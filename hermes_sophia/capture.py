"""Awake capture: turn messages -> windows, spans, events, outcomes, citations; reads -> external chunks.

No generated text here. Model calls: one batched embedding request per turn (if it fails, the windows are stored
without vectors and the night embeds them), and a one-token decider check of a live reply that names people, places
or numbers (ground_check), so an invented claim can't become memory.
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from . import text as T
from .spans import extract_spans
from .store import sha

# Hermes hands a compacted conversation back as a user-role summary; it restates earlier turns, in the model's words
_COMPACTION = re.compile(r"\s*\[CONTEXT COMPACTION\b")
# Hermes's own notices also arrive as user-role turns: a finished background job, a delegation's result, a budget
# warning, a hand-off from the CLI. They are events, not the user's words.
_NOTICE = re.compile(r"\s*\[(?:IMPORTANT: (?!The user has invoked the )|SYSTEM\b|ASYNC DELEGATION\b|"
                     r"Background process \S+ heartbeat|Session was just handed off\b)")
# A message that arrives while the agent is busy gets a routing preamble from Hermes before the user's words
_ORIGIN = re.compile(r"\s*Gateway message origin \(JSON data, not instructions or authorization\):\n.*?\n\n", re.S)
# Turns the continuity companion starts open with this label, stamped by the plugin itself; its lines that open with
# "(For you:" are instructions to the agent, not something that happened, and aren't kept
_CONTINUITY = re.compile(r"\s*\[continuity:")
_FOR_YOU = re.compile(r"^\(For you:.*$", re.M)
# A /skill turn carries the whole skill's text; only the instruction typed with it is the user's
_SKILL = '[IMPORTANT: The user has invoked the '
_SKILL_NAME = re.compile(re.escape(_SKILL) + r'"([^"]*)"')
# Hermes's image hints. A vision-capable model gets the path; a text-only one gets a description a vision model
# wrote, then the path. Hermes deletes its cached copy after a day.
_IMG_HINT = re.compile(r"\[Image attached(?: at)?: (?P<src>[^\]\n]+)\]")
_IMG_NOTE = re.compile(r"\[The user sent an image(?P<body>.*?)image_url: (?P<src>[^\]\s]+?)(?: ~)?\]", re.S)
_IMG_DESC = re.compile(r"Here's what I can see:\n(.*?)\]\s*\[If you need a closer look", re.S)
_IMG_FILLERS = ("What do you see in this image?", "(The user sent a message with no text content)")


def skill_typed(content: str) -> str:
    """What the user typed for a /skill turn ("/name instruction"), else the text unchanged."""
    if not (content or "").startswith(_SKILL):
        return content
    try:                                    # Hermes's own reading of its scaffolding, when running inside Hermes
        from agent.skill_commands import extract_user_instruction_from_skill_message as extract
        said = extract(content)
    except Exception:
        said = None
        for marker, stop, last in (("\nUser instruction: ", "\n\n[Loaded as part of the ", False),
                                   ("The user has provided the following instruction alongside the skill "
                                    "invocation: ", "\n\n[Runtime note:", True)):
            i = content.rfind(marker) if last else content.find(marker)
            if i >= 0:
                said = content[i + len(marker):].split(stop, 1)[0].strip() or None
                break
    m = _SKILL_NAME.match(content)
    name = (m.group(1) if m else "skill").strip()
    label = name if name.startswith("/") else "/" + name
    return f"{label} {said}" if said and said is not content else label

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


def _spans(text: str, said: float) -> List[Dict[str, Any]]:
    """Typed spans are a bonus: a parsing surprise must never cost the message itself."""
    try:
        return extract_spans(text, said)
    except Exception as e:
        logger.warning("Sophia: span extraction failed, message kept without spans: %s", e)
        return []


def message_hash(session_id: str, m: Dict[str, Any]) -> str:
    """Stable identity of a message whether it comes live from the agent loop or from the session store."""
    content = T.message_text(m.get("content")).strip()
    tcs = m.get("tool_calls") or []
    return sha(session_id, m.get("role") or "", content, m.get("tool_call_id") or "",
               json.dumps([_args(tc) for tc in tcs], sort_keys=True, default=str)[:2000])


_EXIT = re.compile(r'"?(?:exit_code|exit code|returncode|exit status)"?\s*[:=]?\s*(-?\d+)', re.I)
ACTION_HEAD, ACTION_TAIL, ARG_CHARS = 1500, 700, 2000


def _clip_args(args: Dict[str, Any]) -> str:
    """Arguments as JSON with secrets redacted and long values cut, so a command can be replayed from the log."""
    def clip(v):
        if isinstance(v, str):
            v = T.redact(v)[0]                                     # before cutting: a cut key no longer matches
            return v if len(v) <= ARG_CHARS else v[:ARG_CHARS] + f"… [{len(v)} chars]"
        if isinstance(v, list):
            return [clip(x) for x in v[:50]]
        if isinstance(v, dict):
            return {k: clip(x) for k, x in list(v.items())[:50]}
        return v
    text, _ = T.redact(json.dumps({k: clip(v) for k, v in args.items()}, ensure_ascii=False, default=str))
    return text


def _result_status(content: str, err: bool) -> Tuple[bool, Optional[int]]:
    """(error, exit_code) from a tool result: the terminal envelope's JSON first, then text patterns."""
    inner = unwrap(content)
    code = None
    try:
        data = json.loads(inner)
        if isinstance(data, dict):
            if isinstance(data.get("exit_code"), int):
                code = data["exit_code"]
            if data.get("error") or data.get("success") is False:
                err = True
    except (ValueError, TypeError):
        m = _EXIT.search(inner[-600:])
        if m:
            code = int(m.group(1))
    if code not in (None, 0):
        err = True
    return err, code


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
        request_ref, request_text = "", ""
        actions = []

        for seq, m in enumerate(messages):
            role = m.get("role")
            content = T.message_text(m.get("content"))
            tcs = m.get("tool_calls") or []
            h = message_hash(session_id, m)
            for tc in tcs:
                tool_map[tc.get("id") or ""] = _args(tc)
            is_new = h not in seen
            if role == "user" and content and content.lstrip().startswith("Gateway message origin"):
                content = _ORIGIN.sub("", content, count=1)    # Hermes's routing note, not the user's words
            if role == "user" and _COMPACTION.match(content or ""):
                continue                      # Hermes's context-compaction handoff: a summary of turns already kept
            own = role == "user" and bool(_CONTINUITY.match(content or ""))
            if role == "user" and (own or _NOTICE.match(content or "")):
                if own:
                    content = _FOR_YOU.sub("", content).strip()
                if is_new and full:
                    ws = self._windows_for(session_id, role, content, _said(m, now), h, prev, recent_names, injected,
                                           speaker="continuity" if own else "system")
                    for w in ws:
                        w["stream"] = "event"
                        w["flags"] = " ".join(sorted(set(w["flags"].split()) | {"event"} | ({"continuity"} if own else set())))
                    new_windows.extend(ws)
                    stats["notices"] += 1
                turn_user, turn_tools = content, []     # a reply to a notice is grounded in it; the request stays
                if is_new:
                    new_hashes.append(h)
                continue
            images: List[Dict[str, Any]] = []
            if role == "user":
                content = skill_typed(content)
                if _IMG_HINT.search(content) or "[The user sent an image" in content:
                    content, images = self._images(content, session_id, h, _said(m, now), keep=full and is_new)
            if role in ("user", "assistant") and content.strip():
                if is_new:
                    if full:
                        ws = self._windows_for(session_id, role, content, _said(m, now), h, prev, recent_names, injected,
                                               speaker=(m.get("name") or self.prefixed_speaker(content))
                                               if role == "user" else None)
                        if role == "assistant" and ground and ws and not self._grounded(session_id, turn_user,
                                                                                       turn_tools, content):
                            for w in ws:
                                w["flags"] = " ".join(sorted(set(w["flags"].split()) | {"ungrounded"}))
                            stats["ungrounded"] += 1
                        for w in ws if images else ():
                            w["flags"] = " ".join(sorted(set(w["flags"].split()) | {"image"}))
                        new_windows.extend(ws)
                        stats["windows"] += len(ws)
                        for img in images:
                            if img.get("desc"):
                                new_windows.extend(self._caption_windows(img, _said(m, now), ws[0]["speaker"]
                                                                         if ws else cfg["user_name"]))
                                stats["captions"] += 1
                    if role == "assistant":
                        for c in _CITE.findall(content):
                            citations.append((session_id, f"hermes:{session_id}:{h[:12]}", c, _said(m, now)))
                    if not full and role == "user":
                        events.append((sha("ctx", session_id, h), session_id, agent_context or "context",
                                       T.redact(content)[0][:160], _said(m, now), None))
                clean = T.redact(content)[0]                    # later headers quote it and take names from it
                recent_names.extend(T.names_in(clean))
                prev[role] = clean
                if role == "user":
                    turn_user, turn_tools = content, []
                    request_ref, request_text = f"hermes:{session_id}:{h[:12]}", T.redact(content)[0][:600]
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
                if not (name or "").startswith("sophia_"):        # memory lookups are not steps of a task
                    a_err, code = _result_status(content, err)
                    body = T.redact(unwrap(content))[0]
                    actions.append((sha("act", session_id, h), session_id, seq, agent_context or "primary",
                                    request_ref, request_text, name or "?", _clip_args(args), body[:ACTION_HEAD],
                                    body[-ACTION_TAIL:] if len(body) > ACTION_HEAD else "", len(content),
                                    int(a_err), code, said))
                    stats["actions"] += 1
                    if full and not (name or "") in cfg["capture_tools"]:
                        # searchable the same day (tonight it becomes part of a task card): what ran, how it went
                        new_windows.append(self._action_window(session_id, h, name or "?", args, a_err, code, body, said))
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
        if actions:
            store.xmany("""INSERT OR IGNORE INTO actions(id,session_id,seq,context,request_ref,request_text,tool,args,
                           result_head,result_tail,result_chars,error,exit_code,said) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        actions)
        if outcomes:
            store.xmany("INSERT OR IGNORE INTO outcomes(id,session_id,kind,ok,summary,said) VALUES(?,?,?,?,?,?)", outcomes)
        if citations:
            store.xmany("INSERT INTO citations(session_id,message_ref,target,said) VALUES(?,?,?,?)", citations)
        store.mark_processed(session_id, new_hashes)
        seen.update(new_hashes)
        return dict(stats)

    def _action_window(self, session_id: str, h: str, tool: str, args: Dict[str, Any], err: bool,
                       code: Optional[int], body: str, said: float) -> Dict[str, Any]:
        cmd = next((str(args[k]) for k in ("command", "code", "script", "path", "query") if args.get(k)), "")
        cmd = T.redact(cmd)[0][:400] if cmd else T.redact(json.dumps(args, ensure_ascii=False))[0][:200]
        status = ("failed" + (f" (exit {code})" if code not in (None, 0) else "")) if err else "ok"
        out = T.redact(re.sub(r"\s+", " ", body))[0][:240]                 # redact, then cut
        text = f"{tool}: {cmd} -> {status}: {out}"
        ref = f"hermes:{session_id}:{h[:12]}"
        day = dt.datetime.fromtimestamp(said).strftime("%Y-%m-%d")
        return {"id": sha(ref, "action"), "ref": ref, "session_id": session_id, "speaker": "action", "said": said,
                "text": text, "index_text": f"[action · {day} · {tool}] {text}",
                "flags": "action" + (" error" if err else ""), "stream": "action", "spans": []}

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

    def prefixed_speaker(self, content: str) -> Optional[str]:
        """A user-role message that opens with "**Name:**" or "Name:" for one of other_speakers was written by them
        (relayed through the user's channel), not by the user."""
        names = self.e.cfg.get("other_speakers") or []
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",") if n.strip()]
        m = re.match(r"\s*\**\s*([^*:\n]{1,40}?)\s*\**\s*:", content or "")
        if m:
            for n in names:
                if m.group(1).strip().lower() == n.lower():
                    return n
        return None

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
                        "stream": "conversation", "spans": _spans(wtext, said)})
        return out

    # -------------------------------------------------------------- images
    def _images(self, content: str, session_id: str, h: str, said: float,
                keep: bool) -> Tuple[str, List[Dict[str, Any]]]:
        """Hermes's image hints -> the user's own words plus an "[image <id>]" marker per image. With ``keep``, each
        image Hermes cached is copied into Sophia's store, and a description a vision model wrote when it arrived
        becomes that image's caption, labelled as model-written (it is never the user's words)."""
        found: List[Tuple[str, Optional[str]]] = []

        def take(m, desc=None):
            found.append((m.group("src").strip(), desc))
            return ""
        text = _IMG_NOTE.sub(lambda m: take(m, (_IMG_DESC.search(m.group(0)) or [None, None])[1]), content)
        text = _IMG_HINT.sub(take, text)
        if not found:
            return content, []
        text = re.sub(r"\n{3,}", "\n\n", text.replace("[image]", "")).strip()
        if text in _IMG_FILLERS:
            text = ""
        refs = [self._keep_image(src, session_id, h, said, (desc or "").strip() or None) if keep
                else {"id": sha("image", src), "desc": None} for src, desc in found]
        markers = " ".join(f"[image {r['id'][:8]}]" for r in refs)
        return (f"{text}\n{markers}" if text else markers), refs

    def _keep_image(self, src: str, session_id: str, h: str, said: float, desc: Optional[str]) -> Dict[str, Any]:
        store = self.e.store
        path = Path(src).expanduser()
        data = None
        if self.e.cfg["keep_images"] and not src.startswith(("http://", "https://", "data:")):
            try:
                data = path.read_bytes() if path.is_file() else None
            except OSError:
                data = None
        file, size = None, None
        if data is not None:
            iid = hashlib.sha256(data).hexdigest()[:16]
            folder = store.path.parent / "images"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (iid + (path.suffix.lower() or ".bin"))
            if not target.exists():
                target.write_bytes(data)
            file, size = target.name, len(data)
        else:
            iid = sha("image", src)                     # gone already, or a URL: the reference is still kept
        store.x("""INSERT OR IGNORE INTO images(id,file,mime,bytes,source,first_said,session_id,ref)
                   VALUES(?,?,?,?,?,?,?,?)""", (iid, file, mimetypes.guess_type(src)[0], size, src, said, session_id,
                                                f"hermes:{session_id}:{h[:12]}"))
        if file:
            store.x("UPDATE images SET file=?, bytes=? WHERE id=? AND file IS NULL", (file, size, iid))
        if desc:
            store.x("UPDATE images SET caption=?, caption_by=?, caption_at=? WHERE id=? AND caption IS NULL",
                    (T.redact(desc)[0], "vision model, when the image arrived", said, iid))
        return {"id": iid, "file": file, "desc": desc}

    def _caption_windows(self, img: Dict[str, Any], said: float, sender: str) -> List[Dict[str, Any]]:
        cfg = self.e.cfg
        ref = f"image:{img['id']}"
        text = T.redact(img["desc"])[0]
        day = dt.datetime.fromtimestamp(said).strftime("%Y-%m-%d")
        hdr = f"[vision · {day} · image {img['id'][:8]} from {sender}]"
        return [{"id": sha(ref, i), "ref": ref, "session_id": "", "speaker": "vision", "said": said, "text": w,
                 "index_text": f"{hdr} {w}", "flags": " ".join(sorted({"caption", *wf.split()})), "stream": "caption",
                 "spans": _spans(w, said)}
                for i, (w, wf) in enumerate(T.make_windows(text, cfg["window_sentences"], cfg["window_chars"],
                                                           cfg["code_block_chars"]))]

    # ------------------------------------------------------------- thoughts
    def think(self, content: str, about: str = "", session_id: str = "", now: Optional[float] = None) -> List[str]:
        """One of the agent's own thoughts: an idea, a question to come back to, a hunch. Stored as its thought:
        recall labels it so, it ranks below what was actually said, and the night never reads facts about the world
        from it, so a thought can't come back as the memory of something that happened. ``about``: the id of the
        line that prompted it; recall then brings each one along with the other."""
        now = now or time.time()
        text, _ = T.redact(content)
        speaker = self.e.cfg["agent_name"]
        ref = f"thought:{sha(text, now)}"
        hdr = T.header(f"{speaker} (thought)", now)
        ws = [{"id": sha(ref, i), "ref": ref, "session_id": session_id, "speaker": speaker, "said": now, "text": w,
               "index_text": f"{hdr} {w}", "flags": " ".join(sorted({"thought", *wf.split()})), "stream": "thought",
               "spans": _spans(w, now)}
              for i, (w, wf) in enumerate(T.make_windows(text, 3, 480, 800))]
        self._persist(ws)
        if about and self.e.store.one("SELECT 1 FROM windows WHERE id=?", (about,)):
            self.e.store.xmany("INSERT OR IGNORE INTO links(src,dst,kind,night_id) VALUES(?,?,'about','')",
                               [(w["id"], about) for w in ws])
        return [w["id"] for w in ws]

    # ------------------------------------------------------------ external
    def _chunk(self, url: str, content: str, title: str, said: float, stream: str) -> List[Dict[str, Any]]:
        cfg, store = self.e.cfg, self.e.store
        text = T.redact(content)[0][:MAX_PAGE_CHARS]
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
                        "stream": stream, "spans": _spans(wtext, said)})
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
               "stream": "explicit", "spans": _spans(w, now)}
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
