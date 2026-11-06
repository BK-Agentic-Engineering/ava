"""Offline paired transcript evaluation. No model calls or gold generation."""
import argparse
import hashlib
import json
import random
import unicodedata
from collections import defaultdict
from pathlib import Path

NORMALIZER = "nfc-lower-punctuation-space-v1"

def normalize(text):
    text = unicodedata.normalize("NFC", text).lower()
    return " ".join("".join(" " if unicodedata.category(c).startswith("P") else c for c in text).split())

def distance(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            row.append(min(row[-1] + 1, prev[j] + 1, prev[j-1] + (x != y)))
        prev = row
    return prev[-1]

def read_rows(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [r["sample_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate sample_id in {path}")
    return rows

def validate_manifest(rows):
    if not rows:
        raise ValueError("Manifest is empty")
    for r in rows:
        for key in ("sample_id", "source", "split", "speaker_id", "region", "reference"):
            if not isinstance(r.get(key), str) or not r[key].strip():
                raise ValueError(f"Missing/non-string {key}: {r.get('sample_id')}")
        if not normalize(r["reference"]):
            raise ValueError("Empty reference: silence needs a separate hallucination protocol")
    # Region is metadata, never inferred from transcript or current location.
    speakers = defaultdict(set)
    for r in rows:
        speakers[(r["source"], r["speaker_id"])].add(r["region"])
    if any(len(v) > 1 for v in speakers.values()):
        raise ValueError("A source/speaker has conflicting region labels")

def evaluate(rows, predictions):
    validate_manifest(rows)
    pred = {r["sample_id"]: r for r in predictions}
    if len(pred) != len(predictions):
        raise ValueError("Duplicate prediction ID")
    if set(pred) != {r["sample_id"] for r in rows}:
        raise ValueError("Prediction IDs must match manifest exactly; encode failures explicitly")
    scored = []
    for r in rows:
        p = pred[r["sample_id"]]
        if p.get("status") not in {"ok", "error", "timeout"}:
            raise ValueError("Unknown prediction status")
        if p["status"] == "ok" and not isinstance(p.get("text"), str):
            raise ValueError("Successful prediction needs text")
        ref = normalize(r["reference"])
        hyp = normalize(p["text"]) if p["status"] == "ok" else ""
        scored.append({**r, "word_errors": distance(ref.split(), hyp.split()),
                       "words": len(ref.split()), "char_errors": distance(ref.replace(" ", ""), hyp.replace(" ", "")),
                       "chars": len(ref.replace(" ", "")), "failed": p["status"] != "ok"})
    return scored

def summary(rows):
    if not rows:
        return {"n": 0, "wer_whitespace": None, "cer": None, "failure_rate": None}
    return {"n": len(rows), "wer_whitespace": sum(r["word_errors"] for r in rows)/sum(r["words"] for r in rows),
            "cer": sum(r["char_errors"] for r in rows)/sum(r["chars"] for r in rows),
            "failure_rate": sum(r["failed"] for r in rows)/len(rows)}

def grouped(rows, fields):
    groups = defaultdict(list)
    for r in rows:
        groups[" | ".join(str(r.get(f, "unknown")) for f in fields)].append(r)
    return {k: summary(v) for k, v in sorted(groups.items())}

def paired_ci(a, b, repeats=2000, seed=42):
    if repeats < 100:
        raise ValueError("Use at least 100 bootstrap repetitions")
    if [r["sample_id"] for r in a] != [r["sample_id"] for r in b]:
        raise ValueError("Paired rows must have identical IDs/order")
    strata = defaultdict(lambda: defaultdict(list))
    for i, r in enumerate(a):
        strata[(r["source"], r["region"])][r["speaker_id"]].append(i)
    if any(len(s) < 2 for s in strata.values()):
        return {"available": False, "reason": "Need >=2 speakers in every source/region stratum"}
    rng = random.Random(seed)
    values = []
    for _ in range(repeats):
        indexes = []
        for speakers in strata.values():
            keys = sorted(speakers)
            for key in rng.choices(keys, k=len(keys)):
                indexes.extend(speakers[key])
        values.append(summary([b[i] for i in indexes])["wer_whitespace"] - summary([a[i] for i in indexes])["wer_whitespace"])
    values.sort()
    return {"available": True, "delta_b_minus_a": summary(b)["wer_whitespace"]-summary(a)["wer_whitespace"],
            "ci95": [values[int(.025*(repeats-1))], values[int(.975*(repeats-1))]], "repeats": repeats, "seed": seed}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("predictions_a")
    parser.add_argument("predictions_b")
    parser.add_argument("--out", required=True)
    parser.add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args()
    rows = read_rows(args.manifest)
    a, b = (evaluate(rows, read_rows(p)) for p in (args.predictions_a, args.predictions_b))
    report = {"normalizer": NORMALIZER, "number_normalization": False,
              "input_sha256": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (args.manifest,args.predictions_a,args.predictions_b)},
              "paired_ci": paired_ci(a,b,args.bootstrap),
              "scope": "Transcript-only evaluation; no ASR run, slot inference or official contest score"}
    for label, data in (("a",a),("b",b)):
        regions = grouped(data,["region"])
        common = [r for r, x, y in zip(data,a,b) if not x["failed"] and not y["failed"]]
        report[label] = {"overall": summary(data), "by_region": regions, "by_source_region": grouped(data,["source","region"]),
                         "by_province": grouped(data,["source","province"]), "by_speaker": grouped(data,["source","speaker_id"]),
                         "region_macro_wer": sum(v["wer_whitespace"] for v in regions.values())/len(regions),
                         "common_success": summary(common)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
