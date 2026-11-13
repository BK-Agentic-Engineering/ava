"""Committed result is authoritative; journal is recovery evidence before commit."""

import hashlib
import json
import os
from pathlib import Path
import tempfile


class RecoveryRequired(RuntimeError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # A killed write stays available for inspection; a later commit won't overwrite it.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".writing.", delete=False) as stream:
        temp = stream.name
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class SessionStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def result(self):
        path = self.folder / "result.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RecoveryRequired("Committed result is corrupt; retained unchanged") from exc

    def events(self):
        path = self.folder / "journal.jsonl"
        if not path.exists():
            return []
        raw = path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise RecoveryRequired("journal trailing record is incomplete; retained unchanged")
        result = []
        for n, line in enumerate(raw.splitlines(), 1):
            try:
                result.append(json.loads(line))
            except (ValueError, UnicodeDecodeError) as exc:
                raise RecoveryRequired(f"journal line {n} is incomplete/corrupt; retained unchanged") from exc
        return result

    def append(self, event, **payload):
        with (self.folder / "journal.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **payload}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def bind(self, signature, header):
        result = self.result()
        if result:
            if result["signature"] != signature:
                raise RecoveryRequired("committed result belongs to a different input/configuration")
            return result
        events = self.events()
        if events:
            if events[0].get("signature") != signature:
                raise RecoveryRequired("journal belongs to a different input/configuration")
        else:
            self.append("session", signature=signature, **header)
        return None

    def commit(self, record):
        if (self.folder / "result.json").exists():
            raise RecoveryRequired("Session already committed; refusing to replace its result")
        atomic_json(self.folder / "result.json", record)

    def view(self, record):
        # A paused attempt is derived evidence; only result.json seals a session.
        record["journal_bytes"] = (self.folder / "journal.jsonl").stat().st_size
        atomic_json(self.folder / "last_attempt.json", record)
