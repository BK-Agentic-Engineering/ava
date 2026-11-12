"""Verify a deploy run with the organizer SDK after inference."""

import argparse
from collections import Counter
import json
from pathlib import Path

from lifemate.data import read_jsonl
from lifemate.evaluate import evaluate_run
from lifemate.sdk import create_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("/data"))
    parser.add_argument("--split", choices=("train", "public_test", "private_test"), required=True)
    parser.add_argument("--sample-id", help="Verify one explicitly selected smoke sample")
    parser.add_argument("--score-train", action="store_true", help="Write local train metrics.json")
    args = parser.parse_args()
    if args.score_train and args.split != "train":
        parser.error("--score-train requires --split train")

    dataset = args.data_root / args.split / f"{args.split}.jsonl"
    expected = [item["id"] for item in read_jsonl(dataset)
                if args.sample_id is None or item["id"] == args.sample_id]
    rows = list(read_jsonl(args.output / "submission.jsonl"))
    results = list(read_jsonl(args.output / "submission/results.jsonl"))
    if (not expected or len(set(expected)) != len(expected)
            or [row["id"] for row in rows] != expected
            or [record["id"] for record in results] != expected):
        raise ValueError("Submission/results IDs do not match the selected dataset in order")

    replayed = 0
    for row, record in zip(rows, results):
        sample_id = row["id"]
        if (set(row) != {"id", "tool_calls", "state_hash", "time"}
                or type(row["time"]) is not int or row["time"] < 0
                or row != record["submission"]
                or row["tool_calls"] != [pair["call"] for pair in record["calls"]]):
            raise ValueError(f"{sample_id}: invalid submission or mismatch with results")
        env = create_env(args.data_root, args.split, sample_id)
        for index, pair in enumerate(record["calls"], start=1):
            call = pair["call"]
            result = env.call(call["name"], call["arguments"])
            if result != pair["result"] or env.get_state_hash() != pair["state_hash"]:
                raise ValueError(f"{sample_id}: SDK result or hash mismatch after call {index}")
            replayed += 1
        if env.get_tool_calls() != row["tool_calls"] or env.get_state_hash() != row["state_hash"]:
            raise ValueError(f"{sample_id}: final SDK calls or hash mismatch")

    report = {"split": args.split, "rows_verified": len(rows), "sdk_calls_replayed": replayed,
              "runtime_statuses": dict(Counter(record["status"] for record in results)),
              "rows_over_30_seconds": sum(row["time"] > 30_000 for row in rows)}
    if args.score_train:
        if (args.output / "metrics.json").exists():
            raise FileExistsError(args.output / "metrics.json")
        summaries = {record["id"]: {"status": record["status"],
                     "elapsed_seconds": record["metrics"]["elapsed_seconds"]} for record in results}
        score = evaluate_run(args.data_root, args.split, args.output,
                             sample_ids=expected, summaries=summaries)
        report["local_train_score_0_to_100"] = score["score_0_to_100"]
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
