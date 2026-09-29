"""Mindscape's read layer and curation: what the dashboard shows, and that every change it makes can be undone."""
import os
import sys
import time

import pytest

from hermes_sophia import observe as O
from hermes_sophia.sleep import SleepRunner
from test_sleep import _fake_models


@pytest.fixture(autouse=True)
def no_model_probes(monkeypatch):
    monkeypatch.setattr(O, "model_health", lambda cfg: [{"role": "decider", "model": cfg["decider_model"], "up": True}])


def _day_and_night(engine, fake):
    """The camera change, a dentist plan whose date passed, and one recall: then a night."""
    _fake_models(fake)
    t = time.time() - 3600
    engine.capture_turn("s1", "", "", [
        {"role": "user", "content": "For Yosemite I'm bringing the Fujifilm X-T5 camera this time.", "timestamp": t},
        {"role": "assistant", "content": "Nice choice, it's much lighter than the Sony.", "timestamp": t + 5}])
    engine.capture_turn("s2", "", "", [
        {"role": "user", "content": "Change of plans, I'm bringing the Sony instead of the Fujifilm.", "timestamp": t + 600},
        {"role": "user", "content": "Also I have a dentist appointment with Dr. Patel yesterday that I forgot.", "timestamp": t + 700}])
    engine.prefetch("What camera is Joey bringing to Yosemite?", "s3")
    engine.capture_turn("s3", "What camera is Joey bringing to Yosemite?", "The Sony A7, since plans changed.")
    assert SleepRunner(engine, model="fake-9b", max_wait_s=0).run()["status"] == "complete"


def test_the_night_reports_its_progress_while_it_runs(engine, fake):
    _fake_models(fake)
    engine.capture_turn("s", "", "", [{"role": "user", "content": "I'm bringing the Sony camera.", "timestamp": time.time() - 60}])
    seen = {}
    r = SleepRunner(engine, model="fake-9b", max_wait_s=0)
    orig = r.step_relate

    def spy():
        seen["during"] = engine.store.get_meta("sleep_progress")
        return orig()
    r.step_relate = spy
    assert r.run()["status"] == "complete"
    d = seen["during"]
    assert d["status"] == "running" and d["step"] == "relate" and d["pid"] == os.getpid()
    assert d["index"] == d["steps"].index("relate") + 1
    after = engine.store.get_meta("sleep_progress")
    assert after["status"] == "complete" and after["step"] is None and after["finished"] >= after["started"]


def test_a_dead_night_is_shown_as_interrupted_not_running(engine):
    engine.store.set_meta("sleep_progress", {"status": "running", "pid": 2 ** 22 + 12345, "step": "integrate",
                                             "steps": ["integrate"], "index": 1, "started": time.time()})
    st = O.now_state(engine.store.path, engine.cfg)["sleep"]
    assert st["running"] is False and st["progress"]["status"] == "interrupted"


def test_overview_queue_and_recall_read_the_store(engine, fake):
    _day_and_night(engine, fake)
    path, cfg = engine.store.path, engine.cfg
    ov = O.overview(path, cfg)
    assert ov["night"]["status"] == "complete" and ov["night"]["superseded"] == 1
    assert ov["sizes"]["lines"] >= 4 and ov["recall"]["messages"] == 1
    q = O.queue(path, cfg)
    kinds = {i["type"] for i in q["items"]}
    assert {"superseded", "plan"} <= kinds and q["plans_total"] == 1
    plan = next(i for i in q["items"] if i["type"] == "plan")
    assert plan["fact"][2] == "Dr. Patel" and "dentist" in plan["sources"][0]["text"]
    rec = O.recall_list(path, cfg)["items"][0]
    d = O.recall_detail(path, cfg, rec["id"])
    assert d["query"].startswith("What camera") and d["verdict"] in ("injected", "possible", "general", "closed")
    assert d["ms"] is not None and "referential" in d          # the gate record now carries latency and follow-ups
    now = O.now_state(path, cfg)
    assert now["capture"]["session_id"] in ("s1", "s2", "s3") and now["recall"][0]["id"] == rec["id"]


def test_graph_and_pages(engine, fake):
    _day_and_night(engine, fake)
    g = O.graph(engine.store.path, engine.cfg)
    joey = next(n for n in g["nodes"] if n["id"] == "joey")
    assert joey["subject"] and joey["role"] == "user"
    assert any(e["status"] == "superseded" for e in g["edges"])
    page = O.entity(engine.store.path, engine.cfg, "Joey")
    assert page["groups"]["before"] and page["groups"]["planned"] and page["groups"]["check"]   # Fujifilm, Sony, Dr. Patel
    assert any("Sony" in w["text"] for w in page["mentions"])
    assert O.entity(engine.store.path, engine.cfg, "nobody at all") is None


def test_plan_outcome_review_and_undo_round_trip(engine, fake):
    _day_and_night(engine, fake)
    s, path, cfg = engine.store, engine.store.path, engine.cfg
    fid = s.one("SELECT id FROM facts WHERE status='unconfirmed'")["id"]
    assert s.resolve_plan(fid, "happened", "went on Monday")
    assert tuple(s.one("SELECT status, modality FROM facts WHERE id=?", (fid,))) == ("active", "asserted")
    assert not any(i["type"] == "plan" for i in O.queue(path, cfg)["items"])
    jid = s.one("SELECT MAX(id) AS m FROM journal")["m"]
    assert s.undo_journal(jid)
    assert tuple(s.one("SELECT status, modality FROM facts WHERE id=?", (fid,))) == ("unconfirmed", "planned")
    assert s.undo_journal(jid) is None                          # an undo happens once
    # "didn't happen" keeps the fact but stops it being current
    assert s.resolve_plan(fid, "didnt") and s.one("SELECT status FROM facts WHERE id=?", (fid,))["status"] == "cancelled"
    # reviewing a supersession takes it off the queue; undoing the review puts it back
    sup = next(i for i in O.queue(path, cfg)["items"] if i["type"] == "superseded")
    s.mark_reviewed(sup["key"], "both can be true? no, it changed")
    assert not any(i["key"] == sup["key"] for i in O.queue(path, cfg)["items"])
    s.undo_journal(s.one("SELECT MAX(id) AS m FROM journal WHERE kind='reviewed'")["m"])
    assert any(i["key"] == sup["key"] for i in O.queue(path, cfg)["items"])
    # and undoing the supersession itself makes the old fact current again
    assert s.undo_journal(sup["journal_id"])
    assert O.journal(path)["entries"][0]["kind"] == "undone"
    with pytest.raises(ValueError):
        s.resolve_plan(fid, "maybe")


def test_the_dashboard_api(engine, fake, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import importlib.util
    from pathlib import Path
    _day_and_night(engine, fake)
    api_file = Path(__file__).resolve().parents[1] / "hermes_sophia" / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("sophia_plugin_api_test", api_file)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sophia_plugin_api_test", mod)      # as the dashboard's loader does
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_ctx", lambda: (engine.cfg, engine.store.path))
    monkeypatch.setattr(mod.O, "model_health", lambda cfg: [])
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/sophia")
    c = TestClient(app)
    for p in ("now", "overview", "queue", "journal", "graph", "entities", "entity/joey", "recall"):
        assert c.get(f"/api/plugins/sophia/{p}").status_code == 200, p
    assert c.get("/api/plugins/sophia/entity/nobody").status_code == 404
    w = engine.store.one("SELECT id FROM windows WHERE session_id='s2' AND text LIKE '%dentist%'")["id"]
    assert c.post("/api/plugins/sophia/correct", json={"action": "drop", "window_id": w, "reason": ""}).status_code == 400
    r = c.post("/api/plugins/sophia/correct", json={"action": "drop", "window_id": w, "reason": "test"}).json()
    assert r["ok"] and "dropped" in engine.store.one("SELECT flags FROM windows WHERE id=?", (w,))["flags"]
    assert c.post("/api/plugins/sophia/undo", json={"journal_id": r["journal_id"]}).json()["ok"]
    assert "dropped" not in engine.store.one("SELECT flags FROM windows WHERE id=?", (w,))["flags"]
    assert c.post("/api/plugins/sophia/undo", json={"journal_id": r["journal_id"]}).status_code == 409
    fid = engine.store.one("SELECT id FROM facts WHERE status='unconfirmed'")["id"]
    assert c.post("/api/plugins/sophia/plan", json={"fact_id": fid, "outcome": "happened"}).json()["ok"]


def test_clusters_find_groups_and_leave_strays_loose():
    w = {("a", "b"): 1, ("b", "c"): 1, ("a", "c"): 1, ("x", "y"): 1, ("y", "z"): 1, ("x", "z"): 1, ("c", "x"): 0.2,
         ("p", "q"): 1}
    cl = O.communities(w)
    assert cl["a"] == cl["b"] == cl["c"] != cl["x"] == cl["y"] == cl["z"]
    assert cl["p"] == cl["q"] == -1                      # a pair is too small to call a cluster
    assert O.communities({}) == {}


def test_graph_carries_clusters_and_the_dashboard_defaults(engine, fake):
    _day_and_night(engine, fake)
    engine.cfg["dashboard_graph_hops"] = 3
    g = O.graph(engine.store.path, engine.cfg)
    assert all("cluster" in n for n in g["nodes"])
    assert g["settings"] == {"hops": 3, "view": "neighborhood"}
    for c in g["clusters"]:
        assert c["size"] >= 3 and c["label"] and set(c["top"]) <= {n["id"] for n in g["nodes"]}
