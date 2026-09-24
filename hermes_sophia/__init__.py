"""Sophia: a passive, associative memory for Hermes Agent that organizes itself while you sleep."""
from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"


def register(ctx) -> None:
    """Hermes memory-provider entry point (directory install or ``hermes_agent.memory_providers``)."""
    from .provider import SophiaProvider
    ctx.register_memory_provider(SophiaProvider())
    skill = Path(__file__).parent / "skills" / "memory" / "SKILL.md"
    if skill.exists():
        try:
            ctx.register_skill("memory", skill, "How to use Sophia's memory tools")
        except Exception:
            pass
