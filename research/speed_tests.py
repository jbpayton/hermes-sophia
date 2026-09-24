"""Speed levers for extraction on LM Studio: (1) concurrency, (2) compact output format with sentence ids."""
import json, re, sys, time, urllib.request, concurrent.futures as cf
import os  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.environ.get("SOPHIAAMS_DIR", "SophiaAMS"))  # a clone of github.com/jbpayton/SophiaAMS
from extract_bakeoff import SAMPLES, post, norm_ws  # noqa: E402
from prompts import TRIPLE_EXTRACTION_PROMPT, CONVERSATION_TRIPLE_EXTRACTION_PROMPT  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen35-9b"
TEST = sys.argv[2] if len(sys.argv) > 2 else "all"

import os
API = os.environ.get("API", "responses")  # "responses" (LM Studio, reasoning off) or "chat" (llama-server, chat_template_kwargs)

def responses(prompt, max_tokens=2048):
    if API == "chat":
        dt, r = post("/v1/chat/completions", {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                                              "max_tokens": max_tokens, "temperature": 0,
                                              "chat_template_kwargs": {"enable_thinking": False}})
        c = r["choices"][0]["message"]
        u = r.get("usage", {}); u["output_tokens"] = u.get("completion_tokens")
        return dt, c.get("content") or "", u
    dt, r = post("/v1/responses", {"model": MODEL, "input": prompt, "max_output_tokens": max_tokens, "temperature": 0,
                                   "reasoning": {"effort": "none"}})
    msg = [o for o in r.get("output", []) if o.get("type") == "message"]
    content = "".join(c.get("text", "") for o in msg for c in o.get("content", []))
    return dt, content, r.get("usage", {})

def sophia_prompt(sid):
    name, is_conv, text = SAMPLES[sid]
    return (CONVERSATION_TRIPLE_EXTRACTION_PROMPT if is_conv else TRIPLE_EXTRACTION_PROMPT).format(text=text)

# ---------- (1) concurrency: same 4 chunks, serial vs 4-way parallel ----------
def test_concurrency():
    sids = [1, 2, 4, 5]
    print("== serial ==")
    t0 = time.perf_counter(); toks = 0
    for sid in sids:
        dt, _, u = responses(sophia_prompt(sid)); toks += u.get("output_tokens", 0)
        print(f"   sample {sid}: {dt:.0f} ms, {u.get('output_tokens')} out tokens")
    ser = time.perf_counter() - t0
    print(f"   serial total {ser:.1f} s, aggregate {toks/ser:.0f} tok/s")
    print("== 4-way parallel ==")
    t0 = time.perf_counter(); toks = 0
    with cf.ThreadPoolExecutor(4) as ex:
        for sid, (dt, _, u) in zip(sids, ex.map(lambda s: responses(sophia_prompt(s)), sids)):
            toks += u.get("output_tokens", 0); print(f"   sample {sid}: {dt:.0f} ms, {u.get('output_tokens')} out tokens")
    par = time.perf_counter() - t0
    print(f"   parallel total {par:.1f} s, aggregate {toks/par:.0f} tok/s, speedup {ser/par:.2f}x")

# ---------- (2) compact format: numbered sentences in, pipe-delimited lines out ----------
COMPACT_PROMPT = """Extract knowledge-graph triples from the numbered text below.

Output format (plain text, no JSON, no commentary):
Line 1:  TOPICS: topic 1; topic 2; topic 3; topic 4        (2-5 short themes covering the whole text)
Then one line per fact:  subject | verb | object | sN | t1,t3
- verb: a complete relationship predicate ("was developed by", "was released in"); it must not contain the object.
- object: a specific entity or value, never empty.
- sN: the id of the sentence the fact comes from (e.g. s3).
- t1,t3: indexes into the TOPICS line (1-based) that apply to this fact.
- One fact per line. Preserve commands, code and numbered steps verbatim in subject or object.
- Ignore navigation lists, "See also" sections and bibliographic references.
{speaker_rule}
Example input:
[s1] Hatsune Miku was developed by Crypton Future Media and released in August 2007.
[s2] To install the voicebank, run `vocaloid-install cv01`.
Example output:
TOPICS: virtual singers; software installation
Hatsune Miku | was developed by | Crypton Future Media | s1 | 1
Hatsune Miku | was released in | August 2007 | s1 | 1
installing the voicebank | is done by running | `vocaloid-install cv01` | s2 | 2
{conv_example}
Text:
{text}"""
CONV_EXAMPLE = """Conversation example input:
[s1] SPEAKER:Sophia|I love sushi and I work at Google.
[s2] SPEAKER:Joey|You should try the place on Castro Street.
Conversation example output:
TOPICS: food preferences; employment; recommendations
Sophia | loves | sushi | s1 | 1
Sophia | works at | Google | s1 | 2
Joey | recommends to Sophia | the place on Castro Street | s2 | 3
"""
SPEAKER_RULE = ('- Lines are "SPEAKER:name|dialogue". "I/my/me" = that speaker; "you/your" = the other person. '
                'Subjects must be the actual names, never "user" or "assistant".')

def number_sentences(text, is_conv):
    """Split into sentences (or dialogue lines) with ids; returns numbered text and id->sentence map."""
    sents = []
    if is_conv:
        for line in text.splitlines():
            if line.strip(): sents.append(line.strip())
    else:
        for para in text.split("\n"):
            para = para.strip()
            if not para: continue
            protected = re.sub(r"\b(Dr|Mr|Mrs|Ms|Prof|St|Mt|Inc|Ltd|Jr|Sr|vs|etc|e\.g|i\.e)\.", lambda m: m.group(0).replace(".", "․"), para)
            parts = [p.replace("․", ".") for p in re.split(r"(?<=[.!?])\s+(?=[A-Z`\"'(\[0-9])", protected)]
            sents.extend(p.strip() for p in parts if p.strip())
    ids = {f"s{i+1}": s for i, s in enumerate(sents)}
    numbered = "\n".join(f"[{k}] {v}" for k, v in ids.items())
    return numbered, ids

def parse_compact(content, ids):
    topics = []; triples = []; bad = 0
    for line in content.splitlines():
        line = line.strip()
        if not line: continue
        if line.upper().startswith("TOPICS:"):
            topics = [t.strip() for t in line.split(":", 1)[1].split(";") if t.strip()]; continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4: bad += 1; continue
        subj, verb, obj, sid = parts[0], parts[1], parts[2], parts[3].lower().strip()
        tix = []
        if len(parts) >= 5:
            for t in re.split(r"[,\s;]+", parts[4]):
                t = t.lower().lstrip("t")
                if t.isdigit() and 1 <= int(t) <= len(topics): tix.append(topics[int(t)-1])
        src = ids.get(sid)
        triples.append({"subject": subj, "verb": verb, "object": obj, "source_text": src, "source_ok": src is not None, "topics": tix})
    return topics, triples, bad

def test_compact():
    for sid in [1, 2, 3, 4, 5]:
        name, is_conv, text = SAMPLES[sid]
        numbered, ids = number_sentences(text, is_conv)
        prompt = COMPACT_PROMPT.format(text=numbered, speaker_rule=SPEAKER_RULE if is_conv else "",
                                       conv_example=CONV_EXAMPLE if is_conv else "")
        dt, content, u = responses(prompt)
        topics, triples, bad = parse_compact(content, ids)
        ok = sum(1 for t in triples if t["source_ok"]); empty = sum(1 for t in triples if not t["object"])
        print(f"\n### sample {sid} [{name}] {dt:.0f} ms, out_tokens={u.get('output_tokens')}, triples={len(triples)}, "
              f"sentence-id resolved={ok}/{len(triples)}, empty_obj={empty}, unparsed_lines={bad}, topics={topics}")
        for t in triples[:14]:
            print(f"   ({t['subject']!r}, {t['verb']!r}, {t['object']!r}) <- {t['source_text'][:50] if t['source_text'] else 'BAD ID'!r} topics={t['topics']}")

if __name__ == "__main__":
    if TEST in ("all", "concurrency"): test_concurrency()
    if TEST in ("all", "compact"): test_compact()
