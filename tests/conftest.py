import re
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_sophia.config import DEFAULTS  # noqa: E402
from hermes_sophia.engine import Engine  # noqa: E402


class FakeLMS:
    """Deterministic stand-in for LM Studio: hashing-trick embeddings, scripted readouts and chats."""

    def __init__(self):
        self.readout = lambda prompt: [("B", -0.05), ("A", -3.0)]   # default: 'true' for a noul
        self.chat_fn = lambda prompt: ""
        self.calls = {"embed": 0, "readout": 0, "chat": 0}
        self.status = {"qwen/qwen3.8-27b": "idle"}

    def embed(self, texts, model, kind="document", timeout=10.0, batch=64):
        self.calls["embed"] += 1
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                if len(tok) > 2:
                    out[i, zlib.crc32(tok.encode()) % 256] += 1.0
        n = np.linalg.norm(out, axis=1, keepdims=True)
        n[n == 0] = 1
        return out / n

    def first_token_logprobs(self, model, prompt, top_logprobs=10, timeout=30.0):
        self.calls["readout"] += 1
        tops = self.readout(prompt)
        return tops[0][0], tops

    def chat(self, model, prompt, max_tokens=1024, temperature=0.0, timeout=120.0, system=None):
        self.calls["chat"] += 1
        return self.chat_fn(prompt)

    def model_status(self):
        return self.status


@pytest.fixture
def fake():
    return FakeLMS()


@pytest.fixture
def engine(tmp_path, fake):
    cfg = dict(DEFAULTS, user_name="Joey", agent_name="Hermes", junk_floor=0.05, skip_gate=0.99,
               sleep_guard_models=["qwen/qwen3.8-27b"])
    e = Engine(cfg, tmp_path / "sophia.db", client=fake)
    yield e
    e.close()
