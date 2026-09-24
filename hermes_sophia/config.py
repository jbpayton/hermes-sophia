"""Configuration: defaults merged with ``memory.sophia`` from the active profile's config.yaml.

``FIELDS`` is the single description of every setting. It drives the schema Hermes shows in
``hermes memory setup`` and the dashboard, and the type coercion applied to values typed there.
"""
from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROLES = ("embed", "decider", "sleep")
SERVER_APIS = ("lmstudio", "openai")

DEFAULTS: Dict[str, Any] = {
    # models, and the servers that host them
    "lmstudio_url": "http://127.0.0.1:1234",   # default server for every job
    "lms_cli": "~/.cache/lm-studio/bin/lms",
    "embed_model": "text-embedding-nomic-embed-text-v1.5",
    "embed_url": "default",                   # "default" = lmstudio_url
    "embed_api": "lmstudio",                  # lmstudio | openai (llama-server, vLLM, …)
    "decider_model": "qwen/qwen3.5-9b",
    "decider_url": "default",
    "decider_api": "lmstudio",
    "sleep_model": "qwen/qwen3.8-27b",
    "sleep_url": "default",
    "sleep_api": "lmstudio",
    "sleep_guard_models": None,          # models that must be idle before each sleep call; default [sleep_model]
    # identity
    "user_name": "user",
    "agent_name": "assistant",
    # windowing
    "window_sentences": 3,
    "window_chars": 480,
    "code_block_chars": 800,
    # recall
    "recall_k": 20,
    "gate_top": 10,
    "skip_gate": 0.82,
    "gate_threshold": 0.5,
    "gate_permutations": 1,
    "junk_floor": 0.5,
    "inject_chars": 3000,
    "recency_bonus": 0.01,
    "fts_bonus": 0.03,
    "type_bonus": 0.02,
    "assistant_penalty": 0.06,        # assistant-authored lines rank below the user's words and sources
    "max_assistant_items": 2,
    "question_penalty": 0.04,         # a bare earlier question carries no facts
    "inject_relative_floor": 0.15,    # inject only items within this similarity of the top match
    # capture
    "capture_tools": ["web_extract", "browser_snapshot", "browser_navigate"],
    "never_capture_substrings": ["vault", "credential", "secret", "password"],
    "test_tools": ["terminal", "shell", "bash", "run_command", "execute_code"],
    "full_capture_contexts": ["primary"],
    "echo_threshold": 0.5,
    # timeouts (seconds)
    "embed_timeout": 5.0,
    "decider_timeout": 8.0,
    "sleep_call_timeout": 300.0,
    # sleep
    "sleep_max_wait_s": 900,
    "sleep_poll_s": 10,
    "sleep_session_windows": 40,
    "promote_min_instances": 5,
    "promote_min_sessions": 2,
    "page_min_facts": 3,
    "calibration_min_labels": 50,
}

_LIST_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, list)} | {"sleep_guard_models"}

# Setup-screen gates. They only decide what setup shows; they change no behaviour.
_SERVERS = {"server_layout": "per-job"}
_ADVANCED = {"show_advanced": "yes"}

# (key, description, extra schema attributes). Order is the order setup asks in.
FIELDS: List[Tuple[str, str, Dict[str, Any]]] = [
    ("user_name", "Your name — the speaker label for your lines and the subject of your facts", {}),
    ("agent_name", "The agent's name — the speaker label for its lines", {}),
    ("lmstudio_url", "Default model server URL (LM Studio); every job uses it unless given its own", {}),
    ("embed_model", "Embedding model — every embedding, day and night (nomic-embed-text-v1.5 recommended)", {}),
    ("decider_model", "Decider model — the per-turn check whether memory has anything relevant; reads "
                      "first-token logprobs only (a small instruct model, reasoning off)", {}),
    ("sleep_model", "Night model — context headers, fact extraction and the night's judgments", {}),
    ("server_layout", "Model servers: one shared server, or a server per job?",
     {"choices": ["shared", "per-job"], "default": "shared"}),
    ("embed_url", "Embedding server URL ('default' = the default server)", {"when": _SERVERS}),
    ("embed_api", "Embedding server type", {"when": _SERVERS, "choices": list(SERVER_APIS)}),
    ("decider_url", "Decider server URL ('default' = the default server)", {"when": _SERVERS}),
    ("decider_api", "Decider server type (openai = llama-server, vLLM or another OpenAI-compatible server "
                    "that returns chat logprobs)", {"when": _SERVERS, "choices": list(SERVER_APIS)}),
    ("sleep_url", "Night model server URL ('default' = the default server)", {"when": _SERVERS}),
    ("sleep_api", "Night model server type", {"when": _SERVERS, "choices": list(SERVER_APIS)}),
    ("show_advanced", "Customize recall, capture and night tuning?",
     {"choices": ["no", "yes"], "default": "no"}),
    ("sleep_guard_models", "Models that must be idle before each night call, comma-separated "
                           "(blank = the night model)", {"when": _ADVANCED}),
    ("lms_cli", "Path to LM Studio's lms CLI (used to see whether a model is busy)", {"when": _ADVANCED}),
    ("skip_gate", "Inject without asking the decider at or above this top-1 cosine", {"when": _ADVANCED}),
    ("gate_threshold", "Decider probability needed to inject", {"when": _ADVANCED}),
    ("gate_permutations", "Option orders averaged per gate decision (2 cancels position bias, at 2x cost)",
     {"when": _ADVANCED}),
    ("recall_k", "Candidates fetched per recall", {"when": _ADVANCED}),
    ("gate_top", "Candidates the gate looks at", {"when": _ADVANCED}),
    ("junk_floor", "Candidates below this cosine are never shown to the gate", {"when": _ADVANCED}),
    ("inject_chars", "Size cap for the injected memory block (characters)", {"when": _ADVANCED}),
    ("inject_relative_floor", "Only inject items within this similarity of the top item", {"when": _ADVANCED}),
    ("assistant_penalty", "Ranking penalty for the agent's own earlier lines", {"when": _ADVANCED}),
    ("max_assistant_items", "Most agent-authored items per injection", {"when": _ADVANCED}),
    ("question_penalty", "Ranking penalty for a bare earlier question", {"when": _ADVANCED}),
    ("recency_bonus", "Ranking bonus for recent items", {"when": _ADVANCED}),
    ("fts_bonus", "Ranking bonus for keyword matches", {"when": _ADVANCED}),
    ("type_bonus", "Ranking bonus when a typed span matches the question", {"when": _ADVANCED}),
    ("window_sentences", "Sentences per raw-record window", {"when": _ADVANCED}),
    ("window_chars", "Characters per raw-record window", {"when": _ADVANCED}),
    ("code_block_chars", "Long code blocks become one window truncated to this many characters",
     {"when": _ADVANCED}),
    ("capture_tools", "Tool results captured as external sources, comma-separated", {"when": _ADVANCED}),
    ("never_capture_substrings", "Never capture a tool whose name contains any of these, comma-separated",
     {"when": _ADVANCED}),
    ("test_tools", "Tools whose output is scanned for test outcomes, comma-separated", {"when": _ADVANCED}),
    ("full_capture_contexts", "Agent contexts captured in full, comma-separated (others record only a short "
                              "event per task)", {"when": _ADVANCED}),
    ("echo_threshold", "Overlap above which a reply that repeats injected memory is fenced off as an echo",
     {"when": _ADVANCED}),
    ("embed_timeout", "Embedding call timeout (seconds)", {"when": _ADVANCED}),
    ("decider_timeout", "Decider call timeout (seconds); keep embed + decider well under Hermes's 8 s",
     {"when": _ADVANCED}),
    ("sleep_call_timeout", "Night model call timeout (seconds)", {"when": _ADVANCED}),
    ("sleep_max_wait_s", "How long a night waits for a busy guarded model before yielding (seconds)",
     {"when": _ADVANCED}),
    ("sleep_poll_s", "How often a waiting night checks again (seconds)", {"when": _ADVANCED}),
    ("sleep_session_windows", "Windows per contextualize call", {"when": _ADVANCED}),
    ("promote_min_instances", "Instances before an emergent relation is promoted", {"when": _ADVANCED}),
    ("promote_min_sessions", "Sessions before an emergent relation is promoted", {"when": _ADVANCED}),
    ("page_min_facts", "Facts about an entity before it gets a wiki page", {"when": _ADVANCED}),
    ("calibration_min_labels", "Gold labels needed before the decider is calibrated", {"when": _ADVANCED}),
]


def config_schema() -> List[Dict[str, Any]]:
    """Fields for Hermes's ``hermes memory setup`` and dashboard (key, description, default, choices, when)."""
    out = []
    for key, desc, extra in FIELDS:
        default = extra.get("default", DEFAULTS.get(key))
        if isinstance(default, list):
            default = ", ".join(default)
        elif default is None:
            default = ""
        field = {"key": key, "description": desc, "default": default}
        field.update({k: v for k, v in extra.items() if k != "default"})
        out.append(field)
    return out


def _coerce(key: str, value: Any) -> Any:
    """Values typed into setup arrive as strings; give them the type of the default."""
    if value is None:
        return None
    if key in _LIST_KEYS:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return [str(v) for v in value]
    default = DEFAULTS.get(key)
    if isinstance(default, bool):
        return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(float(value))
    if isinstance(default, float):
        return float(value)
    return str(value).strip() if isinstance(value, str) else value


def endpoint(cfg: Dict[str, Any], role: str) -> Tuple[str, str]:
    """(url, api) of the server that runs ``role`` (embed | decider | sleep)."""
    url = str(cfg.get(f"{role}_url") or "").strip()
    if url.lower() in ("", "default"):
        url = cfg["lmstudio_url"]
    api = str(cfg.get(f"{role}_api") or "lmstudio").strip().lower()
    if api not in SERVER_APIS:
        logger.warning("Sophia: %s_api=%r is not one of %s; using lmstudio", role, api, SERVER_APIS)
        api = "lmstudio"
    return url.rstrip("/"), api


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # available in the Hermes venv
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_config(hermes_home: Optional[str] = None, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    section: Dict[str, Any] = {}
    try:
        from hermes_cli.config import load_config_readonly  # inside Hermes: honours profiles and ${VAR}
        root = load_config_readonly() or {}
        section = ((root.get("memory") or {}).get("sophia") or {})
    except Exception:
        if hermes_home:
            root = _read_yaml(Path(hermes_home) / "config.yaml")
            section = ((root.get("memory") or {}).get("sophia") or {})
    for key, value in {**section, **(overrides or {})}.items():
        if value is None or (value == "" and key in _LIST_KEYS):
            continue
        try:
            cfg[key] = _coerce(key, value)
        except (TypeError, ValueError):
            logger.warning("Sophia: ignoring memory.sophia.%s=%r (expected %s)", key, value,
                           type(DEFAULTS.get(key)).__name__)
    if not cfg.get("sleep_guard_models"):
        cfg["sleep_guard_models"] = [cfg["sleep_model"]]
    cfg["lms_cli"] = os.path.expanduser(cfg["lms_cli"])
    return cfg
