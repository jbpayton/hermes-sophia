"""Continuity: the agent keeps going between messages. A Hermes general plugin, companion to the Sophia memory plugin.

Enable with ``plugins.enabled: [continuity]``. Perception, the standing view and the journal run as soon as it's
enabled; turns of its own need ``plugins.entries.continuity.settings.enabled: true`` (and, in the gateway,
``session_key`` plus ``plugins.entries.continuity.allow_gateway_injection: true``). Design: docs/CONTINUITY.md.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

__version__ = "0.1.0"
logger = logging.getLogger(__name__)

_RUNNING: dict = {}                    # one process per profile home, even if register() runs twice
_SOPHIA_ALIAS = "sophia_continuity_pkg"

UPDATE_SCHEMA = {
    "name": "continuity_update",
    "description": ("Keep your own working state, which the standing view shows you every turn: what you're focused on, "
                    "your open threads, what you're waiting for. In a turn of your own ([continuity: …]), 'let_go' "
                    "records why you're letting something go; letting go is a normal outcome."),
    "parameters": {"type": "object", "properties": {
        "focus": {"type": "string", "description": "What you're focused on now (empty string clears it)."},
        "add_thread": {"type": "string", "description": "An open thread to keep in view."},
        "close_thread": {"type": "string", "description": "Id or words of a thread that's done."},
        "waiting_for": {"type": "string", "description": "Something you're waiting for (a job, a reply)."},
        "by": {"type": "string", "description": "With waiting_for: when you expect it (\"+30m\", \"+2h\", \"14:30\" or "
                                                "an ISO time); if it's late, you'll notice."},
        "done_waiting": {"type": "string", "description": "Id or words of something that arrived."},
        "let_go": {"type": "string", "description": "Why you're letting this turn's item go."}}},
}


def guide(user: str, quiet_hours: str) -> str:
    return (f"# Continuity\n"
            f"You keep going between messages. Besides {user}'s messages, some turns come from your own continuing "
            f"process. They always start with \"[continuity: …]\" and are never {user}'s words:\n"
            "- \"something came to mind\": a memory raised by what happened lately;\n"
            "- \"a goal of yours\": one of your goals, when nothing else is waiting (continuity_goal keeps them);\n"
            "- \"noticed\": time passing, noticed: quiet for longer than usual, something overdue, a planned date gone "
            "by, or the morning (the one scheduled moment of the day);\n"
            f"- \"a message you held for {user}\": something you wrote earlier that waited for a good time.\n"
            "In those turns do whatever seems worthwhile: think it through, use your tools, keep a thought "
            "(sophia_thought), update your working state (continuity_update), or let it go. (continuity_update and "
            "continuity_goal may be in your tool_search catalog rather than your tool list.) Letting go is normal, and "
            f"declining or resting is always fine. Reply [SILENT] when there's nothing to say to {user}.\n"
            f"If you do write a reply in one of these turns, it reaches {user} only when outreach is allowed (never "
            f"in quiet hours, {quiet_hours}, and within a daily limit); otherwise it is held, and your standing view "
            f"shows it. Write it as a message to {user} about their life or your shared work. Reflections on how "
            "your own memory or process works belong in a thought (sophia_thought), not a message.\n"
            "Every turn also carries a \"[standing view …]\" frame of your situation: the time, "
            f"{user}, finished jobs, your focus and threads, what came to mind, your energy. Each line says where it "
            "came from: perceived, remembered, or your own. Only the latest frame is current; a change frame shows "
            "old → new.")


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def sophia_module(sub: str, path: str = ""):
    """Sophia's package under its own name (the memory provider's own import is left alone)."""
    if _SOPHIA_ALIAS not in sys.modules:
        here = Path(__file__).resolve().parent
        for cand in [Path(path).expanduser()] if path else [here.parent / "hermes_sophia", _home() / "plugins" / "sophia"]:
            init = cand / "__init__.py"
            if init.exists():
                spec = importlib.util.spec_from_file_location(_SOPHIA_ALIAS, init, submodule_search_locations=[str(cand)])
                mod = importlib.util.module_from_spec(spec)
                sys.modules[_SOPHIA_ALIAS] = mod
                spec.loader.exec_module(mod)
                break
        else:
            raise ImportError("Sophia's package wasn't found; set plugins.entries.continuity.settings.sophia_path")
    return importlib.import_module(f"{_SOPHIA_ALIAS}.{sub}")


def _user_name(cfg: dict) -> str:
    try:
        return sophia_module("config", cfg["sophia_path"]).load_config(str(_home()))["user_name"]
    except Exception:
        return "the user"


def should_run(argv=None, platform: str = "") -> bool:
    """Only the long-lived process that serves the loop's platform takes turns of its own: the gateway for a messaging
    platform, an interactive chat for the CLI. Never a one-shot query, a CLI subcommand or the dashboard. (The gateway
    loads every profile's plugins, so without the platform check a CLI profile's loop would run there too, injecting
    into a conversation that doesn't exist.)"""
    if os.environ.get("HERMES_CONTINUITY_RUN") in ("1", "0"):
        return os.environ["HERMES_CONTINUITY_RUN"] == "1"
    a = list(argv if argv is not None else sys.argv)
    cli = (platform or "").lower() == "cli"
    if "gateway" in a and "run" in a:
        return not cli
    return "chat" in a and not any(x in a for x in ("-q", "--query", "--query-file", "-Q")) and (cli or not platform)


def register(ctx) -> None:
    from .config import load
    from .loop import Continuity
    from .store import Store

    cfg = load(getattr(ctx, "get_config", None))
    home = _home()
    key = str(home)
    if key in _RUNNING:
        cont = _RUNNING[key]
    else:
        store = Store(home / "plugin-data" / "continuity" / "continuity.db")

        def inject(text: str, display=None) -> bool:
            key = cfg["session_key"] or None
            if display:
                try:                                  # Hermes with the plugin-turn display patch
                    return bool(ctx.inject_message(text, role="user", session_key=key, display=display))
                except TypeError:
                    pass                              # an unpatched Hermes: the turn shows what its config allows
            return bool(ctx.inject_message(text, role="user", session_key=key))

        cont = Continuity(store, cfg, inject, memory=None, user_name=_user_name(cfg))
        _RUNNING[key] = cont

    ctx.register_hook("pre_llm_call", cont.on_turn_start)
    ctx.register_hook("transform_llm_output", cont.on_reply)
    ctx.register_hook("on_session_end", cont.on_turn_end)
    ctx.register_hook("pre_api_request", cont.on_api_start)
    ctx.register_hook("post_api_request", cont.on_api)
    ctx.register_hook("post_llm_call", cont.on_turn_done)
    from .goals import SCHEMA_TOOL as GOAL_SCHEMA
    ctx.register_tool(name="continuity_goal", toolset="continuity", schema=GOAL_SCHEMA,
                      handler=lambda params, **kw: json.dumps(cont.goals.handle(params or {}), default=str))
    ctx.register_tool(name="continuity_update", toolset="continuity", schema=UPDATE_SCHEMA,
                      handler=lambda params, **kw: json.dumps(cont.update(params or {}), default=str))
    try:
        ctx.register_system_prompt_section("continuity.guide", guide(cont.user_name, cfg["quiet_hours"]),
                                           position="after_memory", max_chars=4000)
    except Exception as ex:
        logger.warning("continuity: system prompt section not registered: %s", ex)
    try:
        from .cli import cmd, setup
        ctx.register_cli_command("continuity", "The continuing process: status, view, queue, journal, outbox, pause",
                                 setup, cmd)
    except Exception as ex:
        logger.warning("continuity: CLI not registered: %s", ex)

    if cfg["enabled"] and should_run(platform=cfg.get("platform", "")) and cont._thread is None:
        def boot():
            try:
                cont.set_memory(sophia_module("api", cfg["sophia_path"]).Memory(str(home)))
                cont.user_name = cont.memory.user_name
            except Exception as ex:
                logger.warning("continuity: running without Sophia (nothing will come to mind): %s", ex)
            cont.start()
        threading.Thread(target=boot, name="continuity-boot", daemon=True).start()
        logger.info("continuity: started (platform=%s, outreach=%s)", cfg["platform"] or "any", cfg["outreach"])
