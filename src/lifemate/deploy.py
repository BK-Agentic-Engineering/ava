"""Live audio -> existing smolagents harness -> organizer SDK, without evaluation."""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import random
import subprocess
import time
import urllib.error
import urllib.request

import numpy as np

from .config import Budget
from .data import samples, build_messages
from .execution import context, emit
from .llamacpp_client import LlamaCpp, SessionStop, ResponseFormatError
from .sdk import create_env
from .smolagents_harness import run_smolagents
from .submission import submission_row
from .tools import load_allowed_tools
from .trace import Trace


SEED = 0
MAX_STEPS = 8
BUDGET = Budget(seconds=30, context_tokens=16384, output_tokens=2048)
SERVER_STARTUP_TIMEOUT = 120


def set_seed(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)


def infer_sample(item, root, split, asr, backend, trace, *, budget=BUDGET):
    state = context()
    state["run_id"] = f"{split}/{item['id']}"
    started = state["started"]
    deadline = started + budget.seconds
    backend.begin(state, deadline, MAX_STEPS)
    env = None
    preparation_seconds = 0
    try:
        env = create_env(root, split, item["id"])
        if time.monotonic() >= deadline:
            raise TimeoutError("Sample deadline reached before ASR")
        prepared = {"id": item["id"],
                    "messages": build_messages(item, root, split, asr=asr, deadline=deadline),
                    "tools": load_allowed_tools(root, split, item)}
        preparation_seconds = time.monotonic() - started
        state["messages"] = prepared["messages"]
        emit(state, trace, "input", messages=prepared["messages"], tools=prepared["tools"])
        result = run_smolagents(prepared, backend, env, state, trace, budget)
    except SessionStop as exc:
        result = {"status": exc.status, "reason": exc.reason, "final_text": None}
    except TimeoutError as exc:
        result = {"status": "budget_exhausted", "reason": "time_limit", "error": str(exc)}
    except ResponseFormatError as exc:
        result = {"status": "protocol_error", "reason": exc.stage, "error": str(exc)}
    except Exception as exc:
        result = {"status": "runner_error", "reason": "exception",
                  "error": f"{type(exc).__name__}: {exc}"}
    if not state["messages"]:
        preparation_seconds = time.monotonic() - started
    row = submission_row(item["id"], env) if env is not None else None
    elapsed = time.monotonic() - started
    if elapsed > budget.seconds:
        result.update(status="budget_exhausted", reason="time_limit")
    if row is not None:
        row["time"] = int(elapsed * 1000)
    metrics = {"elapsed_seconds": elapsed, "preparation_seconds": preparation_seconds,
               "backend_wall_seconds": sum(e.get("backend_wall_seconds", 0) for e in state["events"]),
               "tool_seconds": sum(p["seconds"] for p in state["pairs"]),
               "model_calls": backend.calls}
    record = {"id": item["id"], **result, "submission": row,
              "calls": state["pairs"], "metrics": metrics}
    emit(state, trace, "end", record=record)
    return record


def run_split(root, split, output, asr, backend, *, smoke_test=False, sample_id=None,
              submission_name="submission.jsonl"):
    if sample_id is not None and not smoke_test:
        raise ValueError("sample_id requires smoke_test=True")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    diagnostics = output / Path(submission_name).stem
    diagnostics.mkdir(exist_ok=False)
    errors = 0
    step_limited = 0
    written = 0
    count = 0
    with (output / submission_name).open("x", encoding="utf-8") as submission, \
            (diagnostics / "results.jsonl").open("x", encoding="utf-8") as results:
        for item in samples(root, split, limit=1 if smoke_test else None,
                            ids=[sample_id] if sample_id is not None else None):
            trace = Trace(diagnostics / "traces" / f"{item['id']}.jsonl", item["id"])
            try:
                record = infer_sample(item, root, split, asr, backend, trace)
            finally:
                trace.close()
            row = record["submission"]
            if row is not None:
                submission.write(json.dumps(row, ensure_ascii=False) + "\n")
                submission.flush()
                written += 1
            results.write(json.dumps(record, ensure_ascii=False) + "\n")
            results.flush()
            count += 1
            status, reason = record["status"], record.get("reason")
            if row is not None and status == "budget_exhausted" and reason == "step_limit":
                step_limited += 1
            elif row is None or status not in ("completed", "waiting_for_user"):
                errors += 1
            print(f"PREDICT {item['id']} {status} reason={reason} {record['metrics']['elapsed_seconds']:.3f}s "
                  f"{len(record['calls'])} SDK calls", flush=True)
    if count == 0:
        raise ValueError(f"Empty split: {split}")
    print(f"OUTPUT {output / submission_name}; rows={written}; samples={count}; "
          f"step_limited={step_limited}; errors={errors}; smoke_test={smoke_test}", flush=True)
    return errors


@contextmanager
def load_models(assets, output, *, server_binary="/opt/llamacpp/llama-server"):
    from .asr import GipformerASR

    assets, output = Path(assets), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    asr = GipformerASR(assets / "asr")
    asr.warmup()
    print(f"LOAD ASR {time.monotonic() - started:.3f}s (including synthetic CUDA warmup)", flush=True)
    arguments = [server_binary, "-m", str(assets / "llm/lfm3-1.7b-gguf/LFM3-1.7B-F16.gguf"),
                 "--host", "127.0.0.1", "--port", "8087", "--device", "CUDA0", "-ngl", "99",
                 "-c", str(BUDGET.context_tokens), "-np", "1", "-n", str(BUDGET.output_tokens),
                 "--seed", str(SEED), "--temp", "0", "--repeat-penalty", "1", "--jinja",
                 "--no-ui", "--no-context-shift", "--no-reasoning-preserve"]
    llm_started = time.monotonic()
    startup_deadline = llm_started + SERVER_STARTUP_TIMEOUT
    log_path = output / "llama-server.log"
    with log_path.open("x", encoding="utf-8") as log:
        server = subprocess.Popen(arguments, stdout=log, stderr=subprocess.STDOUT)
        try:
            while server.poll() is None:
                remaining = startup_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"llama-server did not become healthy within {SERVER_STARTUP_TIMEOUT}s; see {log_path}")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8087/health", timeout=min(1, remaining)) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    pass
                time.sleep(min(0.1, max(0, startup_deadline - time.monotonic())))
            else:
                raise RuntimeError(f"llama-server exited with {server.returncode}; see {log_path}")
            backend = LlamaCpp("http://127.0.0.1:8087", seed=SEED)
            print(f"LOAD LLM {time.monotonic() - llm_started:.3f}s; TOTAL {time.monotonic() - started:.3f}s", flush=True)
            (output / "runtime.json").write_text(json.dumps({"backend": backend.identity,
                "server_arguments": arguments, "budget": BUDGET.to_dict(), "max_steps": MAX_STEPS,
                "seed": SEED, "asr_providers": {k: v.get_providers() for k, v in asr.sessions.items()}},
                ensure_ascii=False, indent=2), encoding="utf-8")
            yield asr, backend
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


def run(root=Path("/data"), split="private_test", output=Path("/result"), *,
        assets=Path("/app/models"), smoke_test=False, sample_id=None,
        submission_name="submission.jsonl"):
    if sample_id is not None and not smoke_test:
        raise ValueError("sample_id requires smoke_test=True")
    set_seed()
    print(f"CONFIG seed={SEED}; budget={BUDGET.to_dict()}; steps={MAX_STEPS}; live_audio=True", flush=True)
    with load_models(assets, Path(output) / (Path(submission_name).stem + "_runtime")) as (asr, backend):
        return run_split(Path(root), split, output, asr, backend,
                         smoke_test=smoke_test, sample_id=sample_id, submission_name=submission_name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("/data"))
    parser.add_argument("--split", default="private_test", choices=("train", "public_test", "private_test"))
    parser.add_argument("--output", type=Path, default=Path("/result"))
    parser.add_argument("--assets", type=Path, default=Path("/app/models"))
    parser.add_argument("--smoke-test", action="store_true", help="Run only the first sample; diagnostic, not a submission")
    parser.add_argument("--sample-id", help="Select one sample, only with --smoke-test")
    args = parser.parse_args()
    if args.sample_id is not None and not args.smoke_test:
        parser.error("--sample-id requires --smoke-test")
    raise SystemExit(bool(run(args.data_root, args.split, args.output,
                             assets=args.assets, smoke_test=args.smoke_test, sample_id=args.sample_id)))


if __name__ == "__main__":
    main()
