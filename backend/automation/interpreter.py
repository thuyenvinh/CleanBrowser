"""DSL flow interpreter.

Walks a node graph (the DSL document defined in docs/ARCHITECTURE.md §2.6)
and dispatches each node to its registered executor in :mod:`.nodes`.

Branching:

- ``condition`` nodes return a ``branch`` marker; the interpreter routes via
  ``next_true`` / ``next_false`` on the node.
- ``loop`` nodes return a ``goto`` marker pointing at the body's first node
  plus a ``return_to_loop`` flag so the interpreter knows to come back to
  the loop node when the body chain terminates (i.e. the last body node has
  no ``next``).
- All other nodes follow ``node["next"][0]`` (linear chains only in Phase 1).
"""

from __future__ import annotations

from typing import Any

from . import nodes
from .context import RunContext


class FlowInterpreter:
    """Run a DSL flow against a single Playwright ``page``."""

    def __init__(self, dsl: dict[str, Any], page: Any):
        if "nodes" not in dsl or not dsl["nodes"]:
            raise ValueError("DSL must contain a non-empty 'nodes' list")
        self.dsl = dsl
        self.page = page
        self.nodes_by_id: dict[str, dict[str, Any]] = {
            n["id"]: n for n in dsl["nodes"]
        }

    async def run(self, ctx: RunContext | None = None) -> RunContext:
        """Execute the flow and return the final :class:`RunContext`."""
        if ctx is None:
            ctx = RunContext()
        current: str | None = self.dsl.get("start") or self.dsl["nodes"][0]["id"]
        # Stack of loop nodes to return to once their body chain terminates.
        loop_stack: list[str] = []

        while current is not None:
            ctx.increment()
            node = self.nodes_by_id.get(current)
            if node is None:
                raise ValueError(f"Unknown node id: {current}")
            nexts, return_to_loop = await self._execute_node(node, ctx)
            if return_to_loop:
                # The current node was a loop entering its body; remember to
                # come back to it after the body chain ends.
                loop_stack.append(current)
            if nexts:
                current = nexts[0]
                continue
            # No nexts: if we're inside a loop body, pop and re-enter the
            # loop node so it can decide whether to iterate again.
            if loop_stack:
                current = loop_stack.pop()
            else:
                current = None
        return ctx

    async def _execute_node(
        self, node: dict[str, Any], ctx: RunContext
    ) -> tuple[list[str], bool]:
        """Dispatch ``node`` and return ``(next_ids, return_to_loop)``."""
        fn = nodes.get_executor(node["type"])
        if fn is None:
            raise ValueError(f"Unsupported node type: {node['type']}")
        result = await fn(ctx, node.get("params", {}), self.page)
        if isinstance(result, dict):
            if "branch" in result:
                key = "next_true" if result["branch"] == "true" else "next_false"
                return list(node.get(key, [])), False
            if "goto" in result:
                return list(result["goto"]), bool(result.get("return_to_loop"))
        return list(node.get("next", [])), False
