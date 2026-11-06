import argparse
import copy
import gc
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# None: chỉ chạy train_0004; số nguyên dương: chạy N mẫu đầu của train.
TRAIN_SAMPLES = None
CONTEXT_TOKENS = 16384

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "train+public_test"
MODELS = Path(sys.executable).resolve().parents[2] / "models"
LLM_DIR = MODELS / "LFM3-1.7B" / "ac2586a34f1a1c03329dbdcdefabd8b6478ddaa7"
ASR_DIR = MODELS / "gipformer1.5-68M-rnnt"
ASR_RUNTIME = MODELS.parent / "asr-cuda"
sys.path.insert(0, str(DATA / "train"))
from zaic_tools import ToolEnv, state_hash


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


class Models:
    def __init__(self, source, transcripts=None):
        self.source = source
        self.transcripts = transcripts
        self.model = None
        self.tokenizer = None

    def transcribe(self, item):
        if self.source == "reference":
            return item["audio_text"]
        return self.transcripts[item["audio"]]

    def generate(self, messages, tools, max_tokens):
        if self.model is None:
            self.tokenizer = AutoTokenizer.from_pretrained(LLM_DIR, trust_remote_code=True, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                LLM_DIR, trust_remote_code=True, local_files_only=True,
                dtype=torch.float16, device_map={"": "cuda:0"},
            )
            self.model.eval()
        inputs = self.tokenizer.apply_chat_template(
            messages, tools=tools, tokenize=True, add_generation_prompt=True,
            enable_thinking=False, return_dict=True, return_tensors="pt",
        ).to("cuda")
        count_in = inputs["input_ids"].shape[1]
        remaining = CONTEXT_TOKENS - count_in
        if remaining <= 0:
            return "", count_in, 0, True
        budget = min(remaining, max_tokens) if max_tokens is not None else remaining
        with torch.inference_mode():
            output = self.model.generate(**inputs, do_sample=False, max_new_tokens=budget)
        generated = output[0, count_in:]
        text = self.tokenizer.decode(generated, skip_special_tokens=True)
        truncated = len(generated) >= budget and generated[-1].item() != self.tokenizer.eos_token_id
        return text, count_in, len(generated), truncated

    def close(self):
        self.model = self.tokenizer = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print(f"PyTorch còn cấp phát: {torch.cuda.memory_allocated() / 1024**3:.2f} GiB")


def asr_worker(request_path, output_path):
    """Chạy ASR trong tiến trình riêng; khi thoát CUDA context được giải phóng."""
    if not ASR_RUNTIME.is_dir():
        raise FileNotFoundError(f"Không tìm thấy runtime CUDA: {ASR_RUNTIME}")
    sys.path.insert(0, str(ASR_RUNTIME))
    import sherpa_onnx
    import soundfile as sf

    if not Path(sherpa_onnx.__file__).resolve().is_relative_to(ASR_RUNTIME.resolve()):
        raise RuntimeError(f"Không nạp được sherpa-onnx CUDA từ {ASR_RUNTIME}")

    model_dir = ASR_DIR / "fp16"
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(model_dir / "encoder.onnx"), decoder=str(model_dir / "decoder.onnx"),
        joiner=str(model_dir / "joiner.onnx"), tokens=str(ASR_DIR / "tokens.txt"),
        num_threads=4, sample_rate=16000, feature_dim=80,
        decoding_method="greedy_search", provider="cuda",
    )
    transcripts = {}
    paths = json.loads(Path(request_path).read_text(encoding="utf-8"))
    for index, audio in enumerate(paths, 1):
        samples, rate = sf.read(str(DATA / "train" / audio), dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        stream = recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        recognizer.decode_stream(stream)
        transcripts[audio] = stream.result.text.strip()
        print(f"  ASR {index}/{len(paths)}: {audio} -> {transcripts[audio]}", flush=True)
    Path(output_path).write_text(json.dumps(transcripts, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_transcripts(samples, run_dir):
    paths = list(dict.fromkeys(
        turn["audio"] for sample in samples
        for turn in (*sample.get("history", []), sample) if turn.get("role", "user") == "user"
    ))
    request_path = run_dir / "asr_audio.json"
    output_path = run_dir / "asr_transcripts.json"
    request_path.write_text(dumps(paths), encoding="utf-8")
    print(f"Giai đoạn ASR FP16 trên GPU: {len(paths)} file audio", flush=True)
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--asr-worker", str(request_path), str(output_path)], check=True)
    print("ASR đã hoàn thành và giải phóng tiến trình GPU. Bắt đầu LLM.", flush=True)
    return json.loads(output_path.read_text(encoding="utf-8"))


def parse_tool_calls(text, specs):
    if "</think>" in text:
        thinking, content = text.split("</think>", 1)
        thinking = thinking.removeprefix("<think>")
    else:
        thinking, content = None, text
    if "<think>" in content:
        raise ValueError("Thinking chưa đóng")
    pattern = r"<tool_call>\s*<function=([^>\s]+)>\s*(.*?)\s*</function>\s*</tool_call>"
    matches = list(re.finditer(pattern, content, re.DOTALL))
    remaining = re.sub(pattern, "", content, flags=re.DOTALL)
    if "<tool_call>" in remaining or "</tool_call>" in remaining:
        raise ValueError("Tool call không đúng định dạng LFM3")
    calls = []
    for match in matches:
        name, body = match.group(1), match.group(2)
        param_pattern = r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>"
        params = list(re.finditer(param_pattern, body, re.DOTALL))
        if re.sub(param_pattern, "", body, flags=re.DOTALL).strip():
            raise ValueError(f"Tham số của {name} không đúng định dạng")
        properties = specs.get(name, {}).get("parameters", {}).get("properties", {})
        arguments = {}
        for param in params:
            key, value = param.group(1), param.group(2).strip()
            if key in arguments:
                raise ValueError(f"Tham số {key} xuất hiện nhiều lần")
            arguments[key] = value if properties.get(key, {}).get("type") == "string" or key not in properties else json.loads(value)
        calls.append({"name": name, "arguments": arguments})
    return thinking, remaining.strip(), calls


def run_sample(sample, catalog, models, max_turns, max_tokens, stop_on_repeated_calls=None):
    allowed = {name for app in sample["context"]["installed_apps"].values() for name in app["tools"]}
    allowed.add("sys.ask_missing_info")
    specs = {tool["name"]: tool for app in catalog["apps"] for tool in app["tools"] if tool["name"] in allowed}
    tools = [{"type": "function", "function": {k: spec[k] for k in ("name", "description", "parameters")}} for spec in specs.values()]
    env = ToolEnv("train", sample["id"], root=DATA)
    initial_state = env.get_state()
    messages = [{
        "role": "system",
        "content": (
            "Bạn là trợ lý điều khiển thiết bị và dịch vụ qua công cụ. Tuân thủ nghiêm ngặt các quy tắc sau:\n"
            "1. Chỉ dùng thông tin từ context, history và kết quả trả về của các công cụ. Tuyệt đối không suy diễn dữ liệu ngoài các nguồn này.\n"
            "2. Khi thiếu thông tin để thực hiện, ưu tiên dùng công cụ tra cứu liên quan. Chỉ gọi sys.ask_missing_info khi không có công cụ tra cứu hoặc tra cứu không xác định được.\n"
            "3. Không gọi lại cùng một công cụ với cùng bộ tham số nếu công cụ đó đã trả về kết quả ở lượt trước.\n"
            "4. Với yêu cầu ngoài phạm vi công cụ, phản hồi trực tiếp cho người dùng, không gọi tool."
        ),
    }]
    history = []
    for turn in sample.get("history", []):
        if turn["role"] == "user":
            text = models.transcribe(turn)
            history.append({"role": "user", "text": text})
        else:
            history.append({k: turn[k] for k in ("role", "text", "tool_calls", "tool_results") if k in turn})
    request_text = models.transcribe(sample)
    payload = {"request": request_text, "context": sample["context"]}
    if history:
        payload["history"] = history
    messages.append({"role": "user", "content": dumps(payload)})
    trace = []
    stop_reason = None
    turn = 0
    while max_turns is None or turn < max_turns:
        turn += 1
        print(f"  Lượt {turn}: đang sinh phản hồi...", flush=True)
        raw, count_in, count_out, truncated = models.generate(messages, tools, max_tokens)
        entry = {"turn": turn, "input_tokens": count_in, "output_tokens": count_out, "model_output": raw, "tool_calls": [], "tool_results": []}
        trace.append(entry)
        if truncated:
            stop_reason = "đạt giới hạn context 16384 token" if count_in + count_out >= CONTEXT_TOKENS else "output bị cắt do đạt giới hạn token tùy chọn"
            break
        try:
            thinking, content, calls = parse_tool_calls(raw, specs)
        except ValueError as error:
            stop_reason = f"không đọc được output: {error}"
            break
        if not calls:
            stop_reason = "model kết thúc mà không gọi thêm tool"
            break
        assistant_calls = [{"id": f"call_{turn}_{i}", "type": "function", "function": call} for i, call in enumerate(calls, 1)]
        assistant = {"role": "assistant", "content": content, "tool_calls": assistant_calls}
        if thinking is not None:
            assistant["reasoning_content"] = thinking
        messages.append(assistant)
        for call, formatted in zip(calls, assistant_calls):
            result = env.call(call["name"], call["arguments"])
            print(f"  Tool: {dumps(call)} | ok={result.get('ok')}", flush=True)
            entry["tool_calls"].append(call)
            entry["tool_results"].append(result)
            messages.append({"role": "tool", "tool_call_id": formatted["id"], "content": dumps(result)})
            calls_so_far = env.get_tool_calls() if stop_on_repeated_calls else []
            if stop_on_repeated_calls and len(calls_so_far) >= stop_on_repeated_calls and all(
                previous == call for previous in calls_so_far[-stop_on_repeated_calls:]
            ):
                stop_reason = f"dừng theo yêu cầu: {stop_on_repeated_calls} tool call giống nhau liên tiếp"
                break
            if call["name"] == "sys.ask_missing_info":
                stop_reason = "model yêu cầu thêm thông tin"
                break
        if stop_reason is not None:
            break
    if stop_reason is None:
        stop_reason = "đạt giới hạn lượt tùy chọn"
    submission = {"id": sample["id"], "tool_calls": env.get_tool_calls(), "state_hash": env.get_state_hash()}
    gold_state = copy.deepcopy(initial_state)
    gold_state.update(sample["label"]["final_state"])
    comparison = {
        "state_hash_matches": submission["state_hash"] == state_hash(gold_state),
        "tool_calls_exact_ordered": submission["tool_calls"] == sample["label"]["tool_calls"],
        "expected_tool_calls": sample["label"]["tool_calls"],
    }
    return {"sample_id": sample["id"], "input_source": models.source,
            "precision": {"asr": "fp16 (float32 I/O)" if models.source == "asr" else None, "llm": "float16"},
            "request_text": request_text,
            "reference_text": sample["audio_text"], "history": history, "stop_reason": stop_reason,
            "trace": trace, "submission": submission, "comparison": comparison}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Chạy sandbox LifeMate trên tập train (không train model).")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ids", nargs="+", help="Các sample id cần chạy, mặc định train_0004")
    selection.add_argument("--all", action="store_true", help="Chạy toàn bộ tập train")
    parser.add_argument("--limit", type=int, help="Chạy tối đa N mẫu theo thứ tự dữ liệu; nếu không chọn ID thì lấy từ đầu tập train")
    parser.add_argument("--input", choices=("asr", "reference"), default="asr", help="Nguồn transcript (mặc định: asr)")
    parser.add_argument("--max-turns", type=int, help="Giới hạn lượt tùy chọn; mặc định không giới hạn riêng")
    parser.add_argument("--max-tokens", type=int, help="Giới hạn token sinh mỗi lượt tùy chọn; mặc định dùng context còn lại")
    args = parser.parse_args()
    if args.limit is None and not args.ids and not args.all:
        args.limit = TRAIN_SAMPLES
    if any(value is not None and value < 1 for value in (args.limit, args.max_turns, args.max_tokens)):
        parser.error("--limit, --max-turns và --max-tokens phải lớn hơn 0")
    ids = set(args.ids) if args.ids else (None if args.all or args.limit else {"train_0004"})
    with (DATA / "train" / "train.jsonl").open(encoding="utf-8") as f:
        samples = [sample for line in f if line.strip() and (sample := json.loads(line)) and (ids is None or sample["id"] in ids)]
    if ids and ids - {sample["id"] for sample in samples}:
        parser.error(f"Không tìm thấy mẫu: {', '.join(sorted(ids - {sample['id'] for sample in samples}))}")
    if args.limit:
        samples = samples[:args.limit]
    catalog = json.loads((DATA / "train" / "train_tools_catalog.json").read_text(encoding="utf-8"))
    run_dir = ROOT / "sandbox_runs" / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True)
    print(f"Số mẫu: {len(samples)} | Nguồn: {args.input} | Kết quả: {run_dir}", flush=True)
    transcripts = prepare_transcripts(samples, run_dir) if args.input == "asr" else None
    models = Models(args.input, transcripts)
    results = []
    try:
        with (run_dir / "submission.jsonl").open("w", encoding="utf-8") as f:
            for sample in samples:
                print(f"\nĐang chạy {sample['id']}...", flush=True)
                result = run_sample(sample, catalog, models, args.max_turns, args.max_tokens)
                (run_dir / f"{sample['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                f.write(dumps(result["submission"]) + "\n")
                f.flush()
                results.append(result)
                print(f"{sample['id']}: {dumps(result['comparison'])}", flush=True)
    finally:
        models.close()
    print(f"\nĐã chạy {len(results)} mẫu. Trace và submission: {run_dir}")
    print("So khớp state:", sum(r["comparison"]["state_hash_matches"] for r in results), "/", len(results))
    print("So khớp chính xác tool call:", sum(r["comparison"]["tool_calls_exact_ordered"] for r in results), "/", len(results))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--asr-worker":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        asr_worker(sys.argv[2], sys.argv[3])
    else:
        main()
