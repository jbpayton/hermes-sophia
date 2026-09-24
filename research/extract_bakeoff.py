"""Triple-extraction bake-off against LM Studio.

Modes:
  nuextract-raw   : NuExtract3 native prompt, rendered by us, sent to /v1/completions (bypasses LM Studio templating)
  nuextract-chat  : NuExtract3 native via /v1/chat/completions + chat_template_kwargs (tests whether LM Studio forwards kwargs)
  sophia-responses: SophiaAMS TRIPLE/CONVERSATION prompt via /v1/responses with reasoning effort none (any chat model)

Usage: python extract_bakeoff.py <model_id> <mode> [--samples 1,2,3] [--out results.json]
"""
import json, re, sys, time, argparse, urllib.request
import os  # noqa: E401
sys.path.insert(0, os.environ.get("SOPHIAAMS_DIR", "SophiaAMS"))  # a clone of github.com/jbpayton/SophiaAMS
from prompts import TRIPLE_EXTRACTION_PROMPT, CONVERSATION_TRIPLE_EXTRACTION_PROMPT  # noqa: E402
from schemas import TRIPLE_EXTRACTION_SCHEMA  # noqa: E402
import jsonschema  # noqa: E402

import os
BASE = os.environ.get("LMS_BASE", "http://127.0.0.1:1234")

SAMPLES = {
    1: ("encyclopedia", False, """Voyager 1 is a space probe launched by NASA on September 5, 1977, as part of the Voyager program to study the outer Solar System. It was built at the Jet Propulsion Laboratory in Pasadena, California. The probe made a flyby of Jupiter in March 1979 and of Saturn in November 1980, returning the first detailed images of their moons. In August 2012 Voyager 1 became the first human-made object to enter interstellar space. Its power comes from three radioisotope thermoelectric generators, which are expected to keep at least one instrument running until about 2025. The spacecraft carries the Golden Record, a phonograph record curated by a committee chaired by Carl Sagan."""),
    2: ("conversation", True, """SPEAKER:Joey|I finally booked the Yosemite trip for the second week of May. Sam is coming too, and we're going to try Half Dome if the cables are up. I'm bringing the Fujifilm X-T5 this time instead of the Sony, the Sony was too heavy on the last hike.
SPEAKER:Sophia|That sounds great. Did you decide where you're staying? Last time you mentioned Curry Village was noisy.
SPEAKER:Joey|Yeah, we're doing Curry Village again anyway because it's cheap, but I want to drive up from San Jose on the Thursday night so we get a full first day."""),
    3: ("procedural", False, """To rotate the nginx logs on the web host, first stop the service with `systemctl stop nginx`. Then archive the current logs: `tar -czf /backup/nginx-logs-$(date +%F).tar.gz /var/log/nginx`. After the archive is written, clear the log directory with `rm /var/log/nginx/*.log` and start the service again using `systemctl start nginx`. You can verify it came back with `systemctl status nginx`. Do not delete the archive directory; the retention script prunes it weekly."""),
    4: ("web-chunk-with-noise", False, """Hatsune Miku is a Vocaloid software voicebank developed by Crypton Future Media and released on August 31, 2007. Her voice is sampled from Japanese voice actress Saki Fujita. The software is built on the Yamaha Vocaloid 2 engine. Miku has performed as an animated projection at live concerts since 2009.

See also
- Kagamine Rin/Len
- Megurine Luka
- Vocaloid

References
1. Kenmochi, Hideki (2010). "VOCALOID and Hatsune Miku phenomenon in Japan". Interdisciplinary Workshop on Singing Voice.
2. "Hatsune Miku: Japan's virtual pop star". BBC News. 27 August 2012.
3. Crypton Future Media, Inc. Official product page. https://ec.crypton.co.jp/pages/prod/vocaloid/cv01"""),
    5: ("personal-note", False, """Reminder for next month: Dr. Alvarez moved her clinic to 240 Willow Street in Mountain View, and the follow-up appointment is on October 14 at 9:30. Bring the MRI results from the Stanford imaging center. Insurance changed to Blue Shield in September, so the old card is no longer valid. Also, Mom's birthday is October 20; she said she wants the blue ceramic teapot from the shop on Castro Street."""),
}

NUEXTRACT_TEMPLATE = {
    "triples": [
        {
            "subject": "string",
            "verb": "string",
            "object": "string",
            "source_text": "verbatim-string",
            "topics": ["string"],
        }
    ]
}
NUEXTRACT_INSTRUCTIONS_DOC = (
    "Extract every factual relationship in the document as a knowledge-graph triple. "
    "subject: the main entity. verb: a complete relationship predicate such as 'was developed by' or 'was released in'. "
    "object: a specific entity or value, never empty (use 'unspecified' if unclear). "
    "source_text: the exact sentence fragment the triple comes from. "
    "topics: 2 to 3 short theme labels for the triple, considering the whole document. "
    "Preserve commands, code, and numbered steps verbatim in subject or object. "
    "Ignore navigation lists, 'See also' sections, and bibliographic references."
)
NUEXTRACT_INSTRUCTIONS_CONV = (
    "Extract personal facts from the conversation as knowledge-graph triples. "
    "Lines are formatted SPEAKER:name|dialogue. 'I/my/me' refers to that speaker; 'you/your' refers to the other person. "
    "subject: the person's actual name from the SPEAKER tag, never 'user' or 'assistant'. "
    "verb: a complete relationship such as 'is bringing', 'plans to hike', 'lives in'. "
    "object: a specific entity, place, date, or item. source_text: the exact words the fact comes from. "
    "topics: 2 to 3 short category labels. Ignore filler and emotional responses."
)

ICL_EXAMPLES = {
    "doc": [(
        "Hatsune Miku was developed by Crypton Future Media. She was released in August 2007. Her voice is provided by Saki Fujita. "
        "To install the voicebank, run `vocaloid-install cv01` and then restart the editor.",
        {"triples": [
            {"subject": "Hatsune Miku", "verb": "was developed by", "object": "Crypton Future Media", "source_text": "Hatsune Miku was developed by Crypton Future Media", "topics": ["Virtual Singer Development", "Japanese Digital Entertainment"]},
            {"subject": "Hatsune Miku", "verb": "was released in", "object": "August 2007", "source_text": "She was released in August 2007", "topics": ["VOCALOID Release History", "Virtual Singer Development"]},
            {"subject": "Hatsune Miku", "verb": "voice is provided by", "object": "Saki Fujita", "source_text": "Her voice is provided by Saki Fujita", "topics": ["Voice Actress Information", "Virtual Singer Development"]},
            {"subject": "installing the voicebank", "verb": "is done by running", "object": "`vocaloid-install cv01`", "source_text": "To install the voicebank, run `vocaloid-install cv01`", "topics": ["Software Installation", "VOCALOID Setup"]},
            {"subject": "installing the voicebank", "verb": "requires afterwards", "object": "restarting the editor", "source_text": "and then restart the editor", "topics": ["Software Installation", "VOCALOID Setup"]},
        ]},
    )],
    "conv": [(
        "SPEAKER:Sophia|I love sushi and work at Google. I'm interested in machine learning for creative applications.\nSPEAKER:Joey|You should try the place on Castro Street.",
        {"triples": [
            {"subject": "Sophia", "verb": "loves", "object": "sushi", "source_text": "I love sushi", "topics": ["Food Preference", "Personal Interests"]},
            {"subject": "Sophia", "verb": "works at", "object": "Google", "source_text": "work at Google", "topics": ["Employment", "Career Information"]},
            {"subject": "Sophia", "verb": "is interested in", "object": "machine learning for creative applications", "source_text": "I'm interested in machine learning for creative applications", "topics": ["Interest", "Technology"]},
            {"subject": "Joey", "verb": "recommends to Sophia", "object": "the sushi place on Castro Street", "source_text": "You should try the place on Castro Street", "topics": ["Restaurant Recommendation", "Food Preference"]},
        ]},
    )],
}

def render_nuextract_prompt(document: str, template: dict, instructions: str, icl: list | None = None, think: bool = False) -> str:
    p = ("<|im_start|>user\n"
         "【task】structured\n"
         "【template_start】" + json.dumps(template) + "【template_end】\n"
         "【instructions_start】" + instructions + "【instructions_end】\n")
    if icl:
        p += "【examples_start】\n"
        for ex_in, ex_out in icl:
            p += "【example_input_start】" + ex_in.strip() + "【example_input_end】\n"
            p += "【example_output_start】" + json.dumps(ex_out) + "【example_output_end】\n"
        p += "【examples_end】\n"
    p += ("【document_start】\n" + document.strip() + "\n"
          "【document_end】<|im_end|>\n"
          "<|im_start|>assistant\n")
    p += "<think>\n" if think else "<think>\n\n</think>\n\n"
    return p

def post(path, body, timeout=600):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
    return (time.perf_counter() - t0) * 1000, out

def extract_json(content: str) -> dict:
    """Port of SophiaAMS triple_extraction._extract_json (think-strip, fences, last top-level object)."""
    cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    depth, end, start = 0, -1, -1
    for i in range(len(cleaned) - 1, -1, -1):
        ch = cleaned[i]
        if ch == "}":
            if depth == 0:
                end = i
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0 and end != -1:
                start = i
                break
    if start != -1 and end != -1:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {"__parse_failed__": True, "triples": []}

def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

OPTS = {"icl": False, "think": False, "temperature": 0.2, "v2": False}

NUEXTRACT_INSTRUCTIONS_DOC_V2 = NUEXTRACT_INSTRUCTIONS_DOC + (
    " Emit exactly ONE fact per triple: if a sentence states several facts (an action and a date, a place and a builder), "
    "emit a separate triple for each. The verb must never contain the object entity: write verb 'made a flyby of' with object 'Jupiter', "
    "and a second triple verb 'flew by Jupiter in' with object 'March 1979'. When the document contains a command or code, "
    "put the full command verbatim in the object. object must never be null; use 'unspecified' if truly absent."
)
NUEXTRACT_INSTRUCTIONS_CONV_V2 = NUEXTRACT_INSTRUCTIONS_CONV + (
    " Emit exactly ONE fact per triple and split compound statements into several triples. "
    "The verb must never contain the object entity. object must never be null; use 'unspecified' if truly absent."
)

def call(model, mode, text, is_conv, max_tokens=2048):
    if mode == "nuextract-raw":
        icl = (ICL_EXAMPLES["conv"] if is_conv else ICL_EXAMPLES["doc"]) if OPTS["icl"] else None
        if OPTS["v2"]:
            ins = NUEXTRACT_INSTRUCTIONS_CONV_V2 if is_conv else NUEXTRACT_INSTRUCTIONS_DOC_V2
        else:
            ins = NUEXTRACT_INSTRUCTIONS_CONV if is_conv else NUEXTRACT_INSTRUCTIONS_DOC
        tmpl = NUEXTRACT_TEMPLATE
        if OPTS.get("obj_verbatim"):
            tmpl = {"triples": [dict(NUEXTRACT_TEMPLATE["triples"][0], object="verbatim-string", subject="verbatim-string")]}
        prompt = render_nuextract_prompt(text, tmpl, ins, icl=icl, think=OPTS["think"])
        dt, r = post("/v1/completions", {"model": model, "prompt": prompt, "max_tokens": max_tokens, "temperature": OPTS["temperature"], "stop": ["<|im_end|>"]})
        return dt, r["choices"][0].get("text", ""), r.get("usage")
    if mode == "nuextract-chat":
        dt, r = post("/v1/chat/completions", {
            "model": model, "temperature": 0.2, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": text}],
            "chat_template_kwargs": {"template": json.dumps(NUEXTRACT_TEMPLATE),
                                     "instructions": NUEXTRACT_INSTRUCTIONS_CONV if is_conv else NUEXTRACT_INSTRUCTIONS_DOC,
                                     "enable_thinking": False}})
        return dt, r["choices"][0]["message"].get("content", ""), r.get("usage")
    if mode == "sophia-responses":
        prompt = (CONVERSATION_TRIPLE_EXTRACTION_PROMPT if is_conv else TRIPLE_EXTRACTION_PROMPT).format(text=text)
        dt, r = post("/v1/responses", {"model": model, "input": prompt, "max_output_tokens": max_tokens, "temperature": 0,
                                       "reasoning": {"effort": "none"}})
        msg = [o for o in r.get("output", []) if o.get("type") == "message"]
        content = "".join(c.get("text", "") for o in msg for c in o.get("content", []))
        return dt, content, r.get("usage")
    raise SystemExit(f"unknown mode {mode}")

def evaluate(text, content):
    data = extract_json(content)
    parse_ok = not data.get("__parse_failed__")
    triples = data.get("triples") or []
    try:
        jsonschema.validate(data if parse_ok else {"triples": []}, TRIPLE_EXTRACTION_SCHEMA)
        schema_ok = parse_ok
    except jsonschema.ValidationError as e:
        schema_ok = False
    n = len(triples)
    exact = sum(1 for t in triples if isinstance(t, dict) and t.get("source_text") and t["source_text"] in text)
    normed = sum(1 for t in triples if isinstance(t, dict) and t.get("source_text") and norm_ws(t["source_text"]) in norm_ws(text))
    empty_obj = sum(1 for t in triples if isinstance(t, dict) and not (t.get("object") or "").strip())
    no_topics = sum(1 for t in triples if isinstance(t, dict) and not t.get("topics"))
    return dict(parse_ok=parse_ok, schema_ok=schema_ok, n=n, verbatim_exact=exact, verbatim_normalized=normed,
                empty_object=empty_obj, no_topics=no_topics, triples=triples)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model"); ap.add_argument("mode")
    ap.add_argument("--samples", default="1,2,3,4,5"); ap.add_argument("--out", default=None)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--icl", action="store_true"); ap.add_argument("--think", action="store_true")
    ap.add_argument("--temperature", type=float, default=0.2); ap.add_argument("--v2", action="store_true")
    ap.add_argument("--obj-verbatim", action="store_true")
    a = ap.parse_args()
    OPTS.update(icl=a.icl, think=a.think, temperature=a.temperature, v2=a.v2, obj_verbatim=a.obj_verbatim)
    results = []
    for sid in [int(x) for x in a.samples.split(",")]:
        name, is_conv, text = SAMPLES[sid]
        try:
            dt, content, usage = call(a.model, a.mode, text, is_conv, a.max_tokens)
        except Exception as e:
            print(f"\n### sample {sid} {name}: REQUEST FAILED: {str(e)[:300]}")
            results.append(dict(sample=sid, name=name, error=str(e)[:300])); continue
        ev = evaluate(text, content)
        out_toks = (usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens")
        print(f"\n### sample {sid} [{name}] {dt:.0f} ms, out_tokens={out_toks}, parse={ev['parse_ok']}, schema={ev['schema_ok']}, "
              f"triples={ev['n']}, verbatim exact/normalized={ev['verbatim_exact']}/{ev['verbatim_normalized']}, "
              f"empty_obj={ev['empty_object']}, no_topics={ev['no_topics']}")
        if not ev["parse_ok"]:
            print("   RAW (first 400 chars):", repr(content[:400]))
        for t in ev["triples"][:40]:
            if isinstance(t, dict):
                mark = "" if (t.get("source_text") and norm_ws(t["source_text"]) in norm_ws(text)) else "  [quote NOT in text]"
                print(f"   ({t.get('subject')!r}, {t.get('verb')!r}, {t.get('object')!r}) topics={t.get('topics')}{mark}")
        results.append(dict(sample=sid, name=name, latency_ms=dt, out_tokens=out_toks, **{k: v for k, v in ev.items() if k != 'triples'}, triples=ev["triples"], raw=content))
    if a.out:
        json.dump(dict(model=a.model, mode=a.mode, results=results), open(a.out, "w"), indent=1)
        print(f"\nsaved {a.out}")

if __name__ == "__main__":
    main()
