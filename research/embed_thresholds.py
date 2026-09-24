"""Calibrate retrieval thresholds for nomic-embed-text-v1.5 (via LM Studio) on a Sophia-style triple corpus.

1. Build a corpus: the 9B extracts triples (compact format) from the 5 bake-off samples + near-miss distractor texts.
2. Embed triples and questions; score cosine for every (question, triple) pair.
3. Report recall@k, relevant vs irrelevant score distributions, present vs absent top-1, and whether
   SophiaAMS's MiniLM-era thresholds still make sense.
"""
import json, os, sys, time, math, statistics, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import speed_tests as st  # compact extraction prompt + parser (uses the loaded 9B)

BASE = "http://127.0.0.1:1234/v1"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed")
CORPUS_PATH = os.path.join(HERE, "results", "embed_corpus.json")

DISTRACTORS = {
    101: ("conv-sam-iceland", True, "SPEAKER:Sam|I just got back from Iceland. I shot the whole trip on my Canon R6 and the drone footage from Skogafoss came out great.\nSPEAKER:Sophia|Did the weather cooperate?\nSPEAKER:Sam|Mostly. We stayed in Vik for three nights and drove the Ring Road clockwise."),
    102: ("maria-job", False, "Maria started a new job at Stripe in March 2026 as a staff engineer on the payments reliability team. She moved from Seattle to Oakland and now commutes by BART. Her manager is David Chen, who previously led infrastructure at Dropbox."),
    103: ("postgres-backup", False, "To back up the Postgres database, run `pg_dump -Fc appdb > /backup/appdb.dump` as the postgres user. Restore with `pg_restore -d appdb /backup/appdb.dump`. Nightly backups are kept for 14 days by the cleanup cron job."),
    104: ("webb", False, "The James Webb Space Telescope launched on December 25, 2021 aboard an Ariane 5 rocket from Kourou, French Guiana. It orbits the Sun near the second Lagrange point and observes primarily in the infrared. Its primary mirror is 6.5 meters across and made of 18 gold-coated beryllium segments."),
    105: ("emma", False, "Joey's sister Emma lives in Denver and works as a veterinarian. She is allergic to cats, which she says is ironic. Emma is visiting in November for Thanksgiving and prefers vegetarian food."),
    106: ("rin-len-luka", False, "Kagamine Rin and Len are Vocaloid voicebanks released by Crypton Future Media in December 2007. Their voice provider is Asami Shimoda. Megurine Luka followed in January 2009 as a bilingual Japanese and English voicebank."),
    107: ("bazel", False, "The team decided to migrate the build system from Make to Bazel in Q3. The migration is owned by Priya, and the target is to cut CI time below twelve minutes. Remote caching will be hosted on the existing GCS bucket."),
    108: ("dentist", False, "Dr. Patel's dental office is at 55 Oak Avenue in Palo Alto. Joey has a cleaning scheduled for November 3 at 2:00 PM. The office requires 24 hours notice for cancellations."),
}

# (question, gold predicate as list of alternatives; each alternative is a list of substrings that must ALL appear)
PRESENT = [
    ("What camera did Joey bring to Yosemite?", [["fujifilm"], ["x-t5"]]),
    ("Who is going to Yosemite with Joey?", [["sam", "yosemite"], ["sam", "coming"], ["sam", "trip"]]),
    ("Where is Joey staying in Yosemite?", [["curry village"]]),
    ("When is the Yosemite trip?", [["second week of may"], ["yosemite", "may"]]),
    ("Who built Voyager 1?", [["jet propulsion"]]),
    ("When did Voyager 1 enter interstellar space?", [["interstellar"]]),
    ("What powers Voyager 1?", [["radioisotope"]]),
    ("Who curated the Golden Record?", [["sagan"]]),
    ("How do I stop nginx?", [["systemctl stop nginx"]]),
    ("How are the nginx logs archived?", [["tar -czf"]]),
    ("Who voices Hatsune Miku?", [["saki fujita"]]),
    ("When was Hatsune Miku released?", [["miku", "2007"], ["miku", "august"]]),
    ("Where is Dr. Alvarez's clinic now?", [["willow street"]]),
    ("When is my follow-up appointment?", [["october 14"]]),
    ("What insurance do I have now?", [["blue shield"]]),
    ("What does Mom want for her birthday?", [["teapot"]]),
    ("What camera did Sam use in Iceland?", [["canon"]]),
    ("Where does Maria work?", [["stripe"]]),
    ("How do I back up the Postgres database?", [["pg_dump"]]),
    ("Where does the Webb telescope orbit?", [["lagrange"]]),
    ("Where does Emma live?", [["denver"]]),
    ("Who owns the Bazel migration?", [["priya"]]),
    ("When is Joey's dental cleaning?", [["november 3"]]),
    ("What engine is Hatsune Miku built on?", [["vocaloid 2"]]),
    ("Who voices Kagamine Rin and Len?", [["shimoda"]]),
]
ABSENT = [
    "What is Joey's favorite food?",
    "When did Sam get married?",
    "What is the capital of Australia?",
    "How do I configure Postgres replication?",
    "What lens did Joey use on Half Dome?",
    "Who is Maria's sister?",
    "What car does Emma drive?",
    "When did Voyager 2 launch?",
    "How much does the Fujifilm X-T5 cost?",
    "How do I rotate Apache logs?",
]

def build_corpus():
    if os.path.exists(CORPUS_PATH):
        return json.load(open(CORPUS_PATH))
    texts = {**{k: v for k, v in st.SAMPLES.items()}, **DISTRACTORS}
    corpus = []
    for sid, (name, is_conv, text) in texts.items():
        numbered, ids = st.number_sentences(text, is_conv)
        prompt = st.COMPACT_PROMPT.format(text=numbered, speaker_rule=st.SPEAKER_RULE if is_conv else "",
                                          conv_example=st.CONV_EXAMPLE if is_conv else "")
        dt, content, u = st.responses(prompt)
        topics, triples, bad = st.parse_compact(content, ids)
        for t in triples:
            if t["source_ok"] and t["object"]:
                corpus.append({"doc": name, "subject": t["subject"], "verb": t["verb"], "object": t["object"],
                               "sentence": t["source_text"], "topics": t["topics"]})
        print(f"  extracted {len(triples):2d} triples from {name} in {dt/1000:.1f}s")
    json.dump(corpus, open(CORPUS_PATH, "w"), indent=1)
    return corpus

def embed(texts, batch=64):
    out = []
    for i in range(0, len(texts), batch):
        body = {"model": EMBED_MODEL, "input": texts[i:i + batch]}
        r = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/embeddings", data=json.dumps(body).encode(),
                        headers={"Content-Type": "application/json"}), timeout=120).read())
        out.extend(d["embedding"] for d in sorted(r["data"], key=lambda d: d["index"]))
    M = np.array(out, dtype=np.float32)
    return M / np.linalg.norm(M, axis=1, keepdims=True)

def is_gold(triple, alts):
    text = f"{triple['subject']} {triple['verb']} {triple['object']}".lower()
    return any(all(s in text for s in alt) for alt in alts)

def pct(a, p):
    return float(np.percentile(np.array(a), p)) if len(a) else float("nan")

def run(corpus, label, doc_fmt, q_prefix):
    docs = [doc_fmt(t) for t in corpus]
    D = embed(docs)
    Qp = embed([q_prefix + q for q, _ in PRESENT])
    Qa = embed([q_prefix + q for q in ABSENT])
    Sp, Sa = Qp @ D.T, Qa @ D.T
    rel, irr, ranks, top1_present, margins_present, rel_best = [], [], [], [], [], []
    usable = 0
    for qi, (q, alts) in enumerate(PRESENT):
        gold = [i for i, t in enumerate(corpus) if is_gold(t, alts)]
        if not gold:
            continue
        usable += 1
        s = Sp[qi]; order = np.argsort(-s)
        rank = min(int(np.where(order == g)[0][0]) for g in gold) + 1
        ranks.append(rank)
        rel.extend(float(s[g]) for g in gold)
        irr.extend(float(s[i]) for i in range(len(corpus)) if i not in gold)
        top1_present.append(float(s[order[0]])); rel_best.append(max(float(s[g]) for g in gold))
        margins_present.append(float(s[order[0]] - s[order[1]]))
    top1_absent = [float(Sa[qi].max()) for qi in range(len(ABSENT))]
    margins_absent = [float(np.sort(Sa[qi])[-1] - np.sort(Sa[qi])[-2]) for qi in range(len(ABSENT))]
    all_pairs = np.concatenate([Sp.ravel(), Sa.ravel()])
    r1 = sum(r <= 1 for r in ranks) / len(ranks); r5 = sum(r <= 5 for r in ranks) / len(ranks); r10 = sum(r <= 10 for r in ranks) / len(ranks)
    print(f"\n=== {label} ===  ({len(corpus)} triples, {usable} answerable questions, {len(ABSENT)} unanswerable)")
    print(f"  recall@1 {r1:.2f}  recall@5 {r5:.2f}  recall@10 {r10:.2f}   worst gold rank {max(ranks)}")
    print(f"  relevant pairs    p5 {pct(rel,5):.3f}  p25 {pct(rel,25):.3f}  median {pct(rel,50):.3f}  max {max(rel):.3f}")
    print(f"  irrelevant pairs  median {pct(irr,50):.3f}  p90 {pct(irr,90):.3f}  p99 {pct(irr,99):.3f}  max {max(irr):.3f}")
    print(f"  top-1, answerable   min {min(top1_present):.3f}  median {pct(top1_present,50):.3f}   | best-gold min {min(rel_best):.3f}")
    print(f"  top-1, unanswerable min {min(top1_absent):.3f}  median {pct(top1_absent,50):.3f}  max {max(top1_absent):.3f}")
    print(f"  top1-top2 margin, answerable median {pct(margins_present,50):.3f} | unanswerable median {pct(margins_absent,50):.3f}")
    for th in (0.15, 0.2, 0.3, 0.5, 0.65, 0.7, 0.8):
        print(f"    old cutoff {th:.2f}: keeps {np.mean(all_pairs >= th)*100:5.1f}% of all pairs, "
              f"{np.mean(np.array(rel) >= th)*100:5.1f}% of relevant pairs")
    for qi, q in enumerate(ABSENT):
        j = int(np.argmax(Sa[qi])); t = corpus[j]
        print(f"    unanswerable top hit {Sa[qi, j]:.3f}: {q!r} -> ({t['subject']} | {t['verb']} | {t['object']})")
    return dict(label=label, r1=r1, r5=r5, r10=r10, rel=rel, irr=irr, top1_present=top1_present, top1_absent=top1_absent)

if __name__ == "__main__":
    corpus = build_corpus()
    # latency of a single query embedding (tier-0 cost)
    lat = []
    for i in range(10):
        t0 = time.perf_counter(); embed([f"search_query: what camera did joey use {i}"]); lat.append((time.perf_counter() - t0) * 1000)
    print(f"\nquery embedding latency: median {statistics.median(lat):.1f} ms, max {max(lat):.1f} ms")
    triple_text = lambda t: f"{t['subject']} {t['verb']} {t['object']}"
    results = [
        run(corpus, "nomic, with prefixes, triple text", lambda t: "search_document: " + triple_text(t), "search_query: "),
        run(corpus, "nomic, NO prefixes, triple text", triple_text, ""),
        run(corpus, "nomic, with prefixes, triple + source sentence", lambda t: f"search_document: {triple_text(t)}. {t['sentence']}", "search_query: "),
    ]
    json.dump(results, open(os.path.join(HERE, "results", "embed_thresholds.json"), "w"))
