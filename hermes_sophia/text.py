"""Text utilities: sentence windows, secret redaction, heuristic context headers, echo detection."""
from __future__ import annotations

import datetime as _dt
import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

# ----------------------------------------------------------------- redaction (from Gemmery, precision over recall)
_SECRETS: List[Tuple[str, re.Pattern]] = [
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("bearer-header", re.compile(r"(?i)\bauthorization:\s*bearer\s+[A-Za-z0-9._~+/-]{16,}={0,2}")),
]


def redact(text: str) -> Tuple[str, List[str]]:
    hits = []
    for name, pat in _SECRETS:
        if pat.search(text):
            hits.append(name)
            text = pat.sub(f"[REDACTED:{name}]", text)
    return text, hits


# ----------------------------------------------------------------- sentences and windows
_ABBR = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof|St|Mt|Inc|Ltd|Jr|Sr|vs|etc|e\.g|i\.e|approx|No|Fig)\.")
_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[A-Z0-9`\"'(\[])")
_FENCE = re.compile(r"```.*?```", re.S)
_PLACEHOLDER = "․"  # one-dot leader stands in for protected periods


def split_sentences(text: str) -> List[str]:
    out: List[str] = []
    for para in re.split(r"\n\s*\n|\n(?=\s*[-*•\d]+[.)]?\s)", text):
        para = para.strip()
        if not para:
            continue
        prot = _ABBR.sub(lambda m: m.group(0).replace(".", _PLACEHOLDER), para)
        parts = _SPLIT.split(prot)
        out.extend(p.replace(_PLACEHOLDER, ".").strip() for p in parts if p.strip())
    return out


def make_windows(text: str, max_sentences: int = 3, max_chars: int = 480, code_chars: int = 800) -> List[Tuple[str, str]]:
    """[(window_text, flags)] — fenced code longer than ``code_chars`` becomes one truncated 'code' window."""
    windows: List[Tuple[str, str]] = []
    pos = 0
    for m in _FENCE.finditer(text):
        windows.extend(_prose_windows(text[pos:m.start()], max_sentences, max_chars))
        code = m.group(0)
        if len(code) > code_chars:
            windows.append((code[:max_chars].rstrip() + " …", "code"))
        else:
            windows.append((code, "code"))
        pos = m.end()
    windows.extend(_prose_windows(text[pos:], max_sentences, max_chars))
    return [(w, f) for w, f in windows if w.strip()]


def _prose_windows(text: str, max_sentences: int, max_chars: int) -> List[Tuple[str, str]]:
    sents = split_sentences(text)
    out, cur = [], []
    for s in sents:
        while len(s) > max_chars:                       # very long sentence: hard wrap on whitespace
            cut = s.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if cur:
                out.append((" ".join(cur), ""))
                cur = []
            out.append((s[:cut].strip(), ""))
            s = s[cut:].strip()
        if cur and (len(cur) >= max_sentences or len(" ".join(cur)) + len(s) + 1 > max_chars):
            out.append((" ".join(cur), ""))
            cur = []
        if s:
            cur.append(s)
    if cur:
        out.append((" ".join(cur), ""))
    return out


# ----------------------------------------------------------------- heuristic context header
_ASSENT = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok|okay|no|nope|nah|do it|go ahead|sounds good|agreed|"
                     r"please do|let'?s do (it|that)|that works|perfect|correct|right|exactly|both|neither|"
                     r"the (first|second|third|last) one)\b", re.I)
_PRONOUN_START = re.compile(r"^\s*(it|its|it's|they|them|their|this|that|these|those|he|she|his|her|him|there|"
                            r"then|same|which|the one|so)\b", re.I)
_NAME = re.compile(r"\b([A-Z][a-z]+(?:[ -][A-Z][a-zA-Z0-9]+)*|[A-Z]{2,}[a-z]*|[A-Z][a-z]*[A-Z0-9][A-Za-z0-9-]*)\b")
_NAME_STOP = frozenset("""I The A An And But Or So If When Then This That These Those It Its He She They We You
Yes No Ok Okay Sure Thanks Hi Hello My Our Your Their His Her Also Just Please Let What Which Who Where Why How
Is Are Was Were Do Does Did Can Could Would Should Will Here There Today Tomorrow Yesterday Monday Tuesday
Wednesday Thursday Friday Saturday Sunday January February March April May June July August September October
November December Sophia USER ASSISTANT Note Also""".split())


def needs_context(text: str) -> bool:
    t = text.strip()
    return len(t) < 60 or bool(_ASSENT.match(t)) or bool(_PRONOUN_START.match(t))


def last_question(text: str) -> Optional[str]:
    if not text:
        return None
    sents = split_sentences(text)
    for s in reversed(sents):
        if s.rstrip().endswith("?"):
            return s.strip()[:200]
    return sents[-1].strip()[:200] if sents else None


def names_in(text: str) -> List[str]:
    out = []
    for m in _NAME.finditer(text or ""):
        n = m.group(1)
        if n not in _NAME_STOP and n not in out:
            out.append(n)
    return out


def header(speaker: str, said: float, ctx: Optional[str] = None, names: Sequence[str] = ()) -> str:
    date = _dt.datetime.fromtimestamp(said).strftime("%Y-%m-%d")
    parts = [speaker, date]
    if ctx:
        parts.append(f"re: {ctx}")
    if names:
        parts.append("about " + ", ".join(names[:4]))
    return "[" + " · ".join(parts) + "]"


# ----------------------------------------------------------------- echo detection
def shingles(text: str, n: int = 5) -> Set[str]:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def containment(text: str, reference: Set[str], n: int = 5) -> float:
    s = shingles(text, n)
    if not s or not reference:
        return 0.0
    return len(s & reference) / len(s)


def message_text(content) -> str:
    """OpenAI-style content (str or list of parts) -> plain text; image parts become '[image]'."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for p in content if isinstance(content, list) else [content]:
        if isinstance(p, dict):
            if p.get("type") in ("text", "input_text", "output_text"):
                parts.append(p.get("text", ""))
            elif p.get("type") in ("image_url", "image", "input_image"):
                parts.append("[image]")
        elif isinstance(p, str):
            parts.append(p)
    return "\n".join(x for x in parts if x)


def norm_entity(s: str) -> str:
    """Entity id: lower-case, without a leading article or possessive."""
    s = (s or "").strip().lower()
    s = re.sub(r"^(the|a|an|my|our|his|her|their)\s+", "", s)
    s = re.sub(r"['’]s$", "", s)
    return re.sub(r"\s+", " ", s).strip(" .,:;\"'")
