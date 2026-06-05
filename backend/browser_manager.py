"""Launch/stop/track CloakBrowser instances per profile."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloakbrowser import launch_persistent_context_async

from .vnc_manager import VNCManager

logger = logging.getLogger("cloakbrowser.manager.browser")


def _normalize_proxy(raw: str) -> str:
    """Convert common proxy formats to http://user:pass@host:port.

    Accepts:
      - http://user:pass@host:port  (already valid)
      - host:port:user:pass
      - host:port
    """
    if raw.startswith(("http://", "https://", "socks5://")):
        return raw
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        return f"http://{user}:{passwd}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{raw}"
    return raw


def _validate_proxy(url: str) -> None:
    """Validate that a normalized proxy URL has scheme, host, and port."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", "socks5"):
        raise ValueError(
            f"Invalid proxy scheme '{parsed.scheme}'. Must be http, https, or socks5."
        )
    if not parsed.hostname:
        raise ValueError(f"Proxy URL missing hostname: {url}")
    if not parsed.port:
        raise ValueError(f"Proxy URL missing port: {url}")


def _init_profile_defaults(user_data_dir: Path) -> None:
    """Set up bookmarks and DuckDuckGo search on first launch."""
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)

    # --- Bookmarks (only on first launch) ---
    bookmarks_path = default_dir / "Bookmarks"
    if not bookmarks_path.exists():
        ts = str(int(time.time() * 1_000_000))  # Chrome timestamp format
        _id = 1

        def bm(name: str, url: str) -> dict:
            nonlocal _id
            _id += 1
            return {"type": "url", "id": str(_id), "name": name, "url": url, "date_added": ts}

        def folder(name: str, children: list) -> dict:
            nonlocal _id
            _id += 1
            return {"type": "folder", "id": str(_id), "name": name, "children": children, "date_added": ts, "date_modified": ts}

        bookmarks = {
            "checksum": "",
            "roots": {
                "bookmark_bar": {
                    "type": "folder", "id": "1", "name": "Bookmarks bar",
                    "date_added": ts, "date_modified": ts,
                    "children": [
                        folder("Detection Tests", [
                            bm("Rebrowser Bot Detector", "https://bot-detector.rebrowser.net/"),
                            bm("Incolumitas", "https://bot.incolumitas.com/"),
                            bm("SannySort", "https://bot.sannysoft.com/"),
                            bm("BrowserScan Bot", "https://www.browserscan.net/bot-detection"),
                            bm("FingerprintJS Demo", "https://demo.fingerprint.com/web-scraping"),
                            bm("Pixelscan", "https://pixelscan.net/fingerprint-check"),
                            bm("CreepJS", "https://abrahamjuliot.github.io/creepjs/"),
                            bm("fingerprint-scan", "https://fingerprint-scan.com/"),
                            bm("DeviceInfo Bot", "https://deviceandbrowserinfo.com/are_you_a_bot"),
                        ]),
                        folder("Fingerprint", [
                            bm("BrowserLeaks Canvas", "https://browserleaks.com/canvas"),
                            bm("BrowserLeaks WebGL", "https://browserleaks.com/webgl"),
                            bm("BrowserLeaks Fonts", "https://browserleaks.com/fonts"),
                            bm("BrowserLeaks JS", "https://browserleaks.com/javascript"),
                            bm("FingerprintJS OSS", "https://fingerprintjs.github.io/fingerprintjs/"),
                            bm("Audio FP", "https://audiofingerprint.openwpm.com/"),
                            bm("DeviceInfo", "https://deviceandbrowserinfo.com/info_device"),
                        ]),
                        folder("Headers & TLS", [
                            bm("httpbin headers", "https://httpbin.org/headers"),
                            bm("httpbin IP", "https://httpbin.org/ip"),
                            bm("TLS Fingerprint", "https://tls.browserleaks.com/"),
                        ]),
                        folder("reCAPTCHA", [
                            bm("Google v3 Demo", "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php"),
                            bm("2captcha v3", "https://2captcha.com/demo/recaptcha-v3"),
                            bm("Turnstile", "https://peet.ws/turnstile-test/non-interactive.html"),
                        ]),
                    ],
                },
                "other": {"type": "folder", "id": "2", "name": "Other bookmarks", "children": []},
                "synced": {"type": "folder", "id": "3", "name": "Mobile bookmarks", "children": []},
            },
            "version": 1,
        }
        bookmarks_path.write_text(json.dumps(bookmarks, indent=2))
        logger.info("Created default bookmarks for %s", user_data_dir.name)

    # --- DuckDuckGo as default search engine ---
    prefs_path = default_dir / "Preferences"
    if not prefs_path.exists():
        prefs = {
            "default_search_provider_data": {
                "template_url_data": {
                    "keyword": "duckduckgo.com",
                    "short_name": "DuckDuckGo",
                    "url": "https://duckduckgo.com/?q={searchTerms}",
                    "suggestions_url": "https://duckduckgo.com/ac/?q={searchTerms}&type=list",
                    "favicon_url": "https://duckduckgo.com/favicon.ico",
                }
            },
            "default_search_provider": {
                "enabled": True,
            },
        }
        prefs_path.write_text(json.dumps(prefs, indent=2))
        logger.info("Set DuckDuckGo as default search for %s", user_data_dir.name)


BASE_CDP_PORT = 5100
CDP_PORT_RANGE = 100  # cycle through 5100-5199 to avoid TIME_WAIT collisions


@dataclass
class RunningProfile:
    profile_id: str
    context: Any  # Playwright BrowserContext
    display: int
    ws_port: int
    cdp_port: int
    session_id: str | None = None  # row id in profile_sessions; None pre-DB-write


class BrowserManager:
    def __init__(self):
        self.running: dict[str, RunningProfile] = {}
        self._launching: set[str] = set()  # profile IDs currently being launched
        self.vnc = VNCManager()
        self._lock = asyncio.Lock()
        self._next_cdp_port = BASE_CDP_PORT
        self._auto_launch_task: asyncio.Task | None = None
        # H6: track in-flight post-stop snapshots so cleanup_all can await
        # them before the container exits — fire-and-forget would lose
        # the latest version when a graceful shutdown races the upload.
        self._pending_snapshots: set[asyncio.Task] = set()

    async def launch(self, profile: dict[str, Any]) -> RunningProfile:
        """Launch a browser instance for the given profile."""
        from . import database as db

        profile_id = profile["id"]

        async with self._lock:
            if profile_id in self.running or profile_id in self._launching:
                raise RuntimeError(f"Profile {profile_id} is already running")
            # DB is source of truth: refuse if another worker/process already owns
            # a live session for this profile (Phase 3 multi-worker safety).
            if db.get_active_session_for_profile(profile_id) is not None:
                raise RuntimeError(
                    f"Profile {profile_id} has an active session in another worker"
                )
            self._launching.add(profile_id)

        display, ws_port = await self.vnc.allocate()

        try:
            cdp_port = self._allocate_cdp_port()
        except ValueError:
            async with self._lock:
                self._launching.discard(profile_id)
            await self.vnc.stop_vnc(display)
            raise

        # Persist 'starting' session BEFORE spawning Xvnc/Chromium so that a
        # crash mid-launch still leaves a traceable row (cleaned up by
        # cleanup_stale_sessions on next restart).
        try:
            session = db.create_session(
                profile_id=profile_id,
                display_num=display,
                ws_port=ws_port,
                cdp_port=cdp_port,
            )
        except Exception:
            async with self._lock:
                self._launching.discard(profile_id)
            await self.vnc.stop_vnc(display)
            raise
        session_id = session["id"]

        # Clean stale Chromium lock files (left by previous container crashes)
        user_data_dir = Path(profile["user_data_dir"])
        for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_path = user_data_dir / lock_file
            lock_path.unlink(missing_ok=True)

        # Set up bookmarks and search engine on first launch
        _init_profile_defaults(user_data_dir)

        try:
            # Start KasmVNC on the allocated display
            await self.vnc.start_vnc(
                display,
                ws_port,
                width=profile.get("screen_width", 1920),
                height=profile.get("screen_height", 1080),
            )

            # Build fingerprint args from profile settings
            extra_args = self._build_fingerprint_args(profile)
            extra_args += profile.get("launch_args") or []
            extra_args.append(f"--remote-debugging-port={cdp_port}")

            # Resolve proxy. Preference order (Phase 2, task U):
            #   1. profile.proxy_id → look up the workspace-scoped proxy pool
            #      row and build a fully-qualified URL via db_proxy.
            #      Failure (missing row, decrypt error) fails the launch
            #      loudly — silent fallback would leak the user's real IP.
            #   2. legacy profile.proxy TEXT field → keep parsing
            #      ``host:port[:user:pass]`` shapes.
            proxy: str | None = None
            proxy_id = profile.get("proxy_id")
            if proxy_id:
                try:
                    from .db_proxy import build_proxy_url

                    proxy = build_proxy_url(proxy_id)
                except Exception as exc:
                    logger.error(
                        "failed to build proxy URL for proxy_id=%s: %s",
                        proxy_id, exc,
                    )
                    raise RuntimeError(f"proxy unavailable: {exc}") from exc
            else:
                raw_proxy = profile.get("proxy") or None
                if raw_proxy:
                    proxy = _normalize_proxy(raw_proxy)
            if proxy:
                _validate_proxy(proxy)

            # Phase 6 (task OOO) — dual-core dispatcher. Default is the
            # CloakBrowser-patched Chromium (the historical path); Firefox
            # is opt-in and bypasses CloakBrowser entirely because the
            # fingerprint patches are Chromium-specific (they live in the
            # Chromium fork's renderer). Firefox therefore launches with
            # only the *generic* knobs Playwright's Firefox backend
            # supports — viewport, locale, timezone, user_agent, proxy —
            # and skips fingerprint-seed / GPU / hardware-concurrency.
            #
            # DISPLAY is passed via env kwarg to avoid process-wide
            # os.environ mutation.
            browser_type = (profile.get("browser_type") or "chromium").lower()
            if browser_type == "firefox":
                context = await self._launch_firefox(
                    profile=profile,
                    proxy=proxy,
                    display=display,
                )
            else:
                context = await launch_persistent_context_async(
                    user_data_dir=profile["user_data_dir"],
                    headless=bool(profile.get("headless", False)),
                    proxy=proxy,
                    args=extra_args,
                    timezone=profile.get("timezone") or None,
                    locale=profile.get("locale") or None,
                    humanize=bool(profile.get("humanize", False)),
                    human_preset=profile.get("human_preset", "default"),
                    geoip=bool(profile.get("geoip", False)),
                    color_scheme=profile.get("color_scheme") or None,
                    user_agent=profile.get("user_agent") or None,
                    viewport={
                        "width": profile.get("screen_width", 1920),
                        "height": profile.get("screen_height", 1080) - 133,
                    },
                    env={**os.environ, "DISPLAY": f":{display}"},
                )

            # Inject clipboard listener: captures copied text on every page
            # so the GET /clipboard endpoint can read it via page.evaluate()
            _clipboard_init_js = """
                window.__clipboardText = '';
                document.addEventListener('copy', () => {
                    const sel = window.getSelection();
                    if (sel) window.__clipboardText = sel.toString();
                });
                document.addEventListener('keydown', (e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === 'c' && !e.altKey && !e.shiftKey) {
                        const sel = window.getSelection();
                        if (sel && sel.toString()) window.__clipboardText = sel.toString();
                    }
                });
            """
            await context.add_init_script(_clipboard_init_js)
            # Also inject into already-open pages (about:blank created before init_script)
            for p in context.pages:
                try:
                    await p.evaluate(_clipboard_init_js)
                except Exception as exc:
                    logger.debug("Clipboard init failed on existing page: %s", exc)

            running = RunningProfile(
                profile_id=profile_id,
                context=context,
                display=display,
                ws_port=ws_port,
                cdp_port=cdp_port,
                session_id=session_id,
            )

            # Auto-cleanup if browser crashes or user closes Chrome via VNC
            context.on("close", lambda: asyncio.ensure_future(
                self._on_browser_closed(profile_id)
            ))

            db.mark_session_running(session_id)

            async with self._lock:
                self.running[profile_id] = running
                self._launching.discard(profile_id)

            logger.info(
                "Launched profile %s on display :%d (ws_port=%d, cdp_port=%d, session=%s)",
                profile_id, display, ws_port, cdp_port, session_id,
            )

            return running

        except BaseException as exc:
            async with self._lock:
                self._launching.discard(profile_id)
            await self.vnc.stop_vnc(display)
            try:
                db.end_session(
                    session_id,
                    status="crashed",
                    error_message=f"launch failed: {exc!r}"[:1024],
                )
            except Exception as db_exc:
                logger.warning(
                    "Failed to mark session %s crashed: %s", session_id, db_exc
                )
            raise

    async def _snapshot_after_stop(
        self, profile_id: str, session_id: str | None
    ) -> None:
        """Pack + upload user_data_dir after the browser process is gone.

        Best-effort: never raises into the caller. Skips profiles that
        have no ``workspace_id`` (legacy / orphan rows from before
        Phase 2 multi-tenant) because they have no tenant to charge the
        storage object to. Must run AFTER the Chromium process is dead
        so the on-disk state isn't being mutated mid-tar.
        """
        try:
            from . import database as db
            from . import db_auth
            from .profile_snapshot import snapshot_to_storage_diff as snapshot_to_storage

            profile = db.get_profile(profile_id)
            if not profile:
                logger.debug("snapshot: profile %s gone, skipping", profile_id)
                return
            workspace_id = profile.get("workspace_id")
            if not workspace_id:
                logger.debug(
                    "snapshot: profile %s has no workspace_id, skipping",
                    profile_id,
                )
                return
            ws = db_auth.get_workspace(workspace_id)
            tenant_id = ws.get("tenant_id") if ws else None
            if not tenant_id:
                logger.warning(
                    "snapshot: workspace %s missing tenant_id, skipping %s",
                    workspace_id, profile_id,
                )
                return
            await snapshot_to_storage(
                profile_id=profile_id,
                user_data_dir=profile["user_data_dir"],
                tenant_id=str(tenant_id),
                session_id=session_id,
            )
        except Exception:
            logger.exception("post-stop snapshot failed for %s", profile_id)

    def _schedule_snapshot(
        self, profile_id: str, session_id: str | None
    ) -> asyncio.Task:
        """Create + track a post-stop snapshot task.

        H6: pre-fix this was effectively fire-and-forget — once the
        coroutine left ``stop`` / ``_on_browser_closed`` the runtime
        had no handle, so a container shutdown racing the upload would
        silently drop the latest version. Now ``cleanup_all`` can await
        ``self._pending_snapshots`` before exiting.
        """
        task = asyncio.create_task(
            self._snapshot_after_stop(profile_id, session_id)
        )
        self._pending_snapshots.add(task)
        task.add_done_callback(self._pending_snapshots.discard)
        return task

    async def _on_browser_closed(self, profile_id: str):
        """Called when browser exits (crash, user closed via VNC, or stop())."""
        from . import database as db

        async with self._lock:
            running = self.running.pop(profile_id, None)

        if running:
            logger.info("Browser closed for profile %s, cleaning up", profile_id)
            await self.vnc.stop_vnc(running.display)
            # Snapshot AFTER VNC teardown. Scheduled as a tracked task so
            # cleanup_all (lifespan shutdown) can await pending uploads
            # before the container exits (H6). end_session below only
            # records the row; the snapshot keeps its captured
            # session_id so the FK link still resolves cleanly.
            self._schedule_snapshot(profile_id, running.session_id)
            if running.session_id:
                # end_session is idempotent: if stop() already marked this as
                # 'stopped', the WHERE ended_at IS NULL clause makes this a no-op.
                try:
                    db.end_session(running.session_id, status="crashed")
                except Exception as exc:
                    logger.warning(
                        "Failed to end session %s on close: %s",
                        running.session_id, exc,
                    )

    async def stop(self, profile_id: str):
        """Stop a running browser instance."""
        from . import database as db

        # Pop before close so _on_browser_closed() finds nothing to clean up
        async with self._lock:
            running = self.running.pop(profile_id, None)

        if not running:
            return

        logger.info("Stopping profile %s", profile_id)

        try:
            await running.context.close()
        except Exception as exc:
            logger.warning("Error closing context for %s: %s", profile_id, exc)

        await self.vnc.stop_vnc(running.display)

        # Snapshot user_data_dir to cloud storage now that Chromium has
        # released its on-disk locks. Scheduled as a tracked task (H6)
        # so a graceful shutdown can await pending uploads in
        # cleanup_all; session_id is captured up-front so end_session
        # below cannot race the FK link.
        self._schedule_snapshot(profile_id, running.session_id)

        if running.session_id:
            try:
                db.end_session(running.session_id, status="stopped")
            except Exception as exc:
                logger.warning(
                    "Failed to end session %s on stop: %s",
                    running.session_id, exc,
                )

    def get_status(self, profile_id: str) -> dict[str, Any]:
        """Get running status for a profile."""
        running = self.running.get(profile_id)
        if running:
            return {
                "status": "running",
                "vnc_ws_port": running.ws_port,
                "display": f":{running.display}",
                "cdp_url": f"/api/profiles/{profile_id}/cdp",
            }
        return {"status": "stopped", "vnc_ws_port": None, "display": None, "cdp_url": None}

    async def cleanup_all(self):
        """Stop all running profiles. Called on shutdown."""
        async with self._lock:
            profile_ids = list(self.running.keys())

        for pid in profile_ids:
            await self.stop(pid)

        # H6: stop() schedules the post-stop snapshot as a tracked task
        # rather than awaiting it inline, so we must drain pending
        # uploads before letting lifespan shutdown tear down the event
        # loop. Without this drain a graceful container restart races
        # the upload and silently drops the latest version. Bounded so
        # a stuck upload can't keep the container alive indefinitely.
        if self._pending_snapshots:
            pending = list(self._pending_snapshots)
            logger.info(
                "waiting for %d pending snapshots before shutdown",
                len(pending),
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "snapshot wait timed out — may lose some versions"
                )

        await self.vnc.cleanup_all()

    async def cleanup_stale(self):
        """Kill orphan processes from previous container runs.

        Also marks any ``profile_sessions`` rows left active across a restart as
        'crashed' — those processes are by definition dead, so the DB must
        agree before ``auto_launch_all`` tries to re-launch them (otherwise the
        unique-active-session index would reject the new launch).
        """
        from . import database as db

        await self.vnc.cleanup_stale()
        # H7: a container restart wipes self.running but does NOT kill
        # the Xvnc/Chromium child processes if shutdown was abrupt
        # (SIGKILL, OOM, lost PID 1). Those orphans still hold display
        # numbers, CDP ports, and SingletonLock files, so the next
        # auto_launch_all collides on every resource. Sweep them
        # before allocating anything new.
        await self._kill_orphan_processes()
        try:
            stale = db.cleanup_stale_sessions()
            if stale:
                logger.info("Marked %d stale session(s) as crashed", stale)
        except Exception as exc:
            logger.warning("cleanup_stale_sessions failed: %s", exc)

    async def _kill_orphan_processes(self) -> None:
        """Kill any Xvnc / KasmVNC / Chromium processes left over from a
        previous container lifetime, and clear stale Chromium singleton
        lock files that would otherwise abort the next launch.

        H7: called from ``cleanup_stale`` at startup BEFORE we allocate
        any displays or CDP ports. Best-effort — never raises. If
        ``pkill`` isn't on PATH (minimal images) we skip the process
        sweep but still scrub the lock files, which is the most common
        cause of "browser exited immediately" after a crash-restart.
        """
        import shutil

        killed = 0
        if shutil.which("pkill"):
            for pattern in ("Xvnc", "kasmvncserver", "chromium-browser", "chrome"):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "pkill", "-f", pattern,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    rc = await proc.wait()
                    # pkill rc=0 means at least one process matched and
                    # was signalled; rc=1 means nothing matched (the
                    # happy path on a clean boot).
                    if rc == 0:
                        killed += 1
                        logger.info(
                            "killed orphan process matching %s", pattern
                        )
                except Exception:
                    logger.exception(
                        "orphan kill failed for %s", pattern
                    )
        else:
            logger.warning(
                "pkill not available — skipping orphan process sweep"
            )

        # Scrub Chromium SingletonLock siblings in every per-profile
        # user_data_dir. Chromium refuses to launch if these point at a
        # PID that is no longer ours (or worse, has been reused by an
        # unrelated process post-restart). ``launch()`` already does
        # this for the specific profile it's about to start, but at
        # startup we don't yet know which profiles will be
        # auto-launched, so sweep all of them up front.
        try:
            from . import database as db

            data_dir = Path(getattr(db, "DATA_DIR", "/data")) / "profiles"
            if data_dir.exists():
                for child in data_dir.iterdir():
                    if not child.is_dir():
                        continue
                    for lock in (
                        "SingletonLock",
                        "SingletonCookie",
                        "SingletonSocket",
                    ):
                        for candidate in (child / lock, child / "Default" / lock):
                            try:
                                candidate.unlink(missing_ok=True)
                            except Exception:
                                pass
        except Exception:
            logger.exception("lock file cleanup failed")

        logger.info("orphan cleanup: killed=%d", killed)

    async def auto_launch_all(self):
        """Launch all profiles with auto_launch=True. Called on startup."""
        from . import database as db

        profiles = db.list_profiles()
        auto_profiles = [p for p in profiles if p.get("auto_launch")]
        if not auto_profiles:
            logger.info("No profiles configured for auto-launch")
            return

        logger.info("Auto-launching %d profile(s)...", len(auto_profiles))
        for profile in auto_profiles:
            try:
                await asyncio.wait_for(self.launch(profile), timeout=60)
                logger.info("Auto-launched profile %s (%s)", profile["name"], profile["id"])
            except Exception as exc:
                logger.error(
                    "Auto-launch failed for profile %s (%s): %s",
                    profile["name"], profile["id"], exc,
                )
        logger.info("Auto-launch complete: %d running", len(self.running))

    def _allocate_cdp_port(self) -> int:
        """Find a free CDP port using a rotating counter to avoid TIME_WAIT collisions."""
        for _ in range(CDP_PORT_RANGE):
            port = self._next_cdp_port
            self._next_cdp_port = BASE_CDP_PORT + (
                (self._next_cdp_port + 1 - BASE_CDP_PORT) % CDP_PORT_RANGE
            )
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        raise ValueError("No free CDP ports available in range %d-%d" % (BASE_CDP_PORT, BASE_CDP_PORT + CDP_PORT_RANGE - 1))

    async def _launch_firefox(
        self,
        profile: dict[str, Any],
        proxy: str | None,
        display: int,
    ) -> Any:
        """Launch a stock Playwright Firefox persistent context.

        Phase 6 (task OOO) phase 1: Firefox is the *secondary* engine and
        ships without CloakBrowser's fingerprint patches — there is no
        Firefox build of those patches today, and the value of the option
        is precisely that the detection signal differs from Chromium's.

        Imports Playwright lazily so that (a) the CloakBrowser-only
        Docker image (no firefox binary installed) still imports
        ``browser_manager`` cleanly, and (b) a missing Firefox binary
        produces an actionable error at launch time instead of a
        cryptic ImportError at startup. The fix is to run
        ``playwright install firefox`` inside the container.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover — playwright is a hard dep
            raise RuntimeError(
                "Firefox engine requires the 'playwright' package"
            ) from exc

        pw = await async_playwright().start()
        try:
            context = await pw.firefox.launch_persistent_context(
                user_data_dir=profile["user_data_dir"],
                headless=bool(profile.get("headless", False)),
                proxy={"server": proxy} if proxy else None,
                timezone_id=profile.get("timezone") or None,
                locale=profile.get("locale") or None,
                color_scheme=profile.get("color_scheme") or None,
                user_agent=profile.get("user_agent") or None,
                viewport={
                    "width": profile.get("screen_width", 1920),
                    "height": profile.get("screen_height", 1080) - 133,
                },
                env={**os.environ, "DISPLAY": f":{display}"},
            )
        except Exception as exc:
            # Most common failure: ``playwright install firefox`` was
            # never run inside this image. Re-raise with a hint so the
            # operator doesn't have to grep Playwright's stderr.
            await pw.stop()
            msg = str(exc)
            if "Executable doesn't exist" in msg or "firefox" in msg.lower():
                raise RuntimeError(
                    "Firefox engine not installed — run "
                    "'playwright install firefox' inside the container "
                    f"(underlying error: {exc})"
                ) from exc
            raise
        return context

    def _build_fingerprint_args(self, profile: dict[str, Any]) -> list[str]:
        """Build extra Chromium args from profile fingerprint settings."""
        args: list[str] = [
            "--disable-infobars",
            "--test-type",  # suppress "unsupported flag: --no-sandbox" bad flags warning
            "--use-angle=swiftshader",  # software GL for VNC (no GPU in container)
        ]

        seed = profile.get("fingerprint_seed")
        if seed is not None:
            args.append(f"--fingerprint={seed}")

        p = profile.get("platform")
        if p:
            # Map our "macos" to binary's "macos"
            args.append(f"--fingerprint-platform={p}")

        vendor = profile.get("gpu_vendor")
        if vendor:
            args.append(f"--fingerprint-gpu-vendor={vendor}")

        renderer = profile.get("gpu_renderer")
        if renderer:
            args.append(f"--fingerprint-gpu-renderer={renderer}")

        hw = profile.get("hardware_concurrency")
        if hw is not None:
            args.append(f"--fingerprint-hardware-concurrency={hw}")

        sw = profile.get("screen_width")
        sh = profile.get("screen_height")
        if sw:
            args.append(f"--fingerprint-screen-width={sw}")
        if sh:
            args.append(f"--fingerprint-screen-height={sh}")

        return args
