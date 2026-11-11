import argparse
import copy
import gc
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.request

from transformers import AutoTokenizer

CONTEXT_TOKENS = 16384

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "train+public_test"
MODELS = Path("C:/HCMUT/Projects/ZaloAiChallenge/models")
LLM_DIR = MODELS / "LFM3-1.7B" / "ac2586a34f1a1c03329dbdcdefabd8b6478ddaa7"
ASR_DIR = MODELS / "gipformer1.5-68M-rnnt"
ASR_RUNTIME = MODELS.parent / "asr-cuda"
GGUF_MODEL = MODELS / "LFM3-1.7B-GGUF" / "cd0c74c575b5c416f3011b5b4c298077f26ca8c2" / "LFM3-1.7B-F16.gguf"
LLAMA_SERVER = MODELS / "llama.cpp" / "llama-server.exe"
sys.path.insert(0, str(DATA / "train"))
from zaic_tools import ToolEnv, state_hash


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


class Models:
    def __init__(self, source, transcripts=None, *, llm_dir=LLM_DIR, context_tokens=CONTEXT_TOKENS,
                 prefill_chunk_size=512, enable_thinking=False, gguf_model=None,
                 server_binary=None, output_dir=None, shard=0, port=8080,
                 enable_prefix_caching=True, backend=None):
        self.source = source
        self.transcripts = transcripts
        self.llm_dir = llm_dir
        self.context_tokens = context_tokens
        self.prefill_chunk_size = prefill_chunk_size
        self.enable_thinking = enable_thinking
        self.gguf_model = Path(gguf_model) if gguf_model else None
        self.server_binary = Path(server_binary) if server_binary else None
        self.output_dir = Path(output_dir or ROOT / "sandbox_runs")
        self.shard = shard
        self.port = port
        self.enable_prefix_caching = enable_prefix_caching
        self.backend = backend or ("llama.cpp" if self.gguf_model or self.server_binary else "transformers")
        self.base_url = f"http://127.0.0.1:{port}"
        self.model = None
        self.tokenizer = None
        self.server_log = None
        self.turn_timings = []
        self.backend_timings = []
        self.load_seconds = 0.0
        self.generation_config = {
            "backend": self.backend, "temperature": 0.0, "top_k": 0,
            "top_p": 1.0, "min_p": 0.0, "repeat_penalty": 1.1,
            "repeat_last_n": context_tokens, "cache_prompt": enable_prefix_caching,
            "dtype": "float16", "enable_thinking": enable_thinking,
        }

    def request(self, endpoint, payload=None, timeout=1800):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.base_url + endpoint, data=data,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def transcribe(self, item):
        if self.source == "reference":
            return item["audio_text"]
        return self.transcripts[item["audio"]]

    def generate(self, messages, tools, max_tokens):
        text, count_in, ids, truncated = self.generate_tokens(messages, tools, max_tokens)
        return text, count_in, len(ids), truncated

    def generate_tokens(self, messages, tools, max_tokens):
        if self.backend == "llama.cpp":
            return self._generate_llama_cpp(messages, tools, max_tokens)
        return self._generate_transformers(messages, tools, max_tokens)

    def _load_tokenizer(self):
        if self.tokenizer is None:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.llm_dir, trust_remote_code=True, local_files_only=True)

    def _generate_llama_cpp(self, messages, tools, max_tokens):
        if self.model is None:
            if not self.gguf_model or not self.gguf_model.is_file():
                raise FileNotFoundError(f"Không tìm thấy GGUF LFM3: {self.gguf_model or GGUF_MODEL}; dùng --gguf-model")
            if not self.server_binary or not self.server_binary.is_file():
                raise FileNotFoundError(f"Không tìm thấy llama-server: {self.server_binary or LLAMA_SERVER}; dùng --llama-server")
            self._load_tokenizer()
            self.output_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.output_dir / f"llama_server_gpu{self.shard}.log"
            self.server_log = log_path.open("w", encoding="utf-8")
            command = [str(self.server_binary), "--model", str(self.gguf_model),
                       "--host", "127.0.0.1", "--port", str(self.port),
                       "--ctx-size", str(self.context_tokens), "--parallel", "1",
                       "--n-gpu-layers", "999", "--threads", "2",
                       "--batch-size", str(self.prefill_chunk_size),
                       "--ubatch-size", str(self.prefill_chunk_size)]
            started = time.perf_counter()
            self.model = subprocess.Popen(command, stdout=self.server_log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 300
            while True:
                if self.model.poll() is not None:
                    detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                    raise RuntimeError(f"llama-server exit {self.model.returncode}: {detail}")
                try:
                    self.request("/health", timeout=2)
                    break
                except urllib.error.URLError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"llama-server chưa sẵn sàng. Xem {log_path}")
                    time.sleep(0.25)
            self.load_seconds = time.perf_counter() - started
            print(f"llama.cpp nạp model và khởi tạo server: {self.load_seconds:.2f}s", flush=True)

        inputs = self.tokenizer.apply_chat_template(
            messages, tools=tools, tokenize=True, add_generation_prompt=True,
            enable_thinking=self.enable_thinking, return_dict=True,
        )
        prompt_ids = inputs["input_ids"]
        if hasattr(prompt_ids, "tolist"):
            prompt_ids = prompt_ids.tolist()
        if prompt_ids and isinstance(prompt_ids[0], list):
            prompt_ids = prompt_ids[0]
        count_in = len(prompt_ids)
        remaining = self.context_tokens - count_in
        if remaining <= 0:
            self.turn_timings.append(0.0)
            self.backend_timings.append({})
            return "", count_in, [], True
        budget = min(remaining, max_tokens) if max_tokens is not None else remaining
        payload = {"prompt": prompt_ids, "n_predict": budget, "temperature": 0.0,
                   "top_k": 0, "top_p": 1.0, "min_p": 0.0, "typical_p": 1.0,
                   "repeat_penalty": 1.1, "repeat_last_n": self.context_tokens,
                   "cache_prompt": self.enable_prefix_caching, "return_tokens": True, "stream": False}
        started = time.perf_counter()
        try:
            result = self.request("/completion", payload)
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode("utf-8", errors="replace")) from error
        self.turn_timings.append(time.perf_counter() - started)
        self.backend_timings.append(result.get("timings", {}))
        generated = result["tokens"]
        text = self.tokenizer.decode(generated, skip_special_tokens=True)
        truncated = result["stop_type"] == "limit" or result.get("truncated", False)
        return text, count_in, generated, truncated

    def _generate_transformers(self, messages, tools, max_tokens):
        import torch
        from transformers import AutoModelForCausalLM

        if self.model is None:
            self._load_tokenizer()
            self.model = AutoModelForCausalLM.from_pretrained(
                self.llm_dir, trust_remote_code=True, local_files_only=True,
                dtype=torch.float16, device_map={"": "cuda:0"},
            )
            self.model.eval()
        inputs = self.tokenizer.apply_chat_template(
            messages, tools=tools, tokenize=True, add_generation_prompt=True,
            enable_thinking=self.enable_thinking, return_dict=True, return_tensors="pt",
        ).to("cuda")
        count_in = inputs["input_ids"].shape[1]
        remaining = self.context_tokens - count_in
        if remaining <= 0:
            return "", count_in, [], True
        budget = min(remaining, max_tokens) if max_tokens is not None else remaining
        with torch.inference_mode():
            output = self.model.generate(**inputs, do_sample=False, max_new_tokens=budget)
        generated = output[0, count_in:].tolist()
        text = self.tokenizer.decode(generated, skip_special_tokens=True)
        eos = self.model.generation_config.eos_token_id
        if not isinstance(eos, (list, tuple)):
            eos = [self.tokenizer.eos_token_id if eos is None else eos]
        truncated = len(generated) >= budget and generated[-1] not in eos
        return text, count_in, generated, truncated

    def close(self):
        if self.backend == "llama.cpp":
            if self.model is not None and self.model.poll() is None:
                self.model.terminate()
                try:
                    self.model.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.model.kill()
                    self.model.wait()
            if self.server_log is not None:
                self.server_log.close()
        else:
            import torch
            self.model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                print(f"PyTorch còn cấp phát: {torch.cuda.memory_allocated() / 1024**3:.2f} GiB")
        self.model = self.tokenizer = None


def asr_worker(request_path, output_path):
    """Chạy ASR trong tiến trình riêng; khi thoát CUDA context được giải phóng."""
    if not ASR_RUNTIME.is_dir():
        raise FileNotFoundError(f"Không tìm thấy runtime CUDA: {ASR_RUNTIME}")
    sys.path.insert(0, str(ASR_RUNTIME))
    import sherpa_onnx
    import soundfile as sf

    if not Path(sherpa_onnx.__file__).resolve().is_relative_to(ASR_RUNTIME.resolve()):
        raise RuntimeError(f"Không nạp được sherpa-onnx CUDA từ {ASR_RUNTIME}")

    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(ASR_DIR / "encoder.onnx"), decoder=str(ASR_DIR / "decoder.onnx"),
        joiner=str(ASR_DIR / "joiner.onnx"), tokens=str(ASR_DIR / "tokens.txt"),
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
    print(f"Giai đoạn ASR FP32 ONNX trên GPU: {len(paths)} file audio", flush=True)
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


def healing_feedback(call, spec, result):
    if result.get("ok") is False:
        if not spec:
            return "rejected", "Chọn một công cụ trong danh sách được cấp."
        return "rejected", "Sửa tham số theo lỗi và schema. Nếu thiếu dữ kiện, tra cứu trước hoặc hỏi thêm."
    if result.get("done") is False:
        return "not_done", "Kiểm tra nguyên nhân trong kết quả. Tra cứu hoặc sửa điều kiện trước khi thử lại."

    returns = spec.get("returns", "")
    if (spec.get("kind") == "read" and result.get("ok") is True
            and returns.endswith("[]") and result.get(returns[:-2]) == []):
        schema = spec["parameters"]
        required = set(schema.get("required", []))
        alternatives = {name for group in schema.get("x-one-of", []) for name in group}
        optional = [name for name, value in call["arguments"].items()
                    if name in schema["properties"] and name not in required | alternatives and value not in (None, "", [], {})]
        if optional:
            return "empty_read", (f"Kiểm tra {', '.join(optional)} hoặc tra cứu cách khác. "
                                  "Chỉ nới bộ lọc nếu vẫn giữ điều kiện của người dùng.")
    return None, None


def run_sample(sample, catalog, models, max_turns, max_tokens, stop_on_repeated_calls=None, *,
               system_prompt=None, self_heal=False, data_root=DATA):
    allowed = {name for app in sample["context"]["installed_apps"].values() for name in app["tools"]}
    allowed.add("sys.ask_missing_info")
    specs = {tool["name"]: tool for app in catalog["apps"] for tool in app["tools"] if tool["name"] in allowed}
    tools = [{"type": "function", "function": {k: spec[k] for k in ("name", "description", "parameters")}} for spec in specs.values()]
    env = ToolEnv("train", sample["id"], root=data_root)
    initial_state = env.get_state()
    current_state = initial_state
    previous_execution = None
    messages = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
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
        entry = {"turn": turn, "input_tokens": count_in, "output_tokens": count_out, "model_output": raw,
                 "tool_calls": [], "tool_results": [], "calls": []}
        trace.append(entry)
        if truncated:
            context_limit = getattr(models, "context_tokens", CONTEXT_TOKENS)
            stop_reason = (f"đạt giới hạn context {context_limit} token" if count_in + count_out >= context_limit
                           else "output bị cắt do đạt giới hạn token tùy chọn")
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
            spec = specs.get(call["name"], {})
            kind = spec.get("kind")
            repeated = (self_heal and previous_execution is not None
                        and json.dumps(previous_execution["call"], sort_keys=True) == json.dumps(call, sort_keys=True))
            blocked = (self_heal and kind == "write" and repeated
                       and previous_execution["heal_trigger"] in ("rejected", "not_done"))
            changes = {}
            if blocked:
                result = {"ok": False, "error": "Lệnh ghi trùng với lệnh vừa thất bại."}
                trigger = "repeated_failed_write"
                hint = "Sửa tham số hoặc tra cứu thông tin còn thiếu trước khi thử lại."
            else:
                result = env.call(call["name"], call["arguments"])
                after_state = env.get_state()
                changes = {app: {"before": current_state.get(app), "after": after_state.get(app)}
                           for app in sorted(current_state.keys() | after_state.keys())
                           if current_state.get(app) != after_state.get(app)}
                current_state = after_state
                entry["tool_calls"].append(call)
                entry["tool_results"].append(result)
                trigger, hint = healing_feedback(call, spec, result) if self_heal else (None, None)
                if (trigger is None and kind == "read" and repeated
                        and result == previous_execution["result"] and not changes):
                    trigger = "repeated_read"
                    hint = "Kết quả vẫn như lần trước. Dùng dữ liệu đã có để chọn bước tiếp theo."
            record = {"call": call, "kind": kind, "result": result, "blocked": blocked,
                      "state_changes": changes, "heal_trigger": trigger, "heal_hint": hint}
            entry["calls"].append(record)
            feedback = {"result": result, "hint": hint} if hint else result
            messages.append({"role": "tool", "tool_call_id": formatted["id"], "content": dumps(feedback)})
            print(f"  Tool: {dumps(call)} | ok={result.get('ok')} | blocked={blocked}", flush=True)
            if blocked:
                continue
            previous_execution = record
            calls_so_far = env.get_tool_calls() if stop_on_repeated_calls else []
            if stop_on_repeated_calls and len(calls_so_far) >= stop_on_repeated_calls and all(
                previous == call for previous in calls_so_far[-stop_on_repeated_calls:]
            ):
                stop_reason = f"dừng theo yêu cầu: {stop_on_repeated_calls} tool call giống nhau liên tiếp"
                break
            if call["name"] == "sys.ask_missing_info" and (not self_heal or result.get("waiting_for_user") is True):
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
            "precision": {"asr": "fp32 ONNX" if models.source == "asr" else None, "llm": "float16"},
            "request_text": request_text,
            "reference_text": sample["audio_text"], "history": history, "stop_reason": stop_reason,
            "self_heal": self_heal, "initial_state": initial_state,
            "trace": trace, "submission": submission, "comparison": comparison}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Chạy sandbox LifeMate trên tập train (không train model).")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ids", nargs="+", help="ID các mẫu cần chạy")
    selection.add_argument("--all", action="store_true", help="Chạy toàn bộ tập train")
    parser.add_argument("--limit", type=int, help="Chạy tối đa N mẫu theo thứ tự dữ liệu")
    parser.add_argument("--input", choices=("asr", "reference"), required=True, help="Nguồn transcript")
    parser.add_argument("--prompt", type=Path, help="File system prompt UTF-8 tùy chọn")
    parser.add_argument("--max-turns", type=int, help="Giới hạn lượt tùy chọn")
    parser.add_argument("--max-tokens", type=int, help="Giới hạn token sinh mỗi lượt tùy chọn")
    parser.add_argument("--self-heal", action="store_true", help="Thêm phản hồi sửa lỗi và chặn lặp lệnh ghi vừa thất bại")
    args = parser.parse_args()
    if args.limit is None and not (args.ids or args.all):
        parser.error("Chọn mẫu chạy bằng --ids, --limit hoặc --all")
    if any(value is not None and value < 1 for value in (args.limit, args.max_turns, args.max_tokens)):
        parser.error("--limit, --max-turns và --max-tokens phải lớn hơn 0")
    try:
        system_prompt = args.prompt.read_text(encoding="utf-8-sig") if args.prompt else None
    except (OSError, UnicodeError) as error:
        parser.error(f"Không đọc được system prompt {args.prompt}. {error}")
    ids = set(args.ids) if args.ids else None
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
                result = run_sample(sample, catalog, models, args.max_turns, args.max_tokens,
                                    system_prompt=system_prompt, self_heal=args.self_heal)
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
