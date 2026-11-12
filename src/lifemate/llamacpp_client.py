"""Pinned llama.cpp structured API client; no agent-framework imports."""

import hashlib
import json
import time
import urllib.request
import urllib.error
from pathlib import Path


class ResponseFormatError(ValueError):
    def __init__(self, stage, error, raw_response):
        super().__init__(f"{stage}: {error}")
        self.stage, self.raw_response = stage, raw_response


class SessionStop(BaseException):
    """Stop the session without a framework retry or synthetic final answer."""

    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


class LlamaCpp:
    def __init__(self, url, *, seed=0):
        self.url = url.rstrip("/")
        self.seed = seed
        self.props = self.request("/props")
        if self.props["model_ftype"] != "F16":
            raise ValueError("This experiment requires the non-quantized F16 GGUF")
        with Path(self.props["model_path"]).open("rb") as stream:
            model_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if model_hash != "b7ab8b69a85e4dfbf62cdfd0e02d7d051ed09f2c5b84c701771dddb073b85970":
            raise ValueError("Use the pinned official LiquidAI LFM3-1.7B F16 GGUF")
        self.identity = {
            "kind": "llamacpp", "build": self.props["build_info"],
            "precision": self.props["model_ftype"], "model_path": self.props["model_path"],
            "chat_template_sha256": hashlib.sha256(self.props["chat_template"].encode()).hexdigest(),
            "context_tokens": self.props["default_generation_settings"]["n_ctx"],
            "gguf_sha256": model_hash,
        }

    def request(self, path, body=None, timeout=30):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(self.url + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ResponseFormatError("http_json", str(exc), raw) from exc
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"llama.cpp HTTP {exc.code}: {exc.read().decode()}") from exc

    def begin(self, state, deadline, max_steps):
        self.state, self.deadline, self.max_steps = state, deadline, max_steps
        self.calls = 0

    def generate(self, messages, tools, *, deadline=None, max_context_tokens=16384,
                 max_new_tokens=2048, stop=None, tool_choice="auto"):
        deadline = self.deadline if deadline is None else deadline
        if time.monotonic() >= deadline:
            raise SessionStop("budget_exhausted", "time_limit")
        if self.calls >= self.max_steps:
            raise SessionStop("budget_exhausted", "step_limit")
        if max_new_tokens <= 0:
            raise SessionStop("budget_exhausted", "token_limit")
        if max_context_tokens != self.identity["context_tokens"]:
            raise ValueError("Start llama-server with the experiment's context size")
        self.calls += 1
        body = {"model": "lfm3", "messages": messages, "tools": tools,
                "temperature": 0, "repeat_penalty": 1.0, "max_tokens": max_new_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
                "stop": stop or [], "tool_choice": tool_choice, "seed": getattr(self, "seed", 0)}
        if tool_choice == "required":
            # b12110 permits arbitrary leading text even with required tool choice.
            body["messages"] = [*messages, {"role": "assistant", "content": "<tool_call>\n"}]
        started = time.monotonic()
        if started >= deadline:
            raise SessionStop("budget_exhausted", "time_limit")
        response = self.request("/v1/chat/completions", body, timeout=deadline-started)
        seconds = time.monotonic() - started
        choice = response["choices"][0]
        message = choice["message"]
        hit_token_limit = choice["finish_reason"] == "length"
        if not hit_token_limit and "<tool_call>" in (message.get("content") or ""):
            raise ResponseFormatError("tool_calls", "Server returned unparsed XML", response)
        calls = []
        for call in [] if hit_token_limit else (message.get("tool_calls") or []):
            args = call["function"]["arguments"]
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError as exc:
                raise ResponseFormatError("tool_arguments", str(exc), response) from exc
            if not isinstance(args, dict):
                raise ResponseFormatError("tool_arguments", "arguments must be an object", response)
            calls.append({"name": call["function"]["name"], "arguments": args})
        return {"message": message, "tool_calls": calls,
                "content": message.get("content") or "", "assistant_text": message.get("content") or "",
                "raw_text": json.dumps(response, ensure_ascii=False), "parse_error": None,
                "input_tokens": response["usage"]["prompt_tokens"],
                "output_tokens": response["usage"]["completion_tokens"],
                "seconds": seconds, "finish_reason": choice["finish_reason"],
                "hit_token_limit": hit_token_limit,
                "timed_out": time.monotonic() >= deadline,
                "http_request": body, "server_timings": response.get("timings"),
                "timings": {"http_seconds": seconds}}


