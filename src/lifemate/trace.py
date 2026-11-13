"""Trace JSONL được flush sau từng event."""

import json
import time


class Trace:
    def __init__(self, path, sample_id):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("x", encoding="utf-8")
        self.sample_id = sample_id
        self.started = time.monotonic()

    def write(self, event, **payload):
        row = {"id": self.sample_id, "event": event,
               "elapsed_seconds": time.monotonic() - self.started, **payload}
        self.stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.stream.flush()

    def close(self):
        self.stream.close()
