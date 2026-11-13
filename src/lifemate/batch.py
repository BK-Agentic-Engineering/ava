import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone

from .agent import run_session, summary
from .config import Budget
from .sdk import create_env
from .store import SessionStore, RecoveryRequired, atomic_json, fingerprint
from .trace import Trace


def implementation_id():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def session_trace(run_dir, sid):
    path = Path(run_dir) / "traces" / f"{sid}.jsonl"
    if path.exists():
        number = len(list(path.parent.glob(f"{sid}*.jsonl"))) + 1
        path = path.with_name(f"{sid}.attempt_{number}.jsonl")
    return Trace(path, sid)


def records_from_disk(run_dir, ids):
    records = []
    for sid in ids:
        folder = Path(run_dir) / "sessions" / sid
        if not folder.exists():
            continue
        result = SessionStore(folder).result()
        if result:
            records.append(result)
            continue
        view = folder / "last_attempt.json"
        journal = folder / "journal.jsonl"
        if view.exists() and journal.exists():
            value = json.loads(view.read_text(encoding="utf-8"))
            if value.get("journal_bytes") == journal.stat().st_size:
                records.append(value)
    return records


def is_complete(records, expected_count):
    return len(records) == expected_count and all(
        record["terminal"] and record["submission"] for record in records
    )


def export_results(run_dir, ids):
    """Derived exports can be rebuilt; result.json/journal remain untouched."""
    records = records_from_disk(run_dir, ids)
    for name, values in (
        ("submission.jsonl", [r["submission"] for r in records if r["submission"] is not None]),
        ("samples.jsonl", [summary(r) for r in records]),
    ):
        path = Path(run_dir) / name
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            for value in values:
                stream.write(json.dumps(value, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    manifest = Path(run_dir) / "batch.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        complete = is_complete(records, len(ids))
        atomic_json(Path(run_dir) / "metadata.json", {**data["source"], "sample_ids": ids,
            "budget": data["budget"], "backend": data["backend"], "created_at": data["created_at"],
            "completed_samples": sum(r["terminal"] for r in records), "recorded_samples": len(records),
            "complete_selected_batch": complete,
            "is_complete_split": complete and len(records) == data["source"].get("split_samples")})
    return records


def run_batch(items, prepare, backend, run_dir, *, backend_identity, budget=None,
              resume=False, source=None):
    budget = budget or Budget()
    run_dir = Path(run_dir)
    items = list(items)
    ids = [item.get("id", item.get("sample_id")) for item in items]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Batch requires distinct sample IDs")
    if any(not isinstance(sid, str) or Path(sid).name != sid or sid in (".", "..") for sid in ids):
        raise ValueError("Sample ID cannot be a filesystem path")
    identity = {**backend_identity, "implementation": implementation_id()}
    config = {"selection": fingerprint(items), "ids": ids, "backend": identity,
              "budget": budget.to_dict(), "source": source or {}}
    signature = fingerprint(config)
    manifest = run_dir / "batch.json"
    if resume:
        if not manifest.exists():
            raise RecoveryRequired("No batch.json: legacy/unknown run is not automatically resumable")
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        if previous["signature"] != signature:
            raise RecoveryRequired("Batch input/source/backend/config/code changed")
    else:
        if manifest.exists() or (run_dir / "submission.jsonl").exists() or (run_dir / "sessions").exists():
            raise FileExistsError("Run already has results; use --resume or a new directory")
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(manifest, {"signature": signature, "created_at": datetime.now(timezone.utc).isoformat(), **config})
    records = []
    try:
        for item, sid in zip(items, ids):
            store = SessionStore(run_dir / "sessions" / sid)
            existing = store.result()
            if existing and existing["status"] == "preparation_error":
                records.append(existing)
                continue
            began = time.monotonic()
            try:
                prepared = prepare(item)
            except Exception as exc:
                if existing:
                    raise RecoveryRequired("Source no longer prepares like the committed session") from exc
                # No SDK session/hash exists; don't fabricate a submission line.
                record = {"id": sid, "run_id": f"{run_dir.name}/{sid}", "terminal": True,
                    "status": "preparation_error", "reason": "adapter_error", "final_text": None,
                    "error": f"{type(exc).__name__}: {exc}", "submission": None, "calls": [],
                    "signature": signature, "backend": identity, "source": source or {},
                    "metrics": {"preparation_seconds": time.monotonic() - began}}
                store.commit(record)
                records.append(record)
                export_results(run_dir, ids)
                continue
            prepared["run_id"] = f"{run_dir.name}/{sid}"
            prepared["timings"] = {"preparation_seconds": time.monotonic() - began}
            env = prepared["environment"]
            trace = session_trace(run_dir, sid)
            try:
                record = run_session(prepared, backend,
                    lambda: create_env(Path(env["root"]), env["split"], env["sample_id"]),
                    trace, store=store, budget=budget, backend_identity=identity, resume=resume)
            finally:
                trace.close()
            records.append(record)
            export_results(run_dir, ids)
            if record["status"] == "externally_interrupted":
                break
    finally:
        export_results(run_dir, ids)
    return records
