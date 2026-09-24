"""Minimal client for LM Studio's OpenAI-compatible server: embeddings, chat, first-token logprobs, model status."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


class LMStudioError(RuntimeError):
    pass


class LMStudio:
    def __init__(self, base_url: str = "http://127.0.0.1:1234", lms_cli: str = ""):
        self.base_url = base_url.rstrip("/")
        self.lms_cli = lms_cli

    # ------------------------------------------------------------------ http
    def _post(self, path: str, body: dict, timeout: float) -> dict:
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            raise LMStudioError(f"{path} HTTP {e.code}: {detail}") from e
        except Exception as e:  # timeouts, refused connections
            raise LMStudioError(f"{path}: {e}") from e

    # ------------------------------------------------------------ embeddings
    def embed(self, texts: Sequence[str], model: str, kind: str = "document", timeout: float = 10.0,
              batch: int = 64) -> np.ndarray:
        """L2-normalized float32 matrix. nomic requires task prefixes; they are applied here."""
        prefix = "search_query: " if kind == "query" else "search_document: "
        out: List[List[float]] = []
        for i in range(0, len(texts), batch):
            chunk = [prefix + (t or " ") for t in texts[i:i + batch]]
            r = self._post("/v1/embeddings", {"model": model, "input": chunk}, timeout)
            data = sorted(r.get("data", []), key=lambda d: d.get("index", 0))
            if len(data) != len(chunk):
                raise LMStudioError(f"embeddings returned {len(data)} vectors for {len(chunk)} inputs")
            out.extend(d["embedding"] for d in data)
        if not out:
            return np.zeros((0, 0), dtype=np.float32)
        m = np.asarray(out, dtype=np.float32)
        n = np.linalg.norm(m, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return m / n

    # ------------------------------------------------------------------ chat
    def chat(self, model: str, prompt: str, max_tokens: int = 1024, temperature: float = 0.0,
             timeout: float = 120.0, system: Optional[str] = None) -> str:
        """Plain completion with reasoning off (LM Studio honours top-level ``reasoning_effort: none``)."""
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        r = self._post("/v1/chat/completions", {"model": model, "messages": messages, "max_tokens": max_tokens,
                                                  "temperature": temperature, "reasoning_effort": "none"}, timeout)
        try:
            text = r["choices"][0]["message"].get("content") or ""
        except Exception as e:
            raise LMStudioError(f"unexpected chat response: {str(r)[:200]}") from e
        return _THINK.sub("", text).strip()

    # -------------------------------------------------------------- readout
    def first_token_logprobs(self, model: str, prompt: str, top_logprobs: int = 10,
                             timeout: float = 30.0) -> Tuple[str, List[Tuple[str, float]]]:
        """(first token, [(token, logprob), ...]) for a one-token answer with reasoning off."""
        body = {"model": model, "input": prompt, "max_output_tokens": 2, "temperature": 0,
                "top_logprobs": top_logprobs, "reasoning": {"effort": "none"},
                "include": ["message.output_text.logprobs"]}
        r = self._post("/v1/responses", body, timeout)
        msgs = [o for o in r.get("output", []) if o.get("type") == "message"]
        if not msgs:
            raise LMStudioError(f"no message in response ({[o.get('type') for o in r.get('output', [])]})")
        content = msgs[0]["content"][0]
        lps = content.get("logprobs") or []
        if not lps:
            raise LMStudioError("no logprobs returned")
        first = lps[0]
        return first.get("token", ""), [(t.get("token", ""), float(t["logprob"])) for t in first.get("top_logprobs", [])]

    # ---------------------------------------------------------------- status
    def model_status(self) -> Optional[Dict[str, str]]:
        """{identifier: status} from ``lms ps --json`` (idle | generating | ...); None if unavailable."""
        if not self.lms_cli:
            return None
        try:
            p = subprocess.run([self.lms_cli, "ps", "--json"], capture_output=True, text=True, timeout=10)
            rows = json.loads(p.stdout or "[]")
            return {row.get("identifier") or row.get("modelKey"): str(row.get("status") or row.get("state") or "")
                    for row in rows}
        except Exception:
            return None
