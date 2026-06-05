"""LLM-powered DSL flow generator.

Configure via env: ANTHROPIC_API_KEY (claude-sonnet-4-6 by default).
Falls back to dev-mode templated response if no key — useful for
demos / running tests without LLM costs.
"""
from __future__ import annotations
import json, logging, os
from typing import Any

logger = logging.getLogger(__name__)

# Whitelist of node types the interpreter understands. The LLM is instructed
# to stay within this set, but a prompt-injection / model drift could emit
# node types that the interpreter happens to accept (e.g. ``js_eval``,
# ``http_request``). Security review M-05: reject any output that introduces
# a node type outside this set instead of trusting the model.
_ALLOWED_NODE_TYPES: frozenset[str] = frozenset({
    "goto_url",
    "click",
    "type",
    "wait",
    "wait_seconds",
    "extract",
    "condition",
    "loop",
    "set_variable",
    "log",
})

_MAX_NODES_PER_FLOW = 200


def _validate_dsl(data: Any) -> dict[str, Any]:
    """Strict schema check for the generated flow. Raises ``ValueError``.

    Enforced invariants:
      * top-level ``nodes`` is a list, ``start`` is a string
      * every node is a dict with ``id`` + ``type``; type is in
        :data:`_ALLOWED_NODE_TYPES`
      * ``start`` references an existing node id
      * the node graph is bounded by :data:`_MAX_NODES_PER_FLOW`
    """
    if not isinstance(data, dict):
        raise ValueError("DSL root must be an object")
    if "nodes" not in data or "start" not in data:
        raise ValueError("missing nodes or start in generated DSL")
    nodes = data["nodes"]
    if not isinstance(nodes, list):
        raise ValueError("DSL 'nodes' must be a list")
    if not nodes:
        raise ValueError("DSL 'nodes' must not be empty")
    if len(nodes) > _MAX_NODES_PER_FLOW:
        raise ValueError(
            f"DSL contains {len(nodes)} nodes (max {_MAX_NODES_PER_FLOW})"
        )
    ids: set[str] = set()
    for n in nodes:
        if not isinstance(n, dict):
            raise ValueError("each node must be an object")
        nid = n.get("id")
        ntype = n.get("type")
        if not isinstance(nid, str) or not nid:
            raise ValueError("node missing string 'id'")
        if not isinstance(ntype, str) or ntype not in _ALLOWED_NODE_TYPES:
            raise ValueError(f"node {nid!r} has unsupported type {ntype!r}")
        ids.add(nid)
    if data["start"] not in ids:
        raise ValueError(f"start {data['start']!r} does not match any node id")
    return data

_SYSTEM_PROMPT = '''You are an automation flow builder for CleanBrowser, an antidetect browser product.
Given a user's natural-language description, output a JSON DSL flow for the interpreter.

The DSL schema:
{
  "version": 1,
  "start": "<node_id>",
  "nodes": [
    {"id": "<unique>", "type": "<type>", "params": {...}, "next": ["<next_id>"]}
  ]
}

Available node types and their params:
- goto_url: {url: string}                        — navigate to URL
- click: {selector: string}                      — click an element
- type: {selector: string, text: string, delay?: number}  — type text into input
- wait: {selector?: string, timeout?: number, state?: 'visible'|'hidden'|'attached'|'detached'}  — wait for element
- wait_seconds: {seconds: number}                — sleep
- extract: {selector: string, var: string, attribute?: string}  — extract text or attribute to a variable
- condition: {var: string, equals?: any, contains?: string, exists?: bool}  — branch (uses next_true/next_false instead of next)
- loop: {var_count?: string, max?: number, body: [node_ids]}  — repeat sub-flow
- set_variable: {name: string, value: any}      — set a variable
- log: {message: string}                         — write to run log

Rules:
- Output ONLY valid JSON, no markdown fences, no commentary.
- Use CSS selectors that match common patterns (button[type=submit], input[name=...], a.btn-primary).
- Keep flows linear when possible (each node has one "next").
- For condition nodes use next_true / next_false instead of "next".
- Start node id = first node id (e.g. "n1").
- Avoid actions outside the schema (no http_request, no js eval).
- If the request is ambiguous, make reasonable assumptions and add a `log` node explaining.
'''

def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))

async def generate_flow(prompt: str) -> dict[str, Any]:
    """Returns a DSL flow dict. Raises ValueError on parse failure."""
    if not is_configured():
        return _dev_mode_response(prompt)
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic()
        response = await client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if model returned them
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"): text = text[4:]
            text = text.strip()
        data = json.loads(text)
        return _validate_dsl(data)
    except Exception as e:
        logger.exception("AI flow generation failed")
        raise ValueError(f"Failed to generate flow: {e}") from e

def _dev_mode_response(prompt: str) -> dict[str, Any]:
    """Templated demo response when no API key is configured."""
    return {
        "version": 1,
        "start": "n1",
        "nodes": [
            {"id": "n1", "type": "log",
             "params": {"message": f"[AI dev-mode] Received prompt: {prompt[:200]}"},
             "next": ["n2"]},
            {"id": "n2", "type": "goto_url",
             "params": {"url": "https://example.com"},
             "next": ["n3"]},
            {"id": "n3", "type": "extract",
             "params": {"selector": "h1", "var": "title"},
             "next": []},
        ],
        "_notice": "ANTHROPIC_API_KEY not set — returned a placeholder flow. Configure to enable real generation.",
    }
