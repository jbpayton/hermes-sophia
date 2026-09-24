"""Awake capture: turn messages -> windows, spans, events, outcomes, citations; reads -> external chunks.

No generated text here. The only model call is one batched embedding request per turn; if it fails the
windows are stored without vectors and the night embeds them.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from . import text as T
from .spans import extract_spans
from .store import sha

logger = logging.getLogger(__name__)

_PYTEST = re.compile(r"(\d+ failed|\d+ passed|\d+ errors?)[^\n]*")
_CITE = re.compile(r"\[\[(knowledge/[^\]\s]+)\]\]")
_URL = re.compile(r"https?://[^\s)>\]\"'`]+")
_ERRORISH = re.compile(r'^\s*\{\s*"error"|\bTraceback \(most recent call last\)|\berror:\s', re.I)
MAX_PAGE_CHARS = 60000

_WRAP = re.compile(r'^\s*<untrusted_tool_result[^>]*>\s*(?:The following content was retrieved.*?\n\n)?(.*?)\s*</untrusted_tool_result>\s*$', re.S)
_TEXT_KEYS = ("content", "markdown", "text", "raw_content", "page_content", "body", "snapshot")


def unwrap(content: str) -> str:
    m = _WRAP.match(content or "")
    return m.group(1) if m else (content or "")


def read_payload(content: str, fallback_url: str = "") -> Tuple[bool, List[Tuple[str, str, str]]]:
    """(is_error, [(url, title, text)]) for a web/browser tool result."""
    inner = unwrap(content)
    try:
        data = json.loads(inner)
    except (ValueError, TypeError):
        data = None
    if data is None:
        return bool(_ERRORISH.search(inner[:400])), [(fallback_url, "", inner)]
    if isinstance(data, dict) and (data.get("success") is False or (data.get("error") and not data.get("results"))):
        return True, []
    entries = data.get("results") if isinstance(data, dict) and isinstance(data.get("results"), list) else \
        (data if isinstance(data, list) else [data])
    pages = []
    for ent in entries:
        if not isinstance(ent, dict) or ent.get("error"):
            continue
        text = next((ent[k] for k in _TEXT_KEYS if isinstance(ent.get(k), str) and ent.get(k).strip()), "")
        if text:
            pages.append((ent.get("url") or fallback_url, ent.get("title") or "", text))
    return (not pages), pages


def _said(m: Dict[str, Any], now: float) -> float:
    ts = m.get("timestamp") or m.get("created_at") or m.get("ts")
    if isinstance(ts, (int, float)) and ts > 0:
        return float(ts) / (1000.0 if ts > 1e12 else 1.0)
    if isinstance(ts, str):
        try:
            return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return now


def _args(tc: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    fn = tc.get("function") or {}
    name = fn.get("name") or tc.get("name") or ""
    raw = fn.get("arguments") if fn else tc.get("arguments")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {"_raw": raw[:500]}
    return name, raw if isinstance(raw, dict) else {}


# Worded positively and read in both option orders: on hand-labelled replies the 9B separated made-up claims
# (>= 0.59 unsupported) from acknowledgements, answers from memory and general knowledge (<= 0.34);
# the negative wording in one order did not separate them at all.
GROUND_INSTRUCTIONS = ("Every specific claim the reply makes about the user, the people in their life, or their plans "
                       "(names, places, jobs, dates, times, numbers) is stated in the user's message, the memory "
                       "given, or the tool results. General knowledge about the world does not count as a claim "
                       "about the user.")


def message_hash(session_id: str, m: Dict[str, Any]) -> str:
    """Stable identity of a message whether it comes live from the agent loop or from the session store."""
    content = T.message_text(m.get("content")).strip()
    tcs = m.get("tool_calls") or []
    return sha(session_id, m.get("role") or "", content, m.get("tool_call_id") or "",
               json.dumps([_args(tc) for tc in tcs], sort_keys=True, default=str)[:2000])


def _key_arg(args: Dict[str, Any]) -> str:
    for k in ("command", "url", "urls", "path", "file_path", "query", "q", "pattern", "task", "view", "key", "name"):
        v = args.get(k)
        if v:
            v = v[0] if isinstance(v, list) and v else v
            return str(v)[:120]
    return ""


class Capture:
    def __init__(self, engine):
        self.e = engine
        self._seen: Dict[str, set] = {}

    # --------------------------------------------------------------- turns
    def process_messages(self, session_id: str, messages: Sequence[Dict[str, Any]], now: Optional[float] = None,
                         agent_context: str = "primary", ground: bool = False) -> Dict[str, int]:
        """``ground``: this is a live turn whose injected memory is known, so new agent replies can be checked
        for claims about the user's world that nothing in the turn supports (history imports can't be)."""
        cfg, store = self.e.cfg, self.e.store
        now = now or time.time()
        full = (agent_context or "primary") in cfg["full_capture_contexts"]
        seen = self._seen.setdefault(session_id, store.processed(session_id))
        tool_map: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        prev: Dict[str, Optional[str]] = {"user": None, "assistant": None}
        recent_names: collections.deque = collections.deque(maxlen=6)
        new_windows: List[Dict[str, Any]] = []
        events, outcomes, citations, new_hashes = [], [], [], []
        injected = self.e.last_injection_shingles.get(session_id, set())
        stats = collections.Counter()
        turn_user, turn_tools = "", []

        for m in messages:
            role = m.get("role")
            content = T.message_text(m.get("content"))
            tcs = m.get("tool_calls") or []
            h = message_hash(session_id, m)
            for tc in tcs:
                tool_map[tc.get("id") or ""] = _args(tc)
            is_new = h not in seen
            if role in ("user", "assistant") and content.strip():
                if is_new:
                    if full:
                        ws = self._windows_for(session_id, role, content, _said(m, now), h, prev, recent_names, injected,
                                               speaker=(m.get("name") or None) if role == "user" else None)
                        if role == "assistant" and ground and ws and not self._grounded(session_id, turn_user,
                                                                                       turn_tools, content):
                            for w in ws:
                                w["flags"] = " ".join(sorted(set(w["flags"].split()) | {"ungrounded"}))
                            stats["ungrounded"] += 1
                        new_windows.extend(ws)
                        stats["windows"] += len(ws)
                    if role == "assistant":
                        for c in _CITE.findall(content):
                            citations.append((session_id, f"hermes:{session_id}:{h[:12]}", c, _said(m, now)))
                    if not full and role == "user":
                        events.append((sha("ctx", session_id, h), session_id, agent_context or "context",
                                       content[:160], _said(m, now), None))
                recent_names.extend(T.names_in(content))
                prev[role] = content
                if role == "user":
                    turn_user, turn_tools = content, []
            elif role == "tool" and is_new:
                turn_tools.append(unwrap(content)[:1500])
                name = m.get("name") or m.get("tool_name") or tool_map.get(m.get("tool_call_id") or "", ("", {}))[0]
                args = tool_map.get(m.get("tool_call_id") or "", ("", {}))[1]
                low = (name or "").lower()
                if any(s in low for s in cfg["never_capture_substrings"]):
                    new_hashes.append(h)
                    continue
                said = _said(m, now)
                url = ""
                for k in ("url", "urls"):
                    v = args.get(k)
                    if v:
                        url = v[0] if isinstance(v, list) else str(v)
                        break
                if name in cfg["capture_tools"]:
                    err, pages = read_payload(content, url or f"tool:{name}:{h[:12]}")
                else:
                    err, pages = bool(_ERRORISH.search(unwrap(content)[:400])), []
                events.append((sha("tool", session_id, h), session_id, "tool",
                               f"{name}({_key_arg(args)})" + (" → error" if err else ""), said,
                               json.dumps({"chars": len(content), "pages": len(pages)})))
                stats["events"] += 1
                if full and not err:
                    for purl, ptitle, ptext in pages:
                        if len(ptext) < 200:
                            continue
                        ws = self._chunk(purl or url, ptext, title=ptitle or args.get("title") or "", said=said,
                                         stream="external")
                        new_windows.extend(ws)
                        stats["read_windows"] += len(ws)
                if name in cfg["test_tools"] and "pytest" in str(args.get("command", "")):
                    mt = _PYTEST.search(content)
                    if mt:
                        ok = "failed" not in mt.group(0) and "error" not in mt.group(0)
                        outcomes.append((sha("out", session_id, h), session_id, "pytest", int(ok),
                                         mt.group(0)[:160], said))
                        stats["outcomes"] += 1
            if is_new:
                new_hashes.append(h)

        self._persist(new_windows)
        if events:
            store.xmany("INSERT OR IGNORE INTO events(id,session_id,kind,summary,said,detail) VALUES(?,?,?,?,?,?)", events)
        if outcomes:
            store.xmany("INSERT OR IGNORE INTO outcomes(id,session_id,kind,ok,summary,said) VALUES(?,?,?,?,?,?)", outcomes)
        if citations:
            store.xmany("INSERT INTO citations(session_id,message_ref,target,said) VALUES(?,?,?,?)", citations)
        store.mark_processed(session_id, new_hashes)
        seen.update(new_hashes)
        return dict(stats)

    def _grounded(self, session_id: str, user: str, tools: List[str], reply: str) -> bool:
        """False when the reply states specifics about the user's world that the turn gave it no basis for."""
        if not self.e.cfg["ground_check"] or not (T.names_in(reply) or re.search(r"\d", reply)):
            return True                                    # nothing specific to check
        state = {"message": user[:2000], "memory_given": self.e.last_injection_text.get(session_id, "")[:4000],
                 "tool_results": tools[-4:], "reply": reply[:2000]}
        try:
            return self.e.decider.noul(state, GROUND_INSTRUCTIONS, permutations=2).noul >= 0.5
        except Exception as ex:                            # can't tell: keep it (it is still labelled assistant)
            self.e.set_degraded("decider", str(ex))
            return True

    def _windows_for(self, session_id, role, content, said, h, prev, recent_names, injected,
                     speaker: Optional[str] = None) -> List[Dict[str, Any]]:
        """``speaker``: a user-role message's own ``name`` (several people in one conversation)."""
        cfg = self.e.cfg
        speaker = speaker or (cfg["user_name"] if role == "user" else cfg["agent_name"])
        text, _ = T.redact(content)
        other = prev["assistant" if role == "user" else "user"]
        ctx = T.last_question(other) if T.needs_context(text) else None
        ctx_names = [n for n in recent_names if n not in T.names_in(text)][-3:] if ctx else []
        ref = f"hermes:{session_id}:{h[:12]}"
        out = []
        for i, (wtext, wflags) in enumerate(T.make_windows(text, cfg["window_sentences"], cfg["window_chars"],
                                                           cfg["code_block_chars"])):
            flags = set(wflags.split())
            if role == "assistant":
                flags.add("assistant")
                if injected and T.containment(wtext, injected) >= cfg["echo_threshold"]:
                    flags.add("echo")
            hdr = T.header(speaker, said, ctx if i == 0 else None, ctx_names if i == 0 else ())
            out.append({"id": sha(ref, i), "ref": ref, "session_id": session_id, "speaker": speaker, "said": said,
                        "text": wtext, "index_text": f"{hdr} {wtext}", "flags": " ".join(sorted(flags)),
                        "stream": "conversation", "spans": extract_spans(wtext, said)})
        return out

    # ------------------------------------------------------------ external
    def _chunk(self, url: str, content: str, title: str, said: float, stream: str) -> List[Dict[str, Any]]:
        cfg, store = self.e.cfg, self.e.store
        text, _ = T.redact(content[:MAX_PAGE_CHARS])
        chash = sha(text, n=24)
        if store.one("SELECT ref FROM chunks WHERE content_hash=?", (chash,)):
            return []                                           # same page read again: nothing new
        ref = f"url:{url}#{chash[:8]}"
        store.x("INSERT OR REPLACE INTO chunks(ref,url,title,text,fetched_at,content_hash) VALUES(?,?,?,?,?,?)",
                (ref, url, title, text, said, chash))
        domain = urlparse(url).netloc or url.split(":")[0]
        speaker = f"source:{domain}"
        label = title or domain
        out = []
        for i, (wtext, wflags) in enumerate(T.make_windows(text, cfg["window_sentences"], cfg["window_chars"],
                                                           cfg["code_block_chars"])):
            hdr = f"[{speaker} · {dt.datetime.fromtimestamp(said).strftime('%Y-%m-%d')} · {label}]"
            out.append({"id": sha(ref, i), "ref": ref, "session_id": "", "speaker": speaker, "said": said,
                        "text": wtext, "index_text": f"{hdr} {wtext}", "flags": " ".join(sorted({"external", *wflags.split()})),
                        "stream": stream, "spans": extract_spans(wtext, said)})
        return out

    def ingest_document(self, text: str, url: str, title: str = "", now: Optional[float] = None) -> int:
        ws = self._chunk(url or f"doc:{sha(text)}", text, title, now or time.time(), "external")
        self._persist(ws)
        return len(ws)

    def remember(self, content: str, speaker: str, flags: str = "explicit", session_id: str = "",
                 now: Optional[float] = None) -> List[str]:
        now = now or time.time()
        text, _ = T.redact(content)
        ref = f"note:{sha(text, now)}"
        hdr = T.header(speaker, now)
        ws = [{"id": sha(ref, i), "ref": ref, "session_id": session_id, "speaker": speaker, "said": now, "text": w,
               "index_text": f"{hdr} {w}", "flags": " ".join(sorted({*flags.split(), *wf.split()})),
               "stream": "explicit", "spans": extract_spans(w, now)}
              for i, (w, wf) in enumerate(T.make_windows(text, 3, 480, 800))]
        self._persist(ws)
        return [w["id"] for w in ws]

    # ------------------------------------------------------------- persist
    def _persist(self, windows: List[Dict[str, Any]]) -> None:
        if not windows:
            return
        vecs = None
        try:
            vecs = self.e.embed([w["index_text"] for w in windows], "document")
            self.e.clear_degraded("embed")
        except Exception as ex:
            self.e.set_degraded("embed", str(ex))
            logger.warning("Sophia: embedding failed, storing %d windows without vectors: %s", len(windows), ex)
        self.e.store.add_windows(windows, vecs, self.e.cfg["embed_model"])
