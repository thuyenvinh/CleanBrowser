"""Script mode automation runtime.

Spawns Node subprocess executing the user's TypeScript/JavaScript code
in a vm context. Returns log + vars + status. Strict timeout.

Phase 7 phase 1 isolation level: subprocess + rlimits + no shell injection.
Production multi-tenant SaaS should wrap this in Firecracker / gVisor
for true isolation. The vm.createContext sandbox keeps user code out of
the Node global scope but does not block fs / child_process access yet
(Phase 7 phase 2 will plug those holes).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import resource
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RUNNER_JS = Path(__file__).parent / "script_runner.js"

DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("SCRIPT_TIMEOUT_SECONDS", "60"))
#: Virtual address space cap (RLIMIT_AS) for the Node child.
#: Must be generous enough for V8's CodeRange reservation (~1–2 GB on
#: 64-bit Linux) — anything below ~2 GB causes V8 to abort with
#: "Failed to reserve virtual memory for CodeRange". This is a *virtual*
#: cap; actual RSS stays small for typical scripts.
MAX_MEMORY_MB = int(os.environ.get("SCRIPT_MAX_MEMORY_MB", "4096"))


def is_available() -> bool:
    """Check if Node + runner.js are available."""
    return shutil.which("node") is not None and _RUNNER_JS.exists()


def _set_rlimits() -> None:
    """Pre-exec hook: cap memory and CPU for the child process."""
    try:
        resource.setrlimit(
            resource.RLIMIT_AS,
            (MAX_MEMORY_MB * 1024 * 1024, MAX_MEMORY_MB * 1024 * 1024),
        )
    except (ValueError, resource.error):
        pass
    try:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (DEFAULT_TIMEOUT_SECONDS * 2, DEFAULT_TIMEOUT_SECONDS * 2),
        )
    except (ValueError, resource.error):
        pass


async def execute_script(
    *,
    code: str,
    language: str = "typescript",
    cdp_url: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run user script in subprocess.

    Returns dict ``{status: 'success'|'failure', log: str, vars: dict,
    error: str | None}``.
    """
    if not is_available():
        return {
            "status": "failure",
            "log": "",
            "vars": {},
            "error": (
                "Node runtime not available — install Node.js to enable "
                "script mode"
            ),
        }

    # Persist script to temp file (subprocess reads it via env var path)
    tmp_dir = tempfile.mkdtemp(prefix="cb-script-")
    script_path = Path(tmp_dir) / (
        "script.ts" if language == "typescript" else "script.js"
    )
    script_path.write_text(code, encoding="utf-8")

    env = {
        "CB_SCRIPT_PATH": str(script_path),
        "CB_LANGUAGE": language,
        "CB_TIMEOUT_MS": str(timeout_seconds * 1000),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "NODE_PATH": os.environ.get("NODE_PATH", ""),
    }
    if cdp_url:
        env["CB_CDP_URL"] = cdp_url

    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(_RUNNER_JS),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            preexec_fn=_set_rlimits,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds + 5,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "status": "failure",
                "log": "",
                "vars": {},
                "error": f"Hard timeout after {timeout_seconds}s",
            }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Parse __CB_RESULT__...__CB_RESULT__ marker from stdout
    text = stdout.decode("utf-8", errors="replace")
    marker = "__CB_RESULT__"
    try:
        start = text.index(marker) + len(marker)
        end = text.index(marker, start)
        result = json.loads(text[start:end])
        # Append any stderr to log for debugging
        err_text = stderr.decode("utf-8", errors="replace").strip()
        if err_text:
            result["log"] = (result.get("log") or "") + "\n[stderr]\n" + err_text
        return result
    except (ValueError, json.JSONDecodeError) as e:
        return {
            "status": "failure",
            "log": text[-2000:],
            "vars": {},
            "error": f"Failed to parse runner output: {e}",
        }
