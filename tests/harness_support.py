"""Shared test fixture: SDK imports are origin-bound, so use one root per process."""
import copy
from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
import time
from transformers import AutoTokenizer
from lifemate.llm import prepare_inputs, decode_response
from lifemate.config import Budget, remaining_context
from lifemate.synthetic import prepare_runtime, read, save

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "data/synthetic/handoff_v01"


def native_call(name, **arguments):
    def value(v):
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return (f"<tool_call>\n<function={name}>\n" + "".join(
        f"<parameter={k}>\n{value(v)}\n</parameter>\n" for k, v in arguments.items()
    ) + "</function>\n</tool_call>")


def observations(messages):
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


class NativeScript:
    """Only the token producer is replaced; production template and parser are shared."""

    def __init__(self, tokenizer, actions, folder):
        self.tokenizer, self.actions, self.folder = tokenizer, iter(actions), folder
        self.inputs = []
        self.identity = {"kind": "scripted_native", "name": "native-harness-tests"}

    def generate(self, messages, tools, **kwargs):
        started = time.monotonic()
        inputs = prepare_inputs(self.tokenizer, messages, tools)
        prompt = inputs["input_ids"][0]
        remaining_context(len(prompt), kwargs.get("max_context_tokens", Budget().context_tokens))
        render_seconds = time.monotonic() - started
        wire = self.tokenizer.decode(prompt, skip_special_tokens=False)
        self.inputs.append({"messages": copy.deepcopy(messages), "prompt": wire, "tools": tools})
        action = next(self.actions)  # An unexpected extra Jaz query is a test failure.
        began = time.monotonic()
        response = action(messages, wire) if callable(action) else action
        stats = {"hit_token_limit": False, "timed_out": False,
                 "timings": {"render_tokenize_seconds": render_seconds,
                             "inference_seconds": time.monotonic() - began}}
        if isinstance(response, tuple):
            response, changes = response
            stats.update(changes)
        tokens = self.tokenizer.encode(response + "<|im_end|>", add_special_tokens=False)
        result = decode_response(self.tokenizer, tokens, prompt, tools, **stats)
        save(self.folder / "native_inputs" / f"{len(self.inputs)}.json", {
            **self.inputs[-1], "scripted_raw_text": response, "parse_error": result["parse_error"],
        })
        return result


class AgentEnv:
    """Test boundary: agent gets only participant APIs, backed by a real SDK session."""

    def __init__(self, sdk):
        self._sdk = sdk

    def call(self, name, arguments):
        return self._sdk.call(name, arguments)

    def validate(self, name, arguments):
        return self._sdk.validate(name, arguments)

    def get_tool_calls(self):
        return self._sdk.get_tool_calls()

    def get_state_hash(self):
        return self._sdk.get_state_hash()



@lru_cache(maxsize=1)
def workspace():
    folder = ROOT / "runs" / ("architecture_audit_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir(parents=True)
    cases = {p.stem.removesuffix(".input"): read(p) for p in PACKAGE.glob("*.input.json")}
    runtime = prepare_runtime(PACKAGE, folder, list(cases.values()))
    tokenizer = AutoTokenizer.from_pretrained(ROOT / "models/llm/lfm3-1.7b", local_files_only=True, trust_remote_code=True)
    return folder, runtime, tokenizer, cases
