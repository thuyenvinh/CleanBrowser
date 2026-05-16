"""Node executors for the DSL flow interpreter.

Each executor is registered via the ``@node("name")`` decorator and has the
signature ``async def execute(ctx, params, page)``. Executors may return:

- ``None`` / no return — interpreter falls through to ``node["next"]``.
- ``{"branch": "true"|"false"}`` — interpreter routes via
  ``next_true`` / ``next_false`` (used by ``condition``).
- ``{"goto": [node_ids]}`` — interpreter jumps to the given ids
  (used by ``loop`` to enter its body).

The ``page`` argument is duck-typed: anything that exposes the awaited
Playwright Page methods used below works. Tests pass a small mock object;
production code passes a real Playwright Page obtained via CDP connect.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

NodeExecutor = Callable[["object", dict[str, Any], "object"], Awaitable[Any]]

_EXECUTORS: dict[str, NodeExecutor] = {}


def node(name: str) -> Callable[[NodeExecutor], NodeExecutor]:
    """Register an async function as the executor for a node type."""

    def deco(fn: NodeExecutor) -> NodeExecutor:
        _EXECUTORS[name] = fn
        return fn

    return deco


def get_executor(name: str) -> NodeExecutor | None:
    """Return the executor registered for ``name``, or ``None`` if missing."""
    return _EXECUTORS.get(name)


def registered_types() -> list[str]:
    """Return the list of node type names known to the interpreter."""
    return sorted(_EXECUTORS.keys())


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


@node("goto_url")
async def _goto(ctx, params, page):
    url = params["url"]
    ctx.log(f"goto {url}")
    await page.goto(
        url,
        wait_until=params.get("wait_until", "domcontentloaded"),
    )


@node("click")
async def _click(ctx, params, page):
    selector = params["selector"]
    ctx.log(f"click {selector}")
    await page.click(selector, timeout=params.get("timeout", 5000))


@node("type")
async def _type(ctx, params, page):
    selector = params["selector"]
    text = params["text"]
    delay = params.get("delay")
    ctx.log(f"type {selector!r} ({len(text)} chars)")
    if delay:
        # Human-like keystroke delay (ms between keys).
        await page.type(selector, text, delay=delay)
    else:
        await page.fill(selector, text)


@node("wait")
async def _wait(ctx, params, page):
    selector = params.get("selector")
    timeout = params.get("timeout", 5000)
    state = params.get("state", "visible")
    if selector:
        ctx.log(f"wait selector={selector} state={state} timeout={timeout}")
        await page.wait_for_selector(selector, timeout=timeout, state=state)
    else:
        ctx.log(f"wait timeout={timeout}")
        await page.wait_for_timeout(timeout)


@node("wait_seconds")
async def _wait_seconds(ctx, params, page):
    seconds = float(params["seconds"])
    ctx.log(f"wait_seconds {seconds}")
    await asyncio.sleep(seconds)


@node("extract")
async def _extract(ctx, params, page):
    selector = params["selector"]
    var = params["var"]
    attribute = params.get("attribute")
    element = await page.query_selector(selector)
    if element is None:
        ctx.variables[var] = None
        ctx.log(f"extract {selector} -> {var}=None (not found)")
        return
    if attribute:
        value = await element.get_attribute(attribute)
    else:
        value = await element.text_content()
    ctx.variables[var] = value
    ctx.log(f"extract {selector} -> {var}={value!r}")


@node("condition")
async def _condition(ctx, params, page):
    var = ctx.variables.get(params["var"])
    if "equals" in params:
        result = var == params["equals"]
    elif "contains" in params:
        result = params["contains"] in (var or "")
    elif "exists" in params:
        expected = bool(params["exists"])
        result = (var is not None) == expected
    else:
        result = bool(var)
    branch = "true" if result else "false"
    ctx.log(f"condition var={params['var']!r} -> {branch}")
    return {"branch": branch}


@node("loop")
async def _loop(ctx, params, page):
    """Pure-DSL loop. Enters ``body`` repeatedly up to ``max`` iterations.

    The loop increments ``var_count`` (if provided) in ``ctx.variables`` so
    body nodes can read the current iteration index. The body executes
    sequentially via the interpreter's normal ``next`` chain; when the body's
    final node has no ``next``, control returns to this node and the next
    iteration starts. Implementation: the interpreter handles re-entry by
    treating the returned ``goto`` as the loop's body entry point; we track
    state on ``ctx.variables`` under a private key.
    """
    body = params.get("body") or []
    max_iter = int(params.get("max", 10))
    var_count = params.get("var_count")
    state_key = f"__loop_state_{id(params)}"
    state = ctx.variables.get(state_key, {"i": 0})
    if state["i"] >= max_iter or not body:
        # Done — clean up and fall through to ``next``.
        ctx.variables.pop(state_key, None)
        ctx.log(f"loop done after {state['i']} iters")
        return None
    if var_count:
        ctx.variables[var_count] = state["i"]
    ctx.log(f"loop iter {state['i'] + 1}/{max_iter}")
    state["i"] += 1
    ctx.variables[state_key] = state
    # Re-enter this loop node after the body finishes by appending our own id
    # is handled inside the interpreter via the returned ``goto`` plus a
    # ``return_to`` marker.
    return {"goto": list(body), "return_to_loop": True}


@node("set_variable")
async def _set_variable(ctx, params, page):
    name = params["name"]
    value = params["value"]
    ctx.variables[name] = value
    ctx.log(f"set {name}={value!r}")


@node("log")
async def _log(ctx, params, page):
    message = params["message"]
    ctx.log(str(message))
