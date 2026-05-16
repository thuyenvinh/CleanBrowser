"""Automation engine — DSL flow interpreter on Playwright.

Mode A of the RPA engine described in docs/ARCHITECTURE.md §2.6.
Caller provides a Playwright ``page`` (typically obtained by connecting
to a profile's CDP URL) and a DSL document. The interpreter walks the
node graph and executes each node against the page.

This module is pure Python, holds no DB or HTTP state, and is intended
to be invoked from a router or background worker.
"""

from .context import RunContext
from .interpreter import FlowInterpreter

__all__ = ["FlowInterpreter", "RunContext"]
