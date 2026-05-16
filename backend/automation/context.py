"""Execution context shared across node executions in a single flow run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunContext:
    """Mutable state for a single DSL flow run.

    - ``variables`` holds DSL-level vars set by ``set_variable`` / ``extract``.
    - ``log_lines`` collects human-readable trace lines for the run report.
    - ``max_steps`` is a hard safety cap to abort runaway loops or cycles.
    - ``steps_taken`` counts every node dispatch.
    """

    variables: dict[str, Any] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)
    max_steps: int = 1000
    steps_taken: int = 0

    def log(self, msg: str) -> None:
        """Append a single line to the run trace."""
        self.log_lines.append(msg)

    def increment(self) -> None:
        """Bump the step counter and abort if the safety cap is exceeded."""
        self.steps_taken += 1
        if self.steps_taken >= self.max_steps:
            raise RuntimeError(
                f"step limit exceeded ({self.max_steps}); aborting flow"
            )
