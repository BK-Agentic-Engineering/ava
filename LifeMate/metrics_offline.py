"""Đánh giá PSS, DDR, STLE và SVR offline; không cập nhật trọng số."""

import gc
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

import sandbox


class MetricModels(sandbox.Models):
    def __init__(self, source, transcripts, variant, target_names):
        super().__init__(source, transcripts)
        self.variant = variant
        self.target_names = target_names
        self.entropy_turns = []

    def generate(self, messages, tools, max_tokens):
        if self.variant == "reverse":
            tools = list(reversed(tools))
        elif self.variant == "target":
            tools = [tool for tool in tools if tool["function"]["name"] in self.target_names]
        if self.model is None:
            self.tokenizer = AutoTokenizer.from_pretrained(sandbox.LLM_DIR, trust_remote_code=True, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                sandbox.LLM_DIR, trust_remote_code=True, local_files_only=True,
                dtype=torch.float16, device_map={"": "cuda:0"},
            )
            self.model.eval()
        inputs = self.tokenizer.apply_chat_template(
            messages, tools=tools, tokenize=True, add_generation_prompt=True,
            enable_thinking=False, return_dict=True, return_tensors="pt",
        ).to("cuda")
        count_in = inputs["input_ids"].shape[1]
        budget = sandbox.CONTEXT_TOKENS - count_in
        if budget <= 0:
            return "", count_in, 0, True
        entropies = []

        def collect_logits(module, args, output):
            logits = output[0, -1].float()
            log_probs = logits.log_softmax(dim=-1)
            entropies.append(-(log_probs.exp() * log_probs).sum().item())

        handle = self.model.get_output_embeddings().register_forward_hook(collect_logits)
        try:
            with torch.inference_mode():
                output = self.model.generate(**inputs, do_sample=False, max_new_tokens=budget)
        finally:
            handle.remove()
        generated = output[0, count_in:]
        ids = generated.tolist()
        raw = self.tokenizer.decode(ids, skip_special_tokens=True)
        truncated = len(ids) >= budget and ids[-1] != self.tokenizer.eos_token_id
        if len(ids) != len(entropies):
            raise RuntimeError(f"Không khớp logits/token: {len(entropies)} / {len(ids)}")
        spans = []
        for call in re.finditer(r"<tool_call>.*?</tool_call>", raw, re.DOTALL):
            block = call.group()
            for pattern in (r"<function=([^>]+)>", r"<parameter=([^>]+)>", r"<parameter=[^>]+>\s*(.*?)\s*</parameter>"):
                spans.extend((call.start() + m.start(1), call.start() + m.end(1)) for m in re.finditer(pattern, block, re.DOTALL))
        selected = []
        previous_end = 0
        pending = []
        for index, entropy in enumerate(entropies):
            current = self.tokenizer.decode(ids[:index + 1], skip_special_tokens=True)
            end = 0
            while end < min(len(current), len(raw)) and current[end] == raw[end]:
                end += 1
            if end < previous_end:
                raise ValueError("Không ánh xạ được token vào output")
            pending.append(entropy)
            if end > previous_end:
                if any(previous_end < span_end and end > start for start, span_end in spans):
                    selected.extend(pending)
                pending = []
                previous_end = end
        self.entropy_turns.append({"semantic_tokens": len(selected), "entropy_nats": sum(selected) / len(selected) if selected else None})
        return raw, count_in, len(ids), truncated


def first_call(result):
    calls = result["submission"]["tool_calls"]
    return calls[0] if calls else None


def validity(sample, catalog, result):
    env = sandbox.ToolEnv("train", sample["id"], root=sandbox.DATA)
    specs = {tool["name"]: tool for app in catalog["apps"] for tool in app["tools"]}
    checks = []
    for call in result["submission"]["tool_calls"]:
        official = env.validate(call["name"], call["arguments"])
        properties = specs.get(call["name"], {}).get("parameters", {}).get("properties", {})
        unknown = sorted(set(call["arguments"]) - set(properties))
        checks.append({"call": call, "runtime_valid": official["ok"], "error": official.get("error"),
                       "unknown_arguments": unknown, "strict_valid": official["ok"] and not unknown})
    return checks


def main():
    if hasattr(sandbox.sys.stdout, "reconfigure"):
        sandbox.sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sample_ids = ["train_0004", "train_0003", "train_0008", "train_0019", "train_0048"]
    with (sandbox.DATA / "train/train.jsonl").open(encoding="utf-8") as f:
        indexed = {s["id"]: s for line in f if (s := json.loads(line))["id"] in sample_ids}
    samples = [indexed[sample_id] for sample_id in sample_ids]
    catalog = json.loads((sandbox.DATA / "train/train_tools_catalog.json").read_text(encoding="utf-8"))
    out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else sandbox.ROOT / "metric_runs" / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    out_dir.mkdir(parents=True, exist_ok=True)
    print("Kết quả:", out_dir, flush=True)
    transcripts_file = out_dir / "asr_transcripts.json"
    transcripts = json.loads(transcripts_file.read_text(encoding="utf-8")) if transcripts_file.exists() else sandbox.prepare_transcripts(samples, out_dir)
    results = {}
    models = MetricModels("asr", transcripts, "full", set())
    try:
        for sample in samples:
            results[sample["id"]] = {}
            models.target_names = {call["name"] for call in sample["label"]["tool_calls"]}
            for variant in ("full", "reverse", "target"):
                existing = out_dir / f"{sample['id']}_{variant}.json"
                if existing.is_file():
                    results[sample["id"]][variant] = json.loads(existing.read_text(encoding="utf-8"))
                    continue
                print(f"\nMẫu {sample['id']} | Điều kiện: {variant}", flush=True)
                models.variant = variant
                models.entropy_turns = []
                repeated_limit = 3 if sample["id"] == "train_0008" and variant == "full" else None
                result = sandbox.run_sample(sample, catalog, models, None, None, stop_on_repeated_calls=repeated_limit)
                result["entropy_turns"] = models.entropy_turns
                result["schema_checks"] = validity(sample, catalog, result)
                existing.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                results[sample["id"]][variant] = result
    finally:
        models.close()
        gc.collect()
    records = []
    for sample in samples:
        variants = results[sample["id"]]
        gold = sample["label"]["tool_calls"]
        expected = gold[0] if gold else None
        base = first_call(variants["full"])
        records.append({"sample_id": sample["id"], "gold_first": expected,
                        "first_calls": {v: first_call(variants[v]) for v in variants},
                        "first_correct": {v: first_call(variants[v]) == expected for v in variants},
                        "state_matches": {v: variants[v]["comparison"]["state_hash_matches"] for v in variants},
                        "stop_reasons": {v: variants[v]["stop_reason"] for v in variants},
                        "stable_reverse": first_call(variants["reverse"]) == base})
    applicable = [r for r in records if r["gold_first"] is not None]
    n = len(applicable)
    full_acc = sum(r["first_correct"]["full"] for r in applicable) / n if n else None
    target_acc = sum(r["first_correct"]["target"] for r in applicable) / n if n else None
    pss = sum(r["first_correct"][v] and (v == "full" or r["stable_reverse"]) for r in applicable for v in ("full", "reverse")) / (2 * n) if n else None
    schema_stats = {}
    entropy_stats = {}
    for variant in ("full", "reverse", "target"):
        group = [results[s["id"]][variant] for s in samples]
        checks = [c for result in group for c in result["schema_checks"]]
        entropy = [e for result in group for e in result["entropy_turns"] if e["semantic_tokens"]]
        token_count = sum(e["semantic_tokens"] for e in entropy)
        schema_stats[variant] = {"calls": len(checks), "runtime_invalid": sum(not c["runtime_valid"] for c in checks),
                                 "strict_invalid": sum(not c["strict_valid"] for c in checks),
                                 "runtime_svr": sum(not c["runtime_valid"] for c in checks) / len(checks) if checks else None,
                                 "strict_svr": sum(not c["strict_valid"] for c in checks) / len(checks) if checks else None,
                                 "parse_failures": sum(r["stop_reason"].startswith("không đọc được output") for r in group)}
        entropy_stats[variant] = {"semantic_tokens": token_count,
                                  "entropy_nats": sum(e["entropy_nats"] * e["semantic_tokens"] for e in entropy) / token_count if token_count else None,
                                  "turns_with_calls": len(entropy)}
    summary = {"sample_ids": sample_ids, "task": "first_tool_call_exact", "permutations": ["full", "reverse"],
               "tool_target_sample_count": n, "PSS_correct_and_stable": pss, "reverse_first_call_stability": sum(r["stable_reverse"] for r in applicable) / n if n else None,
               "DDR": 1 - full_acc / target_acc if target_acc else None, "target_accuracy": target_acc, "full_accuracy": full_acc,
               "STLE_by_condition": entropy_stats, "SVR_by_condition": schema_stats, "samples": records,
               "note": "Năm mẫu chọn có chủ đích; PSS/DDR loại mẫu không có gold tool, mẫu đó báo riêng. target dùng tool từ nhãn chỉ cho thử nghiệm offline; context giữ nguyên. SVR strict cộng trường không có trong schema; parse failures báo riêng."}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
