"""State-gated tool F1 theo công thức BTC; gold chỉ đọc ở verifier.

Token-F1 dùng lowercase + NFC + whitespace multiset. Cách tách token chưa
được đối chiếu mã evaluator BTC; không tuyên bố parity tuyệt đối.
"""

from collections import Counter
import json
import unicodedata

from .data import read_jsonl
from .sdk import create_env


def token_f1(pred, gold):
    if not isinstance(pred, str) or not isinstance(gold, str):
        return 0.0
    def tokens(value):
        return Counter(unicodedata.normalize("NFC", value.lower()).split())
    p, g = tokens(pred), tokens(gold)
    size = sum(p.values()) + sum(g.values())
    return 2 * sum((p & g).values()) / size if size else 1.0


def match_value(pred, gold, schema):
    if schema.get("x-match") == "fuzzy":
        return token_f1(pred, gold) > 0.6
    if isinstance(gold, dict):
        return (
            isinstance(pred, dict) and pred.keys() == gold.keys()
            and all(match_value(pred[k], value, schema.get("properties", {}).get(k, {}))
                    for k, value in gold.items())
        )
    if isinstance(gold, list):
        return (
            isinstance(pred, list) and len(pred) == len(gold)
            and all(match_value(p, g, schema.get("items", {})) for p, g in zip(pred, gold))
        )
    if isinstance(pred, bool) != isinstance(gold, bool):
        return False
    return pred == gold


def match_call(pred, gold, tools):
    name = gold["name"]
    return (
        pred.get("name") == name and name in tools
        and match_value(pred.get("arguments", {}), gold.get("arguments", {}),
                        tools[name]["parameters"])
    )


def maximum_matches(edges, gold_count):
    """Maximum bipartite matching; greedy có thể đếm thiếu khi fuzzy edges giao nhau."""
    owner = [None] * gold_count
    def augment(pred, seen):
        for gold in edges[pred]:
            if gold in seen:
                continue
            seen.add(gold)
            if owner[gold] is None or augment(owner[gold], seen):
                owner[gold] = pred
                return True
        return False
    return sum(augment(pred, set()) for pred in range(len(edges)))


def score_calls(pred, gold, hash_match, tools, valid=None):
    valid = [True] * len(pred) if valid is None else valid
    edges = [
        [j for j, g in enumerate(gold) if valid[i] and match_call(p, g, tools)]
        for i, p in enumerate(pred)
    ]
    matched = maximum_matches(edges, len(gold))
    unmatched = len(pred) - matched  # Gồm cả calls bị SDK từ chối.
    precision = matched / len(pred) if pred else 0.0
    recall = matched / len(gold) if gold else 0.0
    if not gold:
        score = float(not pred)
    elif not hash_match or matched == 0:
        score = 0.0
    else:
        score = 2 * precision * recall / (precision + recall)
    return {"score": score, "matched": matched, "unmatched": unmatched,
            "gold_calls": len(gold), "predicted_calls": len(pred),
            "precision": precision, "recall": recall, "state_match": hash_match}


def evaluate_run(root, split, run_dir, *, sample_ids=None, summaries=None):
    if split != "train":
        raise ValueError("Chấm local chỉ dùng train có gold; không tạo nhãn test.")
    predictions = {}
    for row in read_jsonl(run_dir / "submission.jsonl"):
        if row["id"] in predictions:
            raise ValueError("Submission trùng ID.")
        predictions[row["id"]] = row
    if not predictions:
        raise ValueError("Submission rỗng.")
    if sample_ids is None:
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        sample_ids = metadata["sample_ids"]
    if set(predictions) != set(sample_ids):
        raise ValueError("Submission chưa đủ hoặc sai ID trong phạm vi run; không thu nhỏ N khi chấm.")
    if summaries is None:
        summaries = {r["id"]: r for r in read_jsonl(run_dir / "samples.jsonl")}
    catalog = json.loads((root / split / f"{split}_tools_catalog.json").read_text(encoding="utf-8"))
    tools = {t["name"]: t for app in catalog["apps"] for t in app["tools"]}
    details = []
    total = 0
    for item in read_jsonl(root / split / f"{split}.jsonl"):
        total += 1
        if item["id"] not in predictions:
            continue
        gold = item["label"]["tool_calls"]
        # Đây là verifier riêng sau inference, không đưa gold về agent.
        gold_env = create_env(root, split, item["id"])
        for call in gold:
            if not gold_env.call(call["name"], call.get("arguments", {})).get("ok"):
                raise ValueError(f"Gold bị SDK từ chối: {item['id']}")
        gold_hash = gold_env.get_state_hash()
        prediction = predictions[item["id"]]
        replay = create_env(root, split, item["id"])
        valid = [bool(replay.call(c["name"], c.get("arguments", {})).get("ok"))
                 for c in prediction["tool_calls"]]
        reproduced = replay.get_state_hash() == prediction["state_hash"]
        result = score_calls(prediction["tool_calls"], gold,
                             prediction["state_hash"] == gold_hash, tools, valid)
        replay_metric = score_calls(prediction["tool_calls"], gold,
                                    replay.get_state_hash() == gold_hash, tools, valid)
        summary = summaries[item["id"]]
        details.append({"id": item["id"], **result,
                        "replay_metric": replay_metric,
                        "hash_reproduced": reproduced,
                        "runtime_status": summary["status"],
                        "elapsed_seconds": summary["elapsed_seconds"],
                        "reference_calls": gold,
                        "submitted_calls": prediction["tool_calls"]})
    if len(details) != len(predictions):
        raise ValueError("Submission chứa ID ngoài train.")
    report = {
        "metric": "State-gated tool-call F1 (local)",
        "score_0_to_100": 100 * sum(d["score"] for d in details) / len(details),
        "replay_score_0_to_100": 100 * sum(d["replay_metric"]["score"] for d in details) / len(details),
        "evaluated_samples": len(details), "split_samples": total,
        "scope": "full_split" if len(details) == total else "subset",
        "state_matches": sum(d["state_match"] for d in details),
        "hash_reproduced": sum(d["hash_reproduced"] for d in details),
        "official_evaluator_parity": "not verified",
        "matching_assumptions": [
            "Lowercase + Unicode NFC + whitespace multiset token-F1",
            "Fuzzy threshold strictly > 0.6; no accent/punctuation stripping",
            "Exact argument key-set; array order retained",
            "Maximum one-to-one matching; rejected calls cannot match",
            "Submitted-hash metric, replay-hash metric and hash integrity reported separately",
        ],
        "details": details,
    }
    (run_dir / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def verify_run(root, split, run_dir):
    """Kiểm tra coverage và SDK replay cho split không có gold; không tạo điểm."""
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    expected = metadata["sample_ids"]
    rows = list(read_jsonl(run_dir / "submission.jsonl"))
    ids = [r["id"] for r in rows]
    if ids != expected or len(set(ids)) != len(ids):
        raise ValueError("Submission thiếu, trùng hoặc lệch thứ tự ID của run.")
    hashes, rejected = [], []
    for row in rows:
        if set(row) != {"id", "tool_calls", "state_hash"}:
            raise ValueError(f"Sai trường submission: {row['id']}")
        env = create_env(root, split, row["id"])
        for i, call in enumerate(row["tool_calls"]):
            result = env.call(call["name"], call.get("arguments", {}))
            if not result.get("ok"):
                rejected.append({"id": row["id"], "index": i, "error": result.get("error")})
        if env.get_state_hash() != row["state_hash"]:
            hashes.append(row["id"])
    report = {
        "split": split, "rows": len(rows), "split_samples": metadata["split_samples"],
        "complete_split": metadata["is_complete_split"],
        "hash_reproduced": len(rows) - len(hashes), "hash_mismatch_ids": hashes,
        "schema_rejected_calls": rejected,
        "score": None, "score_note": "Không có gold; không tính điểm local.",
    }
    (run_dir / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
