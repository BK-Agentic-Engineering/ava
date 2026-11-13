"""Enhanced LifeMate sandbox cho train và chạy thử với ToolEnv."""

import argparse
import copy
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from modify_tool_description import normalize_catalog
from sandbox_baseline import Models
from self_healing import SelfHealer
from system_prompt import BASELINE, ENHANCED

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "train+public_test"
MODEL_ROOT = Path("C:/HCMUT/Projects/ZaloAiChallenge/models")
CONTEXT_TOKENS = 16384
sys.path.insert(0, str(DATA / "train"))
from zaic_tools import ToolEnv, state_hash


def tool_api(split, data_root):
    if split == "train" and (Path(data_root) / "train" / "zaic_tools").resolve() == (DATA / "train" / "zaic_tools").resolve():
        return ToolEnv, state_hash
    package = Path(data_root) / split / "zaic_tools" / "__init__.py"
    module_name = f"_lifemate_{split}_tools_{abs(hash(str(package.resolve())))}"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(
            module_name, package, submodule_search_locations=[str(package.parent)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module.ToolEnv, module.state_hash


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def parse_tool_calls(text, specs):
    """Tách LFM3 tool calls; giữ nguyên giá trị sai kiểu cho schema verifier."""
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
    if any(tag in remaining for tag in ("<tool_call", "</tool_call", "<function=", "</function>", "<parameter=", "</parameter>")):
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
            if key in properties and properties[key].get("type") != "string":
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            arguments[key] = value
        calls.append({"name": name, "arguments": arguments})
    return thinking, remaining.strip(), calls


def run_sample(sample, catalog, models, max_turns=20, max_tokens=None, *,
               system_prompt=ENHANCED, self_heal=True, enhanced_tools=True,
               data_root=DATA, split="train", tool_names=None):
    """Chạy một mẫu bằng đúng một ToolEnv; trace chỉ dùng cho đánh giá offline."""
    allowed = {name for app in sample["context"]["installed_apps"].values() for name in app["tools"]}
    allowed.add("sys.ask_missing_info")
    if tool_names is not None:
        allowed &= set(tool_names)
    effective_catalog = normalize_catalog(catalog, allowed) if enhanced_tools else catalog
    specs = {tool["name"]: tool for app in effective_catalog["apps"]
             for tool in app["tools"] if tool["name"] in allowed}
    tools = [{"type": "function", "function": {k: spec[k] for k in ("name", "description", "parameters")}}
             for spec in specs.values()]
    make_env, hash_state = tool_api(split, data_root)
    env = make_env(split, sample["id"], root=data_root)
    initial_state = env.get_state()
    current_state = initial_state
    healer = SelfHealer(specs)
    history = []
    for item in sample.get("history", []):
        if item["role"] == "user":
            history.append({"role": "user", "text": models.transcribe(item)})
        else:
            history.append({k: item[k] for k in ("role", "text", "tool_calls", "tool_results") if k in item})
    request_text = models.transcribe(sample)
    payload = {"request": request_text, "context": sample["context"]}
    if history:
        payload["history"] = history
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": dumps(payload)})

    trace = []
    stop_reason = None
    syntax_errors = 0
    for turn in range(1, max_turns + 1):
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
            syntax_errors += 1
            entry["parse_error"] = str(error)
            if not self_heal or syntax_errors > 1:
                stop_reason = f"không đọc được output: {error}"
                break
            hint = (f"Lỗi định dạng thẻ gọi công cụ ({error}). Sinh lại đúng cấu trúc "
                    "<tool_call><function=tên_hàm><parameter=tên_tham_số>giá_trị"
                    "</parameter></function></tool_call>.")
            entry["parse_hint"] = hint
            messages.extend([{"role": "assistant", "content": raw}, {"role": "user", "content": hint}])
            continue
        syntax_errors = 0
        if not calls:
            if self_heal and turn == 1 and turn < max_turns and any(name in content for name in specs):
                hint = ("Bạn vừa nhắc đến công cụ nhưng chưa gọi. Nếu cần dùng công cụ, "
                        "hãy sinh lời gọi theo cấu trúc <tool_call><function=tên_hàm>"
                        "<parameter=tên_tham_số>giá_trị</parameter></function></tool_call>.")
                entry["stop_trigger"] = "tool_name_without_call"
                entry["stop_hint"] = hint
                assistant = {"role": "assistant", "content": content}
                if thinking is not None:
                    assistant["reasoning_content"] = thinking
                messages.extend([assistant, {"role": "user", "content": hint}])
                continue
            stop_reason = "model kết thúc mà không gọi thêm tool"
            break
        assistant_calls = [{"id": f"call_{turn}_{i}", "type": "function", "function": call}
                           for i, call in enumerate(calls, 1)]
        assistant = {"role": "assistant", "content": content, "tool_calls": assistant_calls}
        if thinking is not None:
            assistant["reasoning_content"] = thinking
        messages.append(assistant)
        for call, formatted in zip(calls, assistant_calls):
            spec = specs.get(call["name"], {})
            trigger, hint = healer.precheck(env, call) if self_heal else (None, None)
            blocked = trigger is not None
            changes = {}
            if blocked:
                result = {"ok": False, "error": hint}
            else:
                result = env.call(call["name"], call["arguments"])
                after_state = env.get_state()
                changes = {app: {"before": current_state.get(app), "after": after_state.get(app)}
                           for app in sorted(current_state.keys() | after_state.keys())
                           if current_state.get(app) != after_state.get(app)}
                current_state = after_state
                entry["tool_calls"].append(call)
                entry["tool_results"].append(result)
                if self_heal:
                    trigger, hint = healer.observe(call, result, bool(changes))
            entry["calls"].append({"call": call, "kind": spec.get("kind"), "result": result,
                                   "blocked": blocked, "state_changes": changes,
                                   "heal_trigger": trigger, "heal_hint": hint})
            feedback = {"result": result, "hint": hint} if hint else result
            messages.append({"role": "tool", "tool_call_id": formatted["id"], "content": dumps(feedback)})
            if not blocked and call["name"] == "sys.ask_missing_info" and result.get("waiting_for_user") is True:
                stop_reason = "model yêu cầu thêm thông tin"
                break
        if stop_reason:
            break
    if stop_reason is None:
        stop_reason = "đạt giới hạn lượt tùy chọn"

    submission = {"id": sample["id"], "tool_calls": env.get_tool_calls(), "state_hash": env.get_state_hash()}
    comparison = None
    if "label" in sample:
        gold_state = copy.deepcopy(initial_state)
        gold_state.update(sample["label"]["final_state"])
        comparison = {"state_hash_matches": submission["state_hash"] == hash_state(gold_state),
                      "tool_calls_exact_ordered": submission["tool_calls"] == sample["label"]["tool_calls"],
                      "expected_tool_calls": sample["label"]["tool_calls"]}
    return {"sample_id": sample["id"], "input_source": models.source,
            "precision": {"asr": "fp32 ONNX" if models.source == "asr" else None, "llm": "float16"},
            "request_text": request_text, "reference_text": sample.get("audio_text"),
            "history": history, "stop_reason": stop_reason, "self_heal": self_heal,
            "initial_state": initial_state, "trace": trace, "submission": submission, "comparison": comparison}


def prepare_transcripts(samples, run_dir, data_root, split, model_root, asr_runtime):
    paths = list(dict.fromkeys(
        item["audio"] for sample in samples for item in (*sample.get("history", []), sample)
        if item.get("role", "user") == "user" and item.get("audio")
    ))
    request_path = run_dir / "asr_audio.json"
    output_path = run_dir / "asr_transcripts.json"
    request_path.write_text(dumps(paths), encoding="utf-8")
    print(f"ASR FP32 ONNX: xử lý {len(paths)} file trong tiến trình riêng.", flush=True)
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--asr-worker", str(request_path),
                    str(output_path), str(data_root), split, str(model_root), str(asr_runtime)], check=True)
    return json.loads(output_path.read_text(encoding="utf-8"))


def asr_worker(request_path, output_path, data_root, split, model_root, asr_runtime):
    if not asr_runtime.is_dir():
        raise FileNotFoundError(f"Không tìm thấy runtime CUDA: {asr_runtime}")
    sys.path.insert(0, str(asr_runtime))
    import sherpa_onnx
    import soundfile as sf

    if not Path(sherpa_onnx.__file__).resolve().is_relative_to(asr_runtime.resolve()):
        raise RuntimeError(f"Không nạp được sherpa-onnx CUDA từ {asr_runtime}")
    model = model_root / "gipformer1.5-68M-rnnt"
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(model / "encoder.onnx"), decoder=str(model / "decoder.onnx"),
        joiner=str(model / "joiner.onnx"), tokens=str(model / "tokens.txt"),
        num_threads=4, sample_rate=16000, feature_dim=80, decoding_method="greedy_search", provider="cuda",
    )
    transcripts = {}
    paths = json.loads(request_path.read_text(encoding="utf-8"))
    for index, audio in enumerate(paths, 1):
        data, rate = sf.read(str(data_root / split / audio), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        stream = recognizer.create_stream()
        stream.accept_waveform(rate, data)
        recognizer.decode_stream(stream)
        transcripts[audio] = stream.result.text.strip()
        if index % 25 == 0 or index == len(paths):
            print(f"ASR: {index}/{len(paths)}", flush=True)
    output_path.write_text(dumps(transcripts), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ids", nargs="+")
    selection.add_argument("--limit", type=int)
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--input", choices=("asr", "reference"), default="asr")
    parser.add_argument("--transcripts", type=Path, help="JSON ASR đã có để chạy lại cùng transcript")
    parser.add_argument("--data-root", type=Path, default=DATA)
    parser.add_argument("--split", choices=("train", "public_test"), default="train")
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--llm-dir", type=Path, help="Thư mục model LFM3 đã tải")
    parser.add_argument("--backend", choices=("llama.cpp", "transformers"), default="llama.cpp")
    parser.add_argument("--gguf-model", type=Path, help="File LFM3-1.7B-F16.gguf")
    parser.add_argument("--llama-server", type=Path, help="Binary llama-server")
    parser.add_argument("--prefill-chunk-size", type=int, default=512)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-prefix-caching", action="store_true")
    parser.add_argument("--enable-thinking", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--asr-runtime", type=Path, help="Thư mục runtime sherpa-onnx CUDA")
    parser.add_argument("--prompt", choices=("baseline", "enhanced"), default="enhanced")
    parser.add_argument("--prompt-file", type=Path, help="Thay thế prompt bằng nội dung file UTF-8")
    parser.add_argument("--tool-description", choices=("baseline", "enhanced"), default="enhanced")
    parser.add_argument("--no-self-heal", action="store_true")
    parser.add_argument("--ddr", action=argparse.BooleanOptionalAction, default=True,
                        help="Chạy thêm target trace để đo DDR")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, help="Trần output mỗi lượt; mặc định không đặt trần riêng")
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    if args.max_turns <= 0 or (args.max_tokens is not None and args.max_tokens <= 0) or (args.limit is not None and args.limit <= 0):
        parser.error("--limit, --max-turns và --max-tokens phải lớn hơn 0")
    if args.transcripts and args.input != "asr":
        parser.error("--transcripts chỉ dùng với --input asr")
    if args.split != "train" and (args.ddr or args.input == "reference"):
        parser.error("DDR và reference chỉ dùng với tập train có nhãn")
    llm_dir = args.llm_dir or args.model_root / "LFM3-1.7B" / "ac2586a34f1a1c03329dbdcdefabd8b6478ddaa7"
    if not llm_dir.is_dir():
        parser.error(f"Không tìm thấy tokenizer LFM3 tại {llm_dir}; dùng --llm-dir để chọn thư mục")
    split_dir = args.data_root / args.split
    with (split_dir / f"{args.split}.jsonl").open(encoding="utf-8") as file:
        samples = [json.loads(line) for line in file if line.strip()]
    if args.ids:
        selected = set(args.ids)
        samples = [sample for sample in samples if sample["id"] in selected]
        missing = selected - {sample["id"] for sample in samples}
        if missing:
            parser.error(f"Không tìm thấy mẫu: {', '.join(sorted(missing))}")
    elif not args.all:
        samples = samples[:args.limit or 1]
    catalog = json.loads((split_dir / f"{args.split}_tools_catalog.json").read_text(encoding="utf-8"))
    run_dir = args.out_dir or ROOT / "sandbox_runs" / datetime.now().strftime("enhanced_%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True, exist_ok=False)
    prompt = args.prompt_file.read_text(encoding="utf-8-sig") if args.prompt_file else {
        "baseline": BASELINE, "enhanced": ENHANCED}[args.prompt]
    transcripts = None
    if args.input == "asr":
        transcripts = (json.loads(args.transcripts.read_text(encoding="utf-8-sig")) if args.transcripts else
                       prepare_transcripts(samples, run_dir, args.data_root, args.split, args.model_root,
                                           args.asr_runtime or args.model_root.parent / "asr-cuda"))
    from metrics_eval import MetricModels, requires_state_change, score_runs, write_json
    gguf_model = args.gguf_model or args.model_root / "LFM3-1.7B-GGUF" / "cd0c74c575b5c416f3011b5b4c298077f26ca8c2" / "LFM3-1.7B-F16.gguf"
    llama_server = args.llama_server or args.model_root / "llama.cpp" / "llama-server.exe"
    runtime = Models(args.input, transcripts, llm_dir=llm_dir, context_tokens=CONTEXT_TOKENS,
                     prefill_chunk_size=args.prefill_chunk_size, enable_thinking=args.enable_thinking,
                     gguf_model=gguf_model if args.backend == "llama.cpp" else None,
                     server_binary=llama_server if args.backend == "llama.cpp" else None,
                     output_dir=run_dir, port=args.port,
                     enable_prefix_caching=not args.no_prefix_caching, backend=args.backend)
    models = MetricModels(runtime)
    config = {"sample_ids": [sample["id"] for sample in samples], "split": args.split, "input_source": args.input,
              "prompt": prompt, "tool_description": args.tool_description, "self_heal": not args.no_self_heal,
              "context_tokens": CONTEXT_TOKENS, "max_turns": args.max_turns, "max_tokens": args.max_tokens,
              "ddr": args.ddr, "backend": args.backend,
              "enable_thinking": args.enable_thinking,
              "asr_precision": "fp32" if args.input == "asr" else None,
              "gguf_model": str(gguf_model) if args.backend == "llama.cpp" else None,
              "llama_server": str(llama_server) if args.backend == "llama.cpp" else None,
              "prefill_chunk_size": args.prefill_chunk_size,
              "temperature": 0.0, "repeat_penalty": 1.1,
              "repeat_last_n": CONTEXT_TOKENS,
              "enable_prefix_caching": not args.no_prefix_caching,
              "generation_config": runtime.generation_config}
    (run_dir / "config.json").write_text(dumps(config), encoding="utf-8")
    full, target = {}, {}
    target_dir = run_dir / "target"
    if args.ddr:
        target_dir.mkdir()
    try:
        with (run_dir / "submission.jsonl").open("w", encoding="utf-8") as output:
            for sample in samples:
                print(f"Đang chạy {sample['id']}...", flush=True)
                models.target_names = None
                result = run_sample(sample, catalog, models, args.max_turns, args.max_tokens,
                                    system_prompt=prompt, self_heal=not args.no_self_heal,
                                    enhanced_tools=args.tool_description == "enhanced", data_root=args.data_root,
                                    split=args.split)
                full[sample["id"]] = result
                write_json(run_dir / f"{sample['id']}.json", result)
                output.write(dumps(result["submission"]) + "\n")
                output.flush()
                print(f"{sample['id']}: {result['stop_reason']} | {result['comparison']}", flush=True)
                if args.ddr and requires_state_change(sample, result["initial_state"]):
                    models.target_names = {call["name"] for call in sample["label"]["tool_calls"]}
                    target_result = run_sample(sample, catalog, models, args.max_turns, args.max_tokens,
                                               system_prompt=prompt, self_heal=not args.no_self_heal,
                                               enhanced_tools=args.tool_description == "enhanced",
                                               data_root=args.data_root, split=args.split,
                                               tool_names=models.target_names)
                    target[sample["id"]] = target_result
                    write_json(target_dir / f"{sample['id']}.json", target_result)
        if args.split == "train":
            summary = score_runs({sample["id"]: sample for sample in samples}, catalog, full, target)
            write_json(run_dir / "metrics_summary.json", summary)
    finally:
        runtime.close()
    print(f"Kết quả: {run_dir}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--asr-worker":
        asr_worker(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5],
                   Path(sys.argv[6]), Path(sys.argv[7]))
    else:
        main()
