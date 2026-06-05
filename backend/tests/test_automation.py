"""Unit tests for the DSL flow interpreter and node executors.

Tests use a tiny in-memory mock of the Playwright Page surface used by
:mod:`backend.automation.nodes`; no real browser is launched.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.automation import FlowInterpreter, RunContext
from backend.automation import nodes as nodes_mod


class _Elem:
    def __init__(self, text=None, attrs=None):
        self._t, self._a = text, attrs or {}

    async def text_content(self):
        return self._t

    async def get_attribute(self, name):
        return self._a.get(name)


class MockPage:
    def __init__(self, selectors=None):
        self.calls: list = []
        self.selectors = selectors or {}

    def _rec(self, name, *a, **kw):
        self.calls.append((name, a, kw))

    async def goto(self, url, **kw):           self._rec("goto", url, **kw)
    async def click(self, sel, **kw):          self._rec("click", sel, **kw)
    async def fill(self, sel, text, **kw):     self._rec("fill", sel, text, **kw)
    async def type(self, sel, text, **kw):     self._rec("type", sel, text, **kw)
    async def wait_for_selector(self, s, **k): self._rec("wait_for_selector", s, **k)
    async def wait_for_timeout(self, ms, **k): self._rec("wait_for_timeout", ms, **k)
    async def query_selector(self, sel):
        self._rec("query_selector", sel)
        return self.selectors.get(sel)


def _exec(name, ctx, params, page):
    return asyncio.run(nodes_mod.get_executor(name)(ctx, params, page))


def test_all_ten_node_types_registered():
    expected = {
        "goto_url", "click", "type", "wait", "wait_seconds",
        "extract", "condition", "loop", "set_variable", "log",
    }
    assert expected.issubset(set(nodes_mod.registered_types()))


def test_page_actions_route_to_playwright():
    page = MockPage()
    _exec("goto_url", RunContext(), {"url": "https://ex.com"}, page)
    _exec("click", RunContext(), {"selector": "#b"}, page)
    _exec("type", RunContext(), {"selector": "i", "text": "hi"}, page)
    _exec("type", RunContext(), {"selector": "i", "text": "hi", "delay": 50}, page)
    names = [c[0] for c in page.calls]
    assert names == ["goto", "click", "fill", "type"]
    # The delayed type forwards the delay kwarg for human-like typing.
    assert page.calls[3][2]["delay"] == 50


def test_wait_variants():
    page = MockPage()
    _exec("wait", RunContext(), {"selector": "h1", "timeout": 100, "state": "visible"}, page)
    _exec("wait", RunContext(), {"timeout": 50}, page)
    _exec("wait_seconds", RunContext(), {"seconds": 0}, page)
    assert page.calls[0][0] == "wait_for_selector"
    assert page.calls[1][0] == "wait_for_timeout"


def test_extract_text_attribute_and_missing():
    page = MockPage(selectors={"h1": _Elem(text="Hi"), "a": _Elem(attrs={"href": "/x"})})
    ctx = RunContext()
    _exec("extract", ctx, {"selector": "h1", "var": "title"}, page)
    _exec("extract", ctx, {"selector": "a", "var": "url", "attribute": "href"}, page)
    _exec("extract", ctx, {"selector": "missing", "var": "none"}, page)
    assert ctx.variables == {"title": "Hi", "url": "/x", "none": None}


@pytest.mark.parametrize(
    "params, value, branch",
    [
        ({"var": "x", "equals": 5}, 5, "true"),
        ({"var": "x", "equals": 5}, 4, "false"),
        ({"var": "x", "contains": "ab"}, "xabz", "true"),
        ({"var": "x", "contains": "ab"}, "xyz", "false"),
        ({"var": "x", "exists": True}, "v", "true"),
        ({"var": "x", "exists": True}, None, "false"),
        ({"var": "x"}, "ok", "true"),
        ({"var": "x"}, "", "false"),
    ],
)
def test_condition_branches(params, value, branch):
    ctx = RunContext(variables={"x": value})
    assert _exec("condition", ctx, params, MockPage()) == {"branch": branch}


def test_set_variable_and_log_record_to_context():
    ctx = RunContext()
    _exec("set_variable", ctx, {"name": "k", "value": 42}, MockPage())
    _exec("log", ctx, {"message": "msg"}, MockPage())
    assert ctx.variables["k"] == 42
    assert "msg" in ctx.log_lines


def test_run_context_step_limit_raises():
    ctx = RunContext(max_steps=3)
    ctx.increment(); ctx.increment()
    with pytest.raises(RuntimeError, match="step limit"):
        ctx.increment()


def test_interpreter_linear_flow():
    dsl = {
        "start": "n1",
        "nodes": [
            {"id": "n1", "type": "set_variable", "params": {"name": "x", "value": 1}, "next": ["n2"]},
            {"id": "n2", "type": "log", "params": {"message": "done"}},
        ],
    }
    ctx = asyncio.run(FlowInterpreter(dsl, MockPage()).run())
    assert ctx.variables["x"] == 1
    assert ctx.steps_taken == 2 and "done" in ctx.log_lines


def test_interpreter_condition_routes_branches():
    dsl = {
        "start": "cond",
        "nodes": [
            {"id": "cond", "type": "condition", "params": {"var": "x", "equals": "ok"},
             "next_true": ["yes"], "next_false": ["no"]},
            {"id": "yes", "type": "set_variable", "params": {"name": "r", "value": "Y"}},
            {"id": "no", "type": "set_variable", "params": {"name": "r", "value": "N"}},
        ],
    }
    ctx_ok = asyncio.run(FlowInterpreter(dsl, MockPage()).run(RunContext(variables={"x": "ok"})))
    ctx_no = asyncio.run(FlowInterpreter(dsl, MockPage()).run(RunContext(variables={"x": "no"})))
    assert ctx_ok.variables["r"] == "Y" and ctx_no.variables["r"] == "N"


def test_interpreter_unknown_node_type_and_id_raise():
    with pytest.raises(ValueError, match="Unsupported node type"):
        asyncio.run(FlowInterpreter(
            {"nodes": [{"id": "n1", "type": "nope"}], "start": "n1"}, MockPage()
        ).run())
    with pytest.raises(ValueError, match="Unknown node id"):
        asyncio.run(FlowInterpreter(
            {"nodes": [{"id": "n1", "type": "log", "params": {"message": "x"},
                        "next": ["ghost"]}], "start": "n1"}, MockPage()
        ).run())


def test_interpreter_step_limit_aborts_cycle():
    dsl = {"nodes": [{"id": "n1", "type": "log", "params": {"message": "x"}, "next": ["n1"]}],
           "start": "n1"}
    with pytest.raises(RuntimeError, match="step limit"):
        asyncio.run(FlowInterpreter(dsl, MockPage()).run(RunContext(max_steps=10)))


def test_interpreter_loop_iterates_and_falls_through():
    dsl = {
        "start": "loop",
        "nodes": [
            {"id": "loop", "type": "loop",
             "params": {"var_count": "i", "max": 3, "body": ["body"]},
             "next": ["done"]},
            {"id": "body", "type": "set_variable", "params": {"name": "last", "value": "v"}},
            {"id": "done", "type": "log", "params": {"message": "after"}},
        ],
    }
    ctx = asyncio.run(FlowInterpreter(dsl, MockPage()).run())
    assert ctx.variables["last"] == "v"
    assert "after" in ctx.log_lines
    # Iteration counter stored under var_count; last value is max-1.
    assert ctx.variables["i"] == 2


def test_interpreter_validates_dsl_and_defaults_start():
    with pytest.raises(ValueError, match="non-empty"):
        FlowInterpreter({"nodes": []}, MockPage())
    # Missing ``start`` falls back to the first node in the list.
    dsl = {"nodes": [{"id": "a", "type": "set_variable", "params": {"name": "v", "value": 1}}]}
    ctx = asyncio.run(FlowInterpreter(dsl, MockPage()).run())
    assert ctx.variables["v"] == 1
