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
    "server_url": "",                         # the server every job uses unless given its own ("" = lmstudio_url)
    "server_type": "lmstudio",                # openai (llama-server, vLLM, LM Studio's OpenAI mode, …) | lmstudio
    "lmstudio_url": "http://127.0.0.1:1234",   # the older name for server_url, still read when server_url is unset
    "lms_cli": "~/.cache/lm-studio/bin/lms",
    "embed_model": "text-embedding-nomic-embed-text-v1.5",
    "embed_url": "default",                   # "default" = server_url
    "embed_api": "default",                   # "default" = server_type
    "decider_model": "qwen/qwen3.5-9b",
    "decider_url": "default",
    "decider_api": "default",
    "sleep_model": "qwen/qwen3.8-27b",
    "sleep_url": "default",
    "sleep_api": "default",
    "sleep_guard_models": None,          # models that must be idle before each sleep call; default [sleep_model]
    # the dashboard's graph (not recall's graph_hops, which is how far recall walks)
    "dashboard_graph_view": "neighborhood",  # neighborhood (n hops around one entity) | everything (all, by cluster)
    "dashboard_graph_hops": 2,               # how far a neighborhood reaches, 1-4
    "dashboard_graph_resolution": 1.0,       # cluster size: higher splits memory into more, smaller clusters
    "dashboard_graph_mention_weight": 0.5,   # how strongly a line naming two entities ties them, next to a fact (1.0)
    # identity
    "user_name": "user",
    "agent_name": "assistant",
    "other_speakers": [],             # others who write in your conversations, as "**Name:** ..." or "Name: ..." at
                                      # the start of a message (another agent relaying through the CLI, say)
    # windowing
    "window_sentences": 3,
    "window_chars": 480,
    "code_block_chars": 800,
    # recall
    "recall_k": 50,
    "gate_top": 10,
    "inject_order": "time",          # rank: best first; time: by date, under a heading per day
    "inject_top": 50,                 # injection may draw from this deep in the ranking (the gate sees gate_top)
    "skip_gate": 0.82,
    "gate_threshold": 0.5,
    "gate": "choice",                # choice: one question (nothing needed / about the user but nothing fits / which
                                     # memory bears on it); decider: the older yes/no, which in a large memory lets
                                     # nearly everything through; similarity: no model call, filters little
    "gate_floor": 0.50,              # gate=similarity: the best match's cosine needed to inject anything
    "gate_general": 0.8,             # gate=choice: inject unless "nothing needed" gets this much
    "gate_recheck": 0.05,            # gate=choice: read the reverse option order too when "general" is in [x, 1-x]
                                     # and the second reading could still change the decision
    "gate_split": False,             # gate=choice: list the lines the gate vouched for under Relevant, the rest under
                                     # Possible matches (off by default: on held-out LoCoMo the reader dropped answers
                                     # the split had misfiled)
    "split_min": 0.02,               # ... a memory is vouched for with this share of the memories' probability
    "gate_permutations": 1,
    "junk_floor": 0.5,
    "inject_chars": 9000,
    "recency_bonus": 0.01,
    "fts_bonus": 0.03,
    "fts_weight": 0.05,                # > 0: keyword matches add weight × (bm25 / best bm25) instead of the flat bonus
    "type_bonus": 0.02,
    "mark_passed_dates": True,        # ... and when a phrase that pointed ahead ("next weekend") is over, say "now past"
    "show_resolved_dates": True,      # label relative time words with the date they mean ("last Saturday" = 2023-05-20)
    "time_scope": "boost",            # filter: a date range in the question hides everything outside it; boost: ranks it up
    "time_scope_bonus": 0.05,
    "assistant_penalty": 0.06,        # assistant-authored lines rank below the user's words and sources
    "advice_penalty": 0.06,            # ... and this much more when the user asks for suggestions or advice
    "advice_keeps_questions": True,  # advice requests: the user's own past questions (which describe them) keep full rank
    "max_assistant_items": 2,
    "question_penalty": 0.04,         # a bare earlier question carries no facts
    "inject_relative_floor": 0.25,    # inject only items within this similarity of the top match
    "facts_as": "keys",               # items: a fact competes as its own candidate; keys: it only points at its window
    # graph expansion at recall
    "graph_hops": 1,                  # 0 turns it off
    "graph_decay": 0.9,               # a neighbour scores its seed's score times this…
    "graph_hub_degree": 8,            # …damped by sqrt(hub_degree / facts) for entities with more facts
    "graph_fanout": 3,                # facts taken per entity, best-matching first
    "graph_entities": 6,              # entities expanded per hop
    "graph_adjacent": 1,              # turns before/after a matched window that join the candidates
    "graph_adjacent_decay": 0.9,
    # association: what a cue brings to mind, without a question (sophia_associate; a continuing process's cue)
    "associate_k": 8,                 # memories raised per cue
    "associate_hops": 2,              # how far the graph walk goes (each step weakens the pull by graph_decay)
    "associate_per_source": 2,        # most memories raised from one message or page
    "associate_band": 0.1,            # only memories scoring within this of the cue's best match are raised
    "associate_superseded_weight": 0.5,  # a line that stated something later superseded pulls this much as hard
    "associate_min_words": 4,         # shorter lines ("yes", "ok") say nothing alone and aren't raised
    "associate_habituation_hours": 6.0,  # a memory raised recently is damped; it recovers over about this long
    "associate_conversation_spread": 0.5,  # ...and so, this much, is the rest of its conversation
    "associate_conversation_hours": 2.0,   # lines of one session this close in time count as one conversation
    "associate_recent_hours": 3.0,      # the live conversation's last hours never "come to mind", compacted or not
    "associate_own_weight": 0.5,        # a line the agent itself said pulls this much as hard (its kept thoughts: 1)
    "associate_tasks": False,           # records of finished work (task cards) come to mind; recall keeps them either way
    # the agent's own thoughts (sophia_thought)
    "inject_thoughts": True,          # its kept thoughts can be injected, always labelled as its thoughts
    # capture
    "capture_tools": ["web_extract", "browser_snapshot", "browser_navigate"],
    "never_capture_substrings": ["vault", "credential", "secret", "password"],
    "test_tools": ["terminal", "shell", "bash", "run_command", "execute_code"],
    "full_capture_contexts": ["primary"],
    "echo_threshold": 0.5,
    "ground_check": True,             # flag agent replies that assert facts about the user out of nowhere
    "keep_images": True,              # copy images Hermes cached (it deletes them after a day) into Sophia's store
    # timeouts (seconds)
    "embed_timeout": 5.0,
    "embed_max_chars": 3000,          # longer inputs are embedded from their start (embedding servers cap context;
                                      # dense text like task cards runs ~2.4 characters per token)
    "decider_timeout": 8.0,
    "sleep_call_timeout": 300.0,
    # sleep
    "sleep_max_wait_s": 900,
    "sleep_poll_s": 10,
    "sleep_session_windows": 40,
    "task_judge_chars": 6000,         # a task's action log as the night's judge reads it (start and end kept)
    "night_judge": "decider",         # one-token night judgments on the decider (fast; thresholds measured there) or "night"
    "header_roles": "all",            # "user": model headers only for the user's lines (cheaper on chat-heavy memories)
    "night_parallel": 2,              # night model calls in flight at once (the server's parallel slots)
    "promote_min_instances": 5,
    "promote_min_sessions": 2,
    "page_min_facts": 3,
    "calibration_min_labels": 50,
    "supersede_threshold": 0.85,      # wrongly retiring a fact costs more than missing a change
    "supersede_prescreen": 0.8,       # one reading below this ends it (false ones scored <= 0.74, real ones >= 0.93)
}

_LIST_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, list)} | {"sleep_guard_models"}

# Setup-screen gates. They only decide what setup shows; they change no behaviour.
_SERVERS = {"server_layout": "per-job"}
_ADVANCED = {"show_advanced": "yes"}

# (key, description, extra schema attributes). Order is the order setup asks in.
FIELDS: List[Tuple[str, str, Dict[str, Any]]] = [
    ("user_name", "Your name — the speaker label for your lines and the subject of your facts", {}),
    ("other_speakers", "Others who write in your conversations, recognised by a 'Name:' prefix at the start of their "
                       "message (comma-separated); their lines are labelled with their name instead of yours",
     {"when": _ADVANCED}),
    ("agent_name", "The agent's name — the speaker label for its lines", {}),
    ("server_url", "Model server URL, for example http://127.0.0.1:8080 (llama-server) or http://127.0.0.1:1234 "
                   "(LM Studio); every job uses it unless given its own", {"default": "http://127.0.0.1:1234"}),
    ("server_type", "Server type: openai = llama-server, vLLM or any OpenAI-compatible server that returns logprobs; "
                    "lmstudio = LM Studio's own API", {"choices": ["openai", "lmstudio"], "default": "openai"}),
    ("embed_model", "Embedding model — every embedding, day and night (nomic-embed-text-v1.5 recommended)", {}),
    ("decider_model", "Decider model — the per-turn check whether memory has anything relevant; reads "
                      "first-token logprobs only (a small instruct model, reasoning off)", {}),
    ("sleep_model", "Night model — context headers, fact extraction and the night's judgments", {}),
    ("server_layout", "Model servers: one shared server, or a server per job?",
     {"choices": ["shared", "per-job"], "default": "shared"}),
    ("embed_url", "Embedding server URL ('default' = the default server)", {"when": _SERVERS}),
    ("embed_api", "Embedding server type ('default' = the server type above)", {"when": _SERVERS, "choices": ["default", *SERVER_APIS]}),
    ("decider_url", "Decider server URL ('default' = the default server)", {"when": _SERVERS}),
    ("decider_api", "Decider server type ('default' = the server type above; openai = llama-server, vLLM or another "
                    "OpenAI-compatible server that returns chat logprobs)", {"when": _SERVERS, "choices": ["default", *SERVER_APIS]}),
    ("sleep_url", "Night model server URL ('default' = the default server)", {"when": _SERVERS}),
    ("sleep_api", "Night model server type ('default' = the server type above)", {"when": _SERVERS, "choices": ["default", *SERVER_APIS]}),
    ("dashboard_graph_view", "Dashboard graph: open on one entity's neighborhood, or on everything, coloured by cluster",
     {"choices": ["neighborhood", "everything"]}),
    ("dashboard_graph_hops", "Dashboard graph: how many hops a neighborhood reaches (1-4)", {"minimum": 1, "maximum": 4}),
    ("show_advanced", "Customize recall, capture and night tuning?",
     {"choices": ["no", "yes"], "default": "no"}),
    ("sleep_guard_models", "Models that must be idle before each night call, comma-separated "
                           "(blank = the night model)", {"when": _ADVANCED}),
    ("lms_cli", "Only for LM Studio: path to its lms CLI (used to see whether a model is busy)", {"when": _ADVANCED}),
    ("lmstudio_url", "The older name for the server URL, read only when server_url is unset", {"when": _ADVANCED}),
    ("skip_gate", "Inject without asking the decider at or above this top-1 cosine", {"when": _ADVANCED}),
    ("gate_threshold", "Decider probability needed to inject", {"when": _ADVANCED}),
    ("gate_permutations", "Option orders averaged per gate decision (2 cancels position bias, at twice the time)",
     {"when": _ADVANCED}),
    ("recall_k", "Candidates fetched per recall", {"when": _ADVANCED}),
    ("gate_top", "Candidates the gate looks at", {"when": _ADVANCED}),
    ("gate", "How Sophia decides whether to inject anything: one decider question with an option per memory "
             "(choice: closes on general requests, marks blocks where nothing fits), the older yes/no question "
             "(decider), or the best match's similarity (instant, filters little)",
     {"when": _ADVANCED, "choices": ["choice", "decider", "similarity"]}),
    ("gate_floor", "With gate=similarity: the best match's similarity needed to inject", {"when": _ADVANCED}),
    ("gate_general", "With gate=choice: inject unless the decider is at least this sure the message needs nothing "
                     "from memory", {"when": _ADVANCED}),
    ("gate_recheck", "With gate=choice: ask again with the options reversed when the first reading's 'general' "
                     "probability lies between this and 1 minus this (0 = never)", {"when": _ADVANCED}),
    ("gate_split", "With gate=choice: list the memories the gate vouched for under Relevant and the rest under "
                   "Possible matches", {"when": _ADVANCED}),
    ("split_min", "With gate_split: the share of the memories' probability a line needs to count as Relevant",
     {"when": _ADVANCED}),
    ("inject_top", "How deep in the ranking injection may draw from (still bounded by the relative floor and the "
                   "size cap)", {"when": _ADVANCED}),
    ("junk_floor", "Candidates below this cosine are never shown to the gate", {"when": _ADVANCED}),
    ("inject_chars", "Size cap for the injected memory block (characters)", {"when": _ADVANCED}),
    ("inject_order", "How the injected evidence is listed: best match first, or by date under a heading per day",
     {"when": _ADVANCED, "choices": ["rank", "time"]}),
    ("inject_relative_floor", "Only inject items within this similarity of the top item", {"when": _ADVANCED}),
    ("assistant_penalty", "Ranking penalty for the agent's own earlier lines", {"when": _ADVANCED}),
    ("advice_penalty", "Extra penalty for the agent's earlier lines when the user asks for suggestions or advice, so "
                       "what they said about themselves comes first", {"when": _ADVANCED}),
    ("advice_keeps_questions", "When the user asks for suggestions or advice, their own earlier questions (which say "
                               "a lot about them) are not ranked down", {"when": _ADVANCED}),
    ("max_assistant_items", "Most agent-authored items per injection", {"when": _ADVANCED}),
    ("question_penalty", "Ranking penalty for a bare earlier question", {"when": _ADVANCED}),
    ("recency_bonus", "Ranking bonus for recent items", {"when": _ADVANCED}),
    ("fts_bonus", "Ranking bonus for keyword matches", {"when": _ADVANCED}),
    ("fts_weight", "Graded keyword weight: a match adds this × its bm25 relative to the best (0 = flat fts_bonus)",
     {"when": _ADVANCED}),
    ("type_bonus", "Ranking bonus when a typed span matches the question", {"when": _ADVANCED}),
    ("mark_passed_dates", "Mark a resolved date that pointed ahead when it was said, and is now over, as past",
     {"when": _ADVANCED}),
    ("show_resolved_dates", "Label relative time words in injected memories with the date they mean",
     {"when": _ADVANCED, "choices": ["on", "off"], "default": "on"}),
    ("time_scope", "A date range in the question (\"last week\", \"in March\"): hide everything outside it, or rank "
                   "what's inside it higher", {"when": _ADVANCED, "choices": ["boost", "filter"]}),
    ("time_scope_bonus", "Ranking bonus for things inside the question's date range (time_scope=boost)",
     {"when": _ADVANCED}),
    ("facts_as", "How extracted facts take part in recall: as their own candidates, or as extra search keys for "
                 "the verbatim window they came from", {"when": _ADVANCED, "choices": ["keys", "items"]}),
    ("graph_hops", "Graph expansion at recall: hops from matched entities to connected facts (0 = off)",
     {"when": _ADVANCED}),
    ("graph_decay", "A connected fact scores its seed's score times this", {"when": _ADVANCED}),
    ("graph_hub_degree", "Entities with more facts than this are damped (hubs connect to everything)",
     {"when": _ADVANCED}),
    ("graph_fanout", "Connected facts taken per entity", {"when": _ADVANCED}),
    ("graph_entities", "Entities expanded per hop", {"when": _ADVANCED}),
    ("graph_adjacent", "Turns before and after a matched message that join the candidates (0 = off)",
     {"when": _ADVANCED}),
    ("graph_adjacent_decay", "A neighbouring turn scores its match's score times this", {"when": _ADVANCED}),
    ("associate_k", "Association: memories raised per cue", {"when": _ADVANCED, "minimum": 1, "maximum": 30}),
    ("associate_hops", "Association: how far the graph walk goes from what a cue matches (each step weakens the pull)",
     {"when": _ADVANCED, "minimum": 0, "maximum": 4}),
    ("associate_per_source", "Association: most memories raised from one message or page", {"when": _ADVANCED}),
    ("associate_band", "Association: only memories scoring within this of the cue's best match come up (damping "
                       "reorders them; it never lets unrelated ones in)", {"when": _ADVANCED}),
    ("associate_superseded_weight", "Association: a line that stated something later superseded pulls this much as "
                                    "hard (it keeps its 'later changed' note)", {"when": _ADVANCED, "minimum": 0, "maximum": 1}),
    ("associate_min_words", "Association: lines shorter than this many words (a bare 'yes') aren't raised",
     {"when": _ADVANCED}),
    ("associate_habituation_hours", "Association: a memory raised recently is damped, and recovers over about this "
                                    "many hours", {"when": _ADVANCED}),
    ("associate_conversation_spread", "Association: when a line comes up, the rest of its conversation is damped "
                                      "this much as well (0 = only the line), so a conversation doesn't come back "
                                      "piece by piece", {"when": _ADVANCED, "minimum": 0, "maximum": 1}),
    ("associate_conversation_hours", "Association: lines of one session within this many hours of each other count "
                                     "as one conversation", {"when": _ADVANCED}),
    ("associate_own_weight", "Association: a line the agent itself said pulls this much as hard as one it heard or "
                             "saw (its kept thoughts are unaffected; recall is unaffected)",
     {"when": _ADVANCED, "minimum": 0, "maximum": 1}),
    ("associate_tasks", "Association: records of finished work (task cards) can come to mind (recall finds them either "
                        "way)", {"when": _ADVANCED, "choices": ["on", "off"], "default": "off"}),
    ("associate_recent_hours", "Association: what the live conversation said in this many hours never comes to mind "
                               "as a memory, even once compacted out of the context (it's still working memory)",
     {"when": _ADVANCED}),
    ("inject_thoughts", "The agent's own kept thoughts can be injected before a reply, labelled as its thoughts",
     {"when": _ADVANCED, "choices": ["on", "off"], "default": "on"}),
    ("keep_images", "Keep a copy of each image you send (Hermes deletes its own after a day), so it can be looked at "
                    "again later", {"when": _ADVANCED, "choices": ["on", "off"], "default": "on"}),
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
    ("ground_check", "Check each live agent reply; one that asserts facts about you that nothing in the turn "
                     "supports is kept out of recall", {"when": _ADVANCED, "choices": ["on", "off"], "default": "on"}),
    ("embed_timeout", "Embedding call timeout (seconds)", {"when": _ADVANCED}),
    ("embed_max_chars", "Longer texts are embedded from their first this-many characters (the text itself is kept "
                        "whole); keeps inputs inside the embedding server's context", {"when": _ADVANCED}),
    ("decider_timeout", "Decider call timeout (seconds); keep embed + decider well under Hermes's 8 s",
     {"when": _ADVANCED}),
    ("sleep_call_timeout", "Night model call timeout (seconds)", {"when": _ADVANCED}),
    ("sleep_max_wait_s", "How long a night waits for a busy guarded model before yielding (seconds)",
     {"when": _ADVANCED}),
    ("sleep_poll_s", "How often a waiting night checks again (seconds)", {"when": _ADVANCED}),
    ("sleep_session_windows", "Windows per contextualize call", {"when": _ADVANCED}),
    ("supersede_prescreen", "One reading below this settles 'no change' before the careful two-order reading",
     {"when": _ADVANCED}),
    ("task_judge_chars", "How much of a long task's action log the night's judge reads when deciding how it turned "
                         "out (its first actions and as many of its last as fit)", {"when": _ADVANCED}),
    ("night_judge", "Which model makes the night's one-token judgments (supersession, task outcomes, replay): the "
                    "fast decider, or the night model", {"when": _ADVANCED, "choices": ["decider", "night"]}),
    ("header_roles", "Whose lines get model-written context headers at night: everyone's, or only the user's "
                     "(cheaper when the agent's replies are long)", {"when": _ADVANCED, "choices": ["all", "user"]}),
    ("night_parallel", "Night model calls in flight at once (match the server's parallel slots for the night model)",
     {"when": _ADVANCED}),
    ("promote_min_instances", "Instances before an emergent relation is promoted", {"when": _ADVANCED}),
    ("promote_min_sessions", "Sessions before an emergent relation is promoted", {"when": _ADVANCED}),
    ("page_min_facts", "Facts about an entity before it gets a wiki page", {"when": _ADVANCED}),
    ("calibration_min_labels", "Gold labels needed before the decider is calibrated", {"when": _ADVANCED}),
    ("supersede_threshold", "Decider probability needed before a newer fact retires an older one (high on purpose: "
                            "a wrong retirement hides a true memory)", {"when": _ADVANCED}),
    ("dashboard_graph_resolution", "Dashboard graph: cluster size (higher splits memory into more, smaller clusters)",
     {"when": _ADVANCED, "minimum": 0.2, "maximum": 5}),
    ("dashboard_graph_mention_weight", "Dashboard graph: how strongly a line mentioning two entities ties them, next to a fact "
                             "(1.0)", {"when": _ADVANCED, "minimum": 0, "maximum": 2}),
]


# Short names for setup screens; any key not listed is shown title-cased.
LABELS: Dict[str, str] = {
    "user_name": "Your name", "agent_name": "The agent's name", "other_speakers": "Other speakers",
    "server_url": "Model server URL", "server_type": "Server type", "lmstudio_url": "Server URL (older name)",
    "embed_model": "Embedding model", "decider_model": "Check model", "sleep_model": "Night model",
    "server_layout": "Model servers", "show_advanced": "Show tuning",
    "embed_url": "Embedding server URL", "embed_api": "Embedding server type", "decider_url": "Check server URL",
    "decider_api": "Check server type", "sleep_url": "Night server URL", "sleep_api": "Night server type",
    "dashboard_graph_view": "Graph opens on", "dashboard_graph_hops": "Graph neighborhood hops",
    "dashboard_graph_resolution": "Graph cluster size", "dashboard_graph_mention_weight": "Graph co-mention weight",
    "graph_hops": "Recall graph hops", "lms_cli": "LM Studio lms CLI", "sleep_guard_models": "Night waits for",
    "associate_k": "Association size", "associate_hops": "Association hops",
    "associate_per_source": "Association per source", "associate_band": "Association band",
    "associate_superseded_weight": "Association weight for superseded lines", "associate_min_words": "Association minimum words", "associate_habituation_hours": "Association recovery (hours)",
    "associate_conversation_spread": "Association conversation damping",
    "associate_conversation_hours": "Association conversation span (hours)",
    "associate_recent_hours": "Association: live conversation skipped (hours)",
    "associate_own_weight": "Association weight for the agent's own lines",
    "associate_tasks": "Association includes task cards",
    "inject_thoughts": "Inject own thoughts", "keep_images": "Keep images",
}


def config_schema(current: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Fields for Hermes's ``hermes memory setup`` and dashboard (key, description, default, choices, when).

    ``current``: the effective config. Hermes saves every visible field, filling any the user didn't touch with its
    default, so each default here is what Sophia uses now: a save from setup or the dashboard never changes behaviour
    (an older config's lmstudio_url, say, isn't overwritten by a new field's generic default)."""
    effective: Dict[str, Any] = {}
    if current:
        effective = {k: current.get(k) for k in DEFAULTS if k in current}
        effective["server_url"] = str(current.get("server_url") or current.get("lmstudio_url") or "")
        effective["server_type"] = endpoint(current, "decider")[1]
        for role in ROLES:                      # a job that follows the shared server stays on "default"
            for suffix in ("_url", "_api"):
                if str(current.get(role + suffix) or "default").strip().lower() in ("", "default"):
                    effective[role + suffix] = "default"
    out = []
    for key, desc, extra in FIELDS:
        default = effective[key] if key in effective and effective[key] is not None else extra.get("default", DEFAULTS.get(key))
        if isinstance(default, list):
            default = ", ".join(default)
        elif default is None:
            default = ""
        field = {"key": key, "label": LABELS.get(key, key.replace("_", " ").capitalize()), "description": desc,
                 "default": default}
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
        url = str(cfg.get("server_url") or "").strip() or cfg["lmstudio_url"]
    api = str(cfg.get(f"{role}_api") or "").strip().lower()
    if api in ("", "default"):
        api = str(cfg.get("server_type") or "lmstudio").strip().lower()
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
        from hermes_constants import get_hermes_home
        if hermes_home and Path(hermes_home).resolve() != Path(get_hermes_home()).resolve():
            raise LookupError("another profile than the active one")
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
