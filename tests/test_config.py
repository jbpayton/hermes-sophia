import sys

import pytest

from hermes_sophia.config import DEFAULTS, FIELDS, config_schema, endpoint, load_config
from hermes_sophia.engine import Engine
from hermes_sophia.lms import ModelServer
from hermes_sophia.sleep import SleepRunner


@pytest.fixture(autouse=True)
def no_hermes(monkeypatch):
    # never read a real profile's config.yaml during tests
    monkeypatch.setitem(sys.modules, "hermes_cli", None)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", None)


def test_every_setting_is_in_setup_and_gated():
    keys = [k for k, _, _ in FIELDS]
    assert set(DEFAULTS) <= set(keys)
    schema = {f["key"]: f for f in config_schema()}
    for k in ("user_name", "embed_model", "decider_model", "sleep_model", "lmstudio_url"):
        assert "when" not in schema[k]                                   # basics always shown
    assert schema["decider_url"]["when"] == {"server_layout": "per-job"}
    assert schema["decider_api"]["choices"] == ["lmstudio", "openai"]
    assert schema["skip_gate"]["when"] == {"show_advanced": "yes"}
    assert schema["capture_tools"]["default"] == "web_extract, browser_snapshot, browser_navigate"
    assert keys.index("server_layout") < keys.index("embed_url")        # gates come before what they gate
    assert keys.index("show_advanced") < keys.index("skip_gate")


def test_values_typed_into_setup_get_their_types():
    cfg = load_config(overrides={"skip_gate": "0.7", "recall_k": "15", "gate_permutations": "2",
                                 "capture_tools": "web_extract, browser_snapshot", "sleep_guard_models": "",
                                 "recency_bonus": 0})
    assert cfg["skip_gate"] == 0.7 and cfg["recall_k"] == 15 and cfg["gate_permutations"] == 2
    assert cfg["capture_tools"] == ["web_extract", "browser_snapshot"]
    assert cfg["sleep_guard_models"] == [cfg["sleep_model"]]
    assert cfg["recency_bonus"] == 0.0


def test_bad_value_keeps_default():
    assert load_config(overrides={"recall_k": "lots"})["recall_k"] == DEFAULTS["recall_k"]


def test_endpoints_default_to_the_shared_server():
    cfg = load_config(overrides={"lmstudio_url": "http://box:1234/", "decider_url": "http://gpu1:8081",
                                 "decider_api": "openai", "sleep_api": "bogus"})
    assert endpoint(cfg, "embed") == ("http://box:1234", "lmstudio")
    assert endpoint(cfg, "decider") == ("http://gpu1:8081", "openai")
    assert endpoint(cfg, "sleep") == ("http://box:1234", "lmstudio")    # unknown api falls back


def test_engine_builds_one_client_per_server(tmp_path):
    cfg = load_config(overrides={"decider_url": "http://gpu1:8081", "decider_api": "openai"})
    e = Engine(cfg, tmp_path / "s.db")
    assert e.clients["embed"] is e.clients["sleep"]
    assert e.clients["decider"].base_url == "http://gpu1:8081" and e.clients["decider"].api == "openai"
    assert e.decider.client is e.clients["decider"]
    assert e.status()["models"]["decider"] == {"model": cfg["decider_model"], "server": "http://gpu1:8081",
                                               "api": "openai"}
    e.close()


def _capture(monkeypatch, client, reply):
    sent = []

    def post(path, body, timeout):
        sent.append((path, body))
        return reply
    monkeypatch.setattr(client, "_post", post)
    return sent


def test_openai_server_reads_chat_logprobs(monkeypatch):
    c = ModelServer("http://gpu1:8081", api="openai")
    sent = _capture(monkeypatch, c, {"choices": [{"logprobs": {"content": [
        {"token": "B", "logprob": -0.1, "top_logprobs": [{"token": "B", "logprob": -0.1},
                                                        {"token": "A", "logprob": -2.5}]}]}}]})
    tok, tops = c.first_token_logprobs("m", "STATE…", top_logprobs=40)
    assert tok == "B" and tops == [("B", -0.1), ("A", -2.5)]
    path, body = sent[0]
    assert path == "/v1/chat/completions" and body["logprobs"] is True and body["top_logprobs"] == 20
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and "reasoning_effort" not in body


def test_chat_switches_reasoning_off_per_server_type(monkeypatch):
    reply = {"choices": [{"message": {"content": "<think>x</think>ok"}}]}
    lm, oa = ModelServer(api="lmstudio"), ModelServer(api="openai")
    s1, s2 = _capture(monkeypatch, lm, reply), _capture(monkeypatch, oa, reply)
    assert lm.chat("m", "hi") == "ok" and oa.chat("m", "hi") == "ok"
    assert s1[0][1]["reasoning_effort"] == "none" and "chat_template_kwargs" not in s1[0][1]
    assert s2[0][1]["chat_template_kwargs"] == {"enable_thinking": False} and "reasoning_effort" not in s2[0][1]


def test_server_busy_from_llama_server_slots(monkeypatch):
    c = ModelServer("http://gpu1:8081", api="openai")
    monkeypatch.setattr(c, "_get", lambda path, timeout: [{"id": 0, "is_processing": False},
                                                          {"id": 1, "is_processing": True}])
    assert c.server_busy() is True
    assert ModelServer(api="lmstudio").server_busy() is None


def test_night_waits_for_a_busy_openai_server(engine, fake):
    fake.api, fake.base_url = "openai", "http://gpu1:8081"
    fake.server_busy = lambda: True
    assert SleepRunner(engine, model="m").busy() == ["http://gpu1:8081"]
    fake.server_busy = lambda: None                                      # unknown counts as idle
    assert SleepRunner(engine, model="m").busy() == []
