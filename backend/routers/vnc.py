"""VNC WebSocket proxy + RFB protocol filter for KasmVNC compatibility."""

from __future__ import annotations

import asyncio
import logging
import struct

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from .. import database as db
from .. import db_auth
from ..auth_tokens import decode_session
from ..dependencies import (
    ROLE_LEVEL,
    SESSION_COOKIE,
    _check_websocket_origin,
    browser_mgr,
)

logger = logging.getLogger("cloakbrowser.manager")

router = APIRouter(tags=["vnc"])


# ---------------------------------------------------------------------------
# RFB server message translator — KasmVNC BinaryClipboard → standard RFB
# ---------------------------------------------------------------------------


def _parse_kasmvnc_clipboard(data: bytes) -> str | None:
    """Extract text/plain from KasmVNC BinaryClipboard (type 180).

    Format: type(1) + action(1) + flags(4) + entries...
    Each entry: mime_len(u8) + mime(N) + data_len(u32 BE) + data(M)
    """
    if len(data) < 7:
        return None
    offset = 6  # skip type(1) + action(1) + flags(4)
    while offset < len(data):
        if offset + 1 > len(data):
            break
        mime_len = data[offset]
        offset += 1
        if offset + mime_len > len(data):
            break
        mime_type = data[offset:offset + mime_len]
        offset += mime_len
        if offset + 4 > len(data):
            break
        data_len = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if mime_type == b"text/plain":
            end = min(offset + data_len, len(data))
            return data[offset:end].decode("utf-8", errors="replace")
        offset += data_len
    return None


def _build_server_cut_text(text: str) -> bytes:
    """Build standard RFB ServerCutText (type 3) message.

    RFB spec mandates Latin-1 encoding for ServerCutText.
    Characters outside Latin-1 (CJK, emoji, etc.) are replaced with '?'.
    """
    text_bytes = text.encode("latin-1", errors="replace")
    return struct.pack(">BxxxI", 3, len(text_bytes)) + text_bytes


# ---------------------------------------------------------------------------
# RFB client message filter — strip extension types KasmVNC doesn't support
# ---------------------------------------------------------------------------
# noVNC v1.4 batches multiple RFB messages into one WebSocket frame.
# KasmVNC 1.3.3 crashes on unsupported types (150, 248, etc.).
# We parse message boundaries using known sizes and keep only standard types.

# Client→server message sizes (fixed, except 2 and 6 which encode length)
_RFB_MSG_SIZE: dict[int, int | None] = {
    0: 20,    # SetPixelFormat
    2: None,  # SetEncodings — 4 + numEncodings*4 (rewritten to strip bad pseudo-encodings)
    3: 10,    # FramebufferUpdateRequest
    4: 8,     # KeyEvent
    5: 6,     # PointerEvent
    6: None,  # ClientCutText — 8 + length
}

# Extension types that noVNC sends — known sizes so we can skip past them
# instead of breaking and dropping all trailing data in the frame.
_RFB_EXTENSION_SIZE: dict[int, int] = {
    150: 10,  # EnableContinuousUpdates (1+1+2+2+2+2)
    248: 10,  # QEMU-like key event (observed from noVNC 1.4.0)
    252: 4,   # xvp (1+1+1+1)
    255: 4,   # QEMU audio control (1+1+2) — noVNC QEMUExtendedKeyEvent is actually 12
}

# Whitelist of encodings safe to send to KasmVNC.
# Instead of trying to blocklist problematic pseudo-encodings (error-prone —
# we had wrong numbers), we ONLY keep known-good encodings.
# Anything not on this list is stripped from SetEncodings.
_ALLOWED_ENCODINGS: set[int] = {
    # Framebuffer encodings (standard RFB)
    0,    # Raw
    1,    # CopyRect
    2,    # RRE
    5,    # Hextile
    7,    # Tight
    16,   # ZRLE
    # Safe pseudo-encodings
    -239,  # Cursor (0xFFFFFF11) — cursor shape
    -224,  # LastRect (0xFFFFFF20) — performance optimization
    # Tight quality/compress levels (these are just hints)
    *range(-32, -22),   # quality levels 0-9
    *range(-256, -246),  # compress levels 0-9
}


def _rfb_msg_length(data: bytes, offset: int) -> int | None:
    """Return total length of the RFB message at offset, or None if unrecognized."""
    if offset >= len(data):
        return None
    msg_type = data[offset]
    fixed = _RFB_MSG_SIZE.get(msg_type)
    if fixed is not None:
        return fixed
    remaining = len(data) - offset
    if msg_type == 2 and remaining >= 4:  # SetEncodings
        num_enc = struct.unpack_from(">H", data, offset + 2)[0]
        return 4 + num_enc * 4
    if msg_type == 6 and remaining >= 8:  # ClientCutText
        length = struct.unpack_from(">I", data, offset + 4)[0]
        return 8 + length
    # Known extension types — skip past them instead of giving up
    ext_size = _RFB_EXTENSION_SIZE.get(msg_type)
    if ext_size is not None:
        return ext_size
    return None  # truly unknown type


def _rewrite_set_encodings(data: bytes, offset: int, msg_len: int) -> bytes:
    """Keep only whitelisted encodings in a SetEncodings message."""
    _log = logging.getLogger("cloakbrowser.manager")
    num_enc = struct.unpack_from(">H", data, offset + 2)[0]
    kept = []
    stripped = []
    for i in range(num_enc):
        enc = struct.unpack_from(">i", data, offset + 4 + i * 4)[0]  # signed
        if enc in _ALLOWED_ENCODINGS:
            kept.append(enc)
        else:
            stripped.append(enc)
    if not stripped:
        return data[offset:offset + msg_len]
    _log.info("RFB filter: SetEncodings keeping %d: %s, stripped %d: %s", len(kept), kept, len(stripped), stripped)
    result = struct.pack(">BxH", 2, len(kept))
    for enc in kept:
        result += struct.pack(">i", enc)
    return result


def _rewrite_pointer_event(data: bytes, offset: int) -> bytes:
    """Convert standard 6-byte PointerEvent to KasmVNC's 11-byte format.

    Standard RFB:  [5:u8][mask:u8][x:u16][y:u16]          = 6 bytes
    KasmVNC:       [5:u8][mask:u16][x:u16][y:u16][sx:s16][sy:s16] = 11 bytes
    """
    mask = data[offset + 1]
    x = struct.unpack_from(">H", data, offset + 2)[0]
    y = struct.unpack_from(">H", data, offset + 4)[0]
    # Expand mask from u8 to u16.  Scroll deltas (sx, sy) are zero because
    # noVNC encodes scroll as button-mask bits (3=up, 4=down, 5=left, 6=right)
    # which pass through in the mask.  KasmVNC accepts mask-bit scroll on its
    # extended 11-byte format, so explicit deltas are unnecessary.
    return struct.pack(">BHHHhh", 5, mask, x, y, 0, 0)


def _filter_rfb_client_messages(data: bytes) -> bytes:
    """Parse concatenated RFB messages, keep only standard types (0-6).

    Rewrites PointerEvents from 6-byte standard to 11-byte KasmVNC format
    and strips unsupported pseudo-encodings from SetEncodings.
    """
    _log = logging.getLogger("cloakbrowser.manager")
    result = bytearray()
    offset = 0
    msg_idx = 0
    while offset < len(data):
        msg_type = data[offset]
        msg_len = _rfb_msg_length(data, offset)
        if msg_len is None:
            _log.info("RFB filter: DROPPING unknown type=%d at offset=%d/%d, skipping %d trailing bytes, hex=%s",
                       msg_type, offset, len(data), len(data) - offset, data[offset:offset+20].hex())
            break
        if offset + msg_len > len(data):
            # Incomplete message — DO NOT forward partial data, it desynchronizes
            # the RFB stream (KasmVNC buffers partial reads across frames).
            _log.warning("RFB filter: DROPPING incomplete type=%d need=%d have=%d — would desync stream",
                         msg_type, msg_len, len(data) - offset)
            break
        msg_idx += 1
        if msg_type in _RFB_MSG_SIZE:
            # Standard RFB type — keep (with rewrites for KasmVNC compatibility)
            _log.debug("RFB filter: KEEP type=%d len=%d at offset=%d (msg #%d in frame)", msg_type, msg_len, offset, msg_idx)
            if msg_type == 2:  # SetEncodings — whitelist safe encodings
                result.extend(_rewrite_set_encodings(data, offset, msg_len))
            elif msg_type == 5:  # PointerEvent — expand to KasmVNC's 11-byte format
                result.extend(_rewrite_pointer_event(data, offset))
            else:
                result.extend(data[offset:offset + msg_len])
        else:
            # Extension type (150, 248, etc.) — skip but continue parsing
            _log.debug("RFB filter: SKIP extension type=%d len=%d at offset=%d (msg #%d in frame)", msg_type, msg_len, offset, msg_idx)
        offset += msg_len
    if len(result) != len(data):
        _log.info("RFB filter: input=%d output=%d (delta %+d bytes)", len(data), len(result), len(result) - len(data))
    return bytes(result)


# ── Pre-handshake authorization ──────────────────────────────────────────────


async def _authorize_ws_for_profile(
    websocket: WebSocket, profile_id: str, min_level: int
) -> dict | None:
    """Pre-handshake role check for a profile-scoped WebSocket endpoint.

    Mirrors the HTTP-side ``_load_and_check`` in routers/profiles.py:

    * Resolves the session-cookie user (None for legacy AUTH_TOKEN / anonymous).
    * If no user is present → bypass workspace/role check (matches HTTP routes).
    * If profile is missing, the profile has no workspace, the user isn't a
      member, or the user's role is below ``min_level`` → close the socket with
      ``WS_1008_POLICY_VIOLATION`` and return ``None``.

    Returns the profile row on success.
    """
    token = websocket.cookies.get(SESSION_COOKIE)
    user = None
    if token:
        claims = decode_session(token)
        if claims and claims.get("sub"):
            try:
                candidate = db_auth.get_user(claims["sub"])
            except Exception:
                logger.exception(
                    "_authorize_ws_for_profile: db lookup failed for sub=%s",
                    claims.get("sub"),
                )
                candidate = None
            if candidate and candidate.get("status") == "active":
                if not claims.get("tid") or claims["tid"] == candidate.get("tenant_id"):
                    user = candidate

    profile = db.get_profile(profile_id)
    if not profile:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    if user is not None:
        ws_id = profile.get("workspace_id")
        if not ws_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        try:
            role = db_auth.get_member_role(ws_id, user["id"])
        except Exception:
            logger.exception(
                "_authorize_ws_for_profile: get_member_role failed (ws=%s user=%s)",
                ws_id,
                user.get("id"),
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        if not role or ROLE_LEVEL.get(role, 0) < min_level:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None

    return profile


# ── VNC WebSocket Proxy ──────────────────────────────────────────────────────


@router.websocket("/api/profiles/{profile_id}/vnc")
async def vnc_proxy(websocket: WebSocket, profile_id: str):
    """Proxy WebSocket frames between the frontend and a profile's KasmVNC."""
    if not await _check_websocket_origin(websocket):
        return

    # Pre-handshake RBAC: viewing live browser requires launcher+ role.
    if await _authorize_ws_for_profile(websocket, profile_id, min_level=ROLE_LEVEL["launcher"]) is None:
        return

    running = browser_mgr.running.get(profile_id)
    if not running:
        await websocket.close(code=4004, reason="Profile not running")
        return

    # Accept with client's requested subprotocol (if any) — RFC 6455 requires
    # the server must not respond with a subprotocol the client didn't request.
    requested = websocket.scope.get("subprotocols", [])
    subprotocol = "binary" if "binary" in requested else None
    await websocket.accept(subprotocol=subprotocol)

    import websockets

    vnc_url = f"ws://127.0.0.1:{running.ws_port}/websockify"

    try:
        async with websockets.connect(
            vnc_url,
            subprotocols=["binary"],
            origin=f"http://127.0.0.1:{running.ws_port}",
            max_size=None,  # VNC frames can be large (1920x1080 framebuffer)
            ping_interval=None,  # KasmVNC doesn't respond to WS pings
            ping_timeout=None,
            compression=None,  # KasmVNC can't handle permessage-deflate
        ) as vnc_ws:
            logger.info(
                "VNC proxy: connected to KasmVNC for %s (subprotocol=%s)",
                profile_id, vnc_ws.subprotocol,
            )

            # noVNC v1.4 sends extension message types (150=ContinuousUpdates,
            # 248=QEMUKey, etc.) that KasmVNC 1.3.3 doesn't support, causing
            # "unknown message type" → disconnect.
            #
            # noVNC batches multiple RFB messages into a single WebSocket frame,
            # so we must parse the RFB stream to find message boundaries and strip
            # unsupported types before forwarding. Standard client→server types
            # have known fixed sizes (except SetEncodings and ClientCutText which
            # encode their length).

            async def client_to_vnc():
                count = 0
                handshake = 0  # first 3 messages are RFB handshake
                dropped = 0
                try:
                    while True:
                        msg = await websocket.receive()
                        msg_type = msg.get("type", "")
                        if msg_type == "websocket.disconnect":
                            logger.info("VNC proxy [c->v]: client disconnect (code=%s) after %d msgs (%d dropped)", msg.get("code"), count, dropped)
                            break
                        if "bytes" in msg and msg["bytes"]:
                            count += 1
                            data = msg["bytes"]
                            handshake += 1

                            # First 3 messages are RFB handshake — forward as-is
                            if handshake <= 3:
                                logger.debug("VNC handshake #%d: %d bytes hex=%s", handshake, len(data), data[:20].hex())
                                await vnc_ws.send(data)
                                continue

                            # Parse RFB messages and strip unsupported types
                            filtered = _filter_rfb_client_messages(data)
                            if filtered:
                                # Safety: verify first byte is a valid RFB client type
                                if filtered[0] not in _RFB_MSG_SIZE:
                                    logger.error("RFB SAFETY: refusing to send data with invalid first byte=%d hex=%s",
                                                 filtered[0], filtered[:20].hex())
                                    dropped += 1
                                    continue
                                logger.debug("VNC send: %d bytes first_type=%d hex=%s", len(filtered), filtered[0], filtered[:100].hex())
                                await vnc_ws.send(filtered)
                            else:
                                dropped += 1

                        elif "text" in msg and msg["text"]:
                            # noVNC only sends binary frames — text frames are unexpected
                            # and would bypass the RFB filter, so drop them.
                            count += 1
                            logger.warning("VNC proxy [c->v]: DROPPING text frame len=%d (noVNC should only send binary)", len(msg["text"]))
                            dropped += 1
                        else:
                            logger.warning("VNC proxy [c->v]: unhandled msg keys=%s type=%s", list(msg.keys()), msg_type)
                except WebSocketDisconnect as exc:
                    logger.info("VNC proxy [c->v]: WebSocketDisconnect code=%s after %d msgs (%d dropped)", exc.code, count, dropped)
                except Exception as exc:
                    logger.warning("VNC proxy [c->v]: %s: %s (after %d msgs)", type(exc).__name__, exc, count)

            async def vnc_to_client():
                count = 0
                try:
                    async for msg in vnc_ws:
                        count += 1
                        if isinstance(msg, bytes) and len(msg) > 0:
                            msg_type = msg[0]
                            if msg_type == 180:
                                # KasmVNC BinaryClipboard → convert to standard
                                # ServerCutText (type 3) so noVNC can handle it
                                text = _parse_kasmvnc_clipboard(msg)
                                if text:
                                    logger.info("VNC proxy [v->c]: clipboard %d chars", len(text))
                                    await websocket.send_bytes(_build_server_cut_text(text))
                                else:
                                    logger.info("VNC proxy [v->c]: dropped type 180 (no text/plain)")
                                continue
                            await websocket.send_bytes(msg)
                        elif isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                    logger.info("VNC proxy [v->c]: KasmVNC stream ended after %d msgs (close_code=%s)", count, vnc_ws.close_code)
                except WebSocketDisconnect as exc:
                    logger.info("VNC proxy [v->c]: client disconnect code=%s after %d msgs", exc.code, count)
                except Exception as exc:
                    logger.warning("VNC proxy [v->c]: %s: %s (after %d msgs)", type(exc).__name__, exc, count)

            c2v = asyncio.create_task(client_to_vnc(), name="c2v")
            v2c = asyncio.create_task(vnc_to_client(), name="v2c")

            done, pending = await asyncio.wait(
                [c2v, v2c],
                return_when=asyncio.FIRST_COMPLETED,
            )
            finished = [t.get_name() for t in done]
            still_running = [t.get_name() for t in pending]

            # Check if Xvnc is still alive
            vnc_instance = browser_mgr.vnc._allocated.get(running.display)
            xvnc_alive = vnc_instance and vnc_instance.process and vnc_instance.process.poll() is None
            logger.info(
                "VNC proxy: finished=%s pending=%s xvnc_alive=%s display=:%d for %s",
                finished, still_running, xvnc_alive, running.display, profile_id,
            )

            # Dump Xvnc log on disconnect
            import os
            xvnc_log = f"/tmp/xvnc-{running.display}.log"
            if os.path.exists(xvnc_log):
                with open(xvnc_log) as f:
                    log_content = f.read()
                if log_content.strip():
                    for line in log_content.strip().split("\n")[-20:]:
                        logger.info("Xvnc[:%d] %s", running.display, line)

            for task in pending:
                task.cancel()

    except Exception as exc:
        logger.error("VNC proxy connect error for %s: %s: %s", profile_id, type(exc).__name__, exc)
    finally:
        try:
            await websocket.close()
        except Exception as exc:
            logger.debug("VNC proxy: websocket.close() failed: %s", exc)
