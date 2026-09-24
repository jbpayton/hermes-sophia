"""Configuration: defaults merged with ``memory.sophia`` from the active profile's config.yaml."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULTS: Dict[str, Any] = {
    # LM Studio (OpenAI-compatible) endpoints and model identifiers
    "lmstudio_url": "http://127.0.0.1:1234",
    "lms_cli": "~/.cache/lm-studio/bin/lms",
    "embed_model": "text-embedding-nomic-embed-text-v1.5",
    "decider_model": "qwen/qwen3.5-9b",
    "sleep_model": "qwen/qwen3.8-27b",
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
    "full_capture_contexts": ["primary", ""],
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
    cfg.update({k: v for k, v in section.items() if v is not None})
    if overrides:
        cfg.update(overrides)
    if not cfg.get("sleep_guard_models"):
        cfg["sleep_guard_models"] = [cfg["sleep_model"]]
    cfg["lms_cli"] = os.path.expanduser(cfg["lms_cli"])
    return cfg
