"""Fault-injection child. No model weights; hard exit at a journal/commit boundary."""
import json
import os
from pathlib import Path
import sys

from transformers import AutoTokenizer
from harness_support import NativeScript, ROOT
from lifemate.agent import run_session
from lifemate.sdk import create_env
from lifemate.batch import session_trace
from lifemate.config import Budget
from lifemate.store import SessionStore

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
folder = Path(payload["folder"])
spec = payload["prepared"]
phase = payload["phase"]
tokenizer = AutoTokenizer.from_pretrained(ROOT / "models/llm/lfm3-1.7b", local_files_only=True, trust_remote_code=True)
backend = NativeScript(tokenizer, [payload["raw"]], folder / "child_backend")
append = SessionStore.append
commit = SessionStore.commit


def crashing_append(self, event, **data):
    if event == "tool" and phase == "after_sdk_before_result":
        os._exit(78)
    if event == "tool" and phase == "torn_result":
        with (self.folder / "journal.jsonl").open("ab") as stream:
            stream.write(b'{"event":"tool"')
            stream.flush()
            os.fsync(stream.fileno())
        os._exit(79)
    append(self, event, **data)
    if event == "tool" and phase == "after_result":
        os._exit(77)
    if event == "model_input" and phase == "inflight_model":
        os._exit(81)


def crashing_commit(self, record):
    commit(self, record)
    if phase == "after_commit":
        os._exit(80)


SessionStore.append = crashing_append
SessionStore.commit = crashing_commit
env = spec["environment"]
trace = session_trace(folder, spec["id"])
run_session(spec, backend,
    lambda: create_env(Path(env["root"]), env["split"], env["sample_id"]), trace,
    store=SessionStore(folder / "sessions" / spec["id"]),
    backend_identity=payload["identity"], budget=Budget())
