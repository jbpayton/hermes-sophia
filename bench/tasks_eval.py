"""Task memory: scripted agent sessions with known outcomes, through the real night and recall.

Five sessions in Hermes's message shape (requests, tool calls, results, replies, reactions):
  nginx     a dead end (permission denied), then logrotate works; the user confirms  -> succeeded, 1 dead end
  docker    two failed builds, then the user gives up                                -> failed or abandoned
  certbot   reads the certbot docs, then the command they describe works              -> succeeded, source linked
  venv      venv fails on python3.9; the user says "try python3.12"; that works       -> one task, succeeded
  mixed     "check disk space", then an unrelated "how many CPUs?"                     -> two tasks

Then, in fresh sessions, requests to do the same things again: the right card should be injected.

  python bench/tasks_eval.py                      # 9B night, decider and embeddings from LM Studio
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from common import RESULTS, add_model_args, fresh_engine, memory_config
from hermes_sophia.sleep import SleepRunner


def call(cid, name, **args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def term(cid, output, code):
    return {"role": "tool", "tool_call_id": cid, "name": "terminal",
            "content": json.dumps({"output": output, "exit_code": code, "error": None})}


SESSIONS = {
    "nginx": [
        {"role": "user", "content": "Rotate the nginx logs on web-1, the disk is filling up."},
        {"role": "assistant", "content": "", "tool_calls": [call("n1", "terminal", command="ssh web-1 'rm /var/log/nginx/access.log'")]},
        term("n1", "rm: cannot remove '/var/log/nginx/access.log': Permission denied", 1),
        {"role": "assistant", "content": "", "tool_calls": [call("n2", "terminal", command="ssh web-1 'sudo logrotate -f /etc/logrotate.d/nginx'")]},
        term("n2", "", 0),
        {"role": "assistant", "content": "", "tool_calls": [call("n3", "terminal", command="ssh web-1 'df -h /var/log'")]},
        term("n3", "Filesystem Size Used Avail Use% Mounted on\n/dev/sda1 50G 21G 29G 42% /", 0),
        {"role": "assistant", "content": "Rotated with logrotate -f under sudo; /var/log is now at 42%."},
        {"role": "user", "content": "Perfect, that worked. Thanks!"}],
    "docker": [
        {"role": "user", "content": "Build the docker image for the billing service."},
        {"role": "assistant", "content": "", "tool_calls": [call("d1", "terminal", command="docker build -t billing:latest services/billing")]},
        term("d1", "ERROR: failed to solve: failed to read dockerfile: open Dockerfile: no such file or directory", 1),
        {"role": "assistant", "content": "", "tool_calls": [call("d2", "terminal", command="docker build -t billing:latest -f services/billing/docker/Dockerfile .")]},
        term("d2", "ERROR: failed to solve: process \"/bin/sh -c pip install -r requirements.txt\" did not complete successfully: exit code: 1", 1),
        {"role": "assistant", "content": "The build fails installing requirements; a private package index seems unreachable."},
        {"role": "user", "content": "Forget it for today, we'll deal with the package index next week."}],
    "certbot": [
        {"role": "user", "content": "Renew the TLS certificate for shop.example.com, it expires next week."},
        {"role": "assistant", "content": "", "tool_calls": [call("c1", "web_extract", urls=["https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates"])]},
        {"role": "tool", "tool_call_id": "c1", "name": "web_extract", "content": json.dumps({"results": [{
            "url": "https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates", "title": "User Guide",
            "content": "Renewing certificates. Certbot can renew a single certificate with the command "
                       "certbot renew --cert-name <name>. Use --dry-run first to test renewal without saving certificates. "
                       "After renewal, reload the web server so it serves the new certificate, for example systemctl "
                       "reload nginx. " * 3}]})},
        {"role": "assistant", "content": "", "tool_calls": [call("c2", "terminal", command="sudo certbot renew --cert-name shop.example.com --dry-run")]},
        term("c2", "Congratulations, all simulated renewals succeeded", 0),
        {"role": "assistant", "content": "", "tool_calls": [call("c3", "terminal", command="sudo certbot renew --cert-name shop.example.com && sudo systemctl reload nginx")]},
        term("c3", "Congratulations, all renewals succeeded", 0),
        {"role": "assistant", "content": "Renewed shop.example.com's certificate and reloaded nginx."},
        {"role": "user", "content": "Great, the padlock shows the new expiry date."}],
    "venv": [
        {"role": "user", "content": "Set up a virtualenv for the reports project and install its requirements."},
        {"role": "assistant", "content": "", "tool_calls": [call("v1", "terminal", command="cd ~/reports && python3.9 -m venv .venv && .venv/bin/pip install -r requirements.txt")]},
        term("v1", "ERROR: Package 'reports' requires a different Python: 3.9.18 not in '>=3.11'", 1),
        {"role": "assistant", "content": "The project needs Python 3.11 or newer; python3.9 is too old."},
        {"role": "user", "content": "Try python3.12 instead, it's installed."},
        {"role": "assistant", "content": "", "tool_calls": [call("v2", "terminal", command="cd ~/reports && rm -rf .venv && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt")]},
        term("v2", "Successfully installed pandas-2.2.2 reports-0.4.0", 0),
        {"role": "assistant", "content": "Created .venv with python3.12 and installed the requirements."},
        {"role": "user", "content": "Nice, works now."}],
    "mixed": [
        {"role": "user", "content": "How much disk space is left on the build server?"},
        {"role": "assistant", "content": "", "tool_calls": [call("m1", "terminal", command="ssh build-1 'df -h /'")]},
        term("m1", "/dev/nvme0n1p2 457G 390G 44G 90% /", 0),
        {"role": "assistant", "content": "44G free of 457G (90% used)."},
        {"role": "user", "content": "Unrelated: how many CPU cores does this laptop have?"},
        {"role": "assistant", "content": "", "tool_calls": [call("m2", "terminal", command="nproc")]},
        term("m2", "16", 0),
        {"role": "assistant", "content": "16 cores."},
        {"role": "user", "content": "Thanks."}],
}

EXPECT = {"nginx": {"outcome": {"succeeded"}, "tasks": 1, "dead_ends": 1},
          "docker": {"outcome": {"failed", "abandoned"}, "tasks": 1},
          "certbot": {"outcome": {"succeeded"}, "tasks": 1, "source": "eff-certbot.readthedocs.io"},
          "venv": {"outcome": {"succeeded"}, "tasks": 1, "worked_has": "python3.12"},
          "mixed": {"outcome": {"succeeded"}, "tasks": 2}}

AGAIN = {"nginx": ("The disk on web-1 is filling up with nginx logs again, can you rotate them?", "logrotate -f"),
         "docker": ("Let's try building the billing service docker image.", "docker build"),
         "certbot": ("The TLS certificate for shop.example.com needs renewing.", "certbot renew"),
         "venv": ("Recreate the virtualenv for the reports project.", "python3.12")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_model_args(ap)
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp())
    cfg = memory_config(args, user_name="Joey", agent_name="Hermes")
    cfg["sleep_guard_models"] = [args.yield_to] if args.yield_to else []   # wait for real chat, not for our own 9B
    e = fresh_engine(work, "tasks", cfg)
    t0 = time.time() - 86400
    for k, (name, msgs) in enumerate(SESSIONS.items()):
        stamped = [dict(m, timestamp=t0 + k * 3600 + i * 20) for i, m in enumerate(msgs)]
        e.capture.process_messages(f"s-{name}", stamped)
    t = time.time()
    out = SleepRunner(e, max_wait_s=3600, steps=["tasks", "index"], log=lambda *_: None).run()
    night_s = round(time.time() - t, 1)
    report = {"night_seconds": night_s, "night": out["stats"].get("tasks"), "sessions": {}, "again": {}}
    score = {"outcome": 0, "segmentation": 0, "details": 0, "recall": 0}
    for name, exp in EXPECT.items():
        rows = e.store.q("SELECT * FROM tasks WHERE session_id=? ORDER BY first_said", (f"s-{name}",))
        cards = [json.loads(r["card"]) for r in rows]
        seg_ok = len(rows) == exp["tasks"]
        out_ok = bool(rows) and all(r["outcome"] in exp["outcome"] for r in rows)
        det_ok = True
        if "dead_ends" in exp:
            det_ok &= bool(cards) and len(cards[0]["dead_ends"]) >= exp["dead_ends"]
        if "source" in exp:
            det_ok &= bool(cards) and any(exp["source"] in s["source"] for s in cards[0]["sources"])
        if "worked_has" in exp:
            det_ok &= bool(cards) and any(exp["worked_has"] in s["step"] for s in cards[0]["worked"])
        score["segmentation"] += seg_ok
        score["outcome"] += out_ok
        score["details"] += det_ok
        report["sessions"][name] = {"tasks": len(rows), "outcomes": [r["outcome"] for r in rows],
                                    "segmentation_ok": seg_ok, "outcome_ok": out_ok, "details_ok": det_ok,
                                    "cards": [c["text"] for c in cards]}
    for name, (q, must) in AGAIN.items():
        text, info = e.recall.prefetch(q, f"again-{name}")
        hit = "earlier task" in text and must in text
        score["recall"] += hit
        report["again"][name] = {"query": q, "gate": info.get("gate"), "card_injected": hit,
                                 "injection": text[:900]}
    report["score"] = {k: f"{v}/{len(EXPECT) if k != 'recall' else len(AGAIN)}" for k, v in score.items()}
    report["setup"] = {"night_model": args.night_model, "decider": args.decider, "embed": args.embed}
    e.close()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "tasks_eval.summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
