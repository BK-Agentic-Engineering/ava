"""Run LifeMate batches, local evaluation and recaps."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

from .batch import run_batch, export_results, is_complete
from .config import Budget
from .data import samples, prepare_btc

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT.parent / "train+public_test/train+public_test")
    parser.add_argument("--split", default="train", choices=("train", "public_test", "private_test"))
    choose = parser.add_mutually_exclusive_group()
    choose.add_argument("--limit", type=int, default=20)
    choose.add_argument("--id", dest="sample_id")
    choose.add_argument("--all", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--text", action="store_true", help="Text is the default; train only.")
    mode.add_argument("--audio", action="store_true", help="Explicitly enable the existing ASR adapter.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--seconds", type=float, default=Budget().seconds)
    parser.add_argument("--context-tokens", type=int, default=Budget().context_tokens)
    parser.add_argument("--output-tokens", type=int, default=Budget().output_tokens)
    parser.add_argument("--score-run", type=Path)
    parser.add_argument("--recap-run", type=Path)
    args = parser.parse_args()
    if args.score_run or args.recap_run:
        folder = (args.score_run or args.recap_run).resolve()
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        if args.score_run:
            from .evaluate import evaluate_run
            print(evaluate_run(Path(metadata["data_root"]), metadata["split"], folder)["score_0_to_100"])
        from .recap import render_recap
        print(render_recap(folder))
        return
    if not args.audio and args.split != "train":
        parser.error("Text requires train transcripts. Public/private require the explicit audio adapter.")
    if args.resume and args.output is None:
        parser.error("--resume requires --output")
    if args.limit < 1:
        parser.error("--limit must be positive")
    items = list(samples(args.data_root, args.split, text=not args.audio,
        limit=None if args.all or args.sample_id else args.limit,
        ids=[args.sample_id] if args.sample_id else None))
    asr = None
    if args.audio:
        from .asr import GipformerASR
        asr = GipformerASR(ROOT / "models/asr")
    from .llm import LocalLLM
    model = LocalLLM(ROOT / "models/llm/lfm3-1.7b")
    identity = model.identity
    folder = (args.output or ROOT / "runs" / ("btc_" + datetime.now().strftime("%Y%m%d_%H%M%S"))).resolve()
    data_file = args.data_root / args.split / f"{args.split}.jsonl"
    split_count = sum(1 for line in data_file.read_text(encoding="utf-8").splitlines() if line.strip())
    source = {"kind": "btc", "data_root": str(args.data_root.resolve()), "split": args.split,
        "mode": "audio" if args.audio else "text", "split_samples": split_count,
        "dataset_sha256": hashlib.sha256(data_file.read_bytes()).hexdigest()}
    records = run_batch(items,
        lambda item: prepare_btc(item, args.data_root, args.split, text=not args.audio, asr=asr),
        model, folder, backend_identity=identity,
        budget=Budget(args.seconds, args.context_tokens, args.output_tokens), resume=args.resume, source=source)
    all_records = export_results(folder, [i["id"] for i in items])
    complete = is_complete(all_records, len(items))
    for record in records:
        print(record["id"], record["status"], record["reason"])
    if not complete:
        print("Incomplete batch: inspect sessions/*/journal.jsonl and last_attempt.json; no aggregate score.")
        return
    if args.split == "train":
        from .evaluate import evaluate_run
        print("Local score:", evaluate_run(args.data_root, args.split, folder)["score_0_to_100"])
    else:
        from .evaluate import verify_run
        print(verify_run(args.data_root, args.split, folder))

