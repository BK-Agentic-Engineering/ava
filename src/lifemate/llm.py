"""LLM inference local: messages và tools → phản hồi đã parse."""

import torch
import time
import json
import hashlib
from pathlib import Path
from importlib.metadata import version
from transformers import (
    AutoModelForCausalLM, AutoTokenizer, GenerationConfig,
    StoppingCriteria, StoppingCriteriaList,
)

from .tools import parse_tool_response
from .config import Budget, PREFILL_CHUNK, remaining_context


def generation_policy(max_new_tokens=Budget().output_tokens):
    return GenerationConfig(
        do_sample=False, num_beams=1, temperature=1.0, repetition_penalty=1.0,
        max_new_tokens=max_new_tokens, use_cache=True, prefill_chunk_size=PREFILL_CHUNK,
    )


def inference_identity(model_path, generation, precision="bfloat16"):
    root = Path(model_path)
    artifacts = {}
    # Hash once per backend startup, not per query. Checkpoints stay unchanged while loaded.
    suffixes = {".safetensors", ".bin", ".json", ".jinja", ".py", ".model", ".txt", ".tiktoken"}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in suffixes and "__pycache__" not in path.parts:
            with path.open("rb") as stream:
                artifacts[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"artifacts": artifacts, "generation": generation.to_dict(), "precision": precision,
            "versions": {"torch": torch.__version__, "transformers": version("transformers"),
                         "accelerate": version("accelerate"), "cuda": torch.version.cuda}}


def prepare_inputs(tokenizer, messages, tools=None):
    """Cùng một chat-template boundary cho inference và kiểm thử native."""
    return tokenizer.apply_chat_template(
        messages, tools=tools, tokenize=True, add_generation_prompt=True,
        return_tensors="pt", return_dict=True, enable_thinking=False,
    )


def decode_response(tokenizer, generated_tokens, prompt_tokens, tools=None, **stats):
    started = time.monotonic()
    result = {
        "raw_text": tokenizer.decode(generated_tokens, skip_special_tokens=False),
        "assistant_text": tokenizer.decode(generated_tokens, skip_special_tokens=True),
        "input_tokens": len(prompt_tokens), "output_tokens": len(generated_tokens), **stats,
    }
    try:
        result.update(parse_tool_response(tokenizer, generated_tokens, prompt_tokens, tools))
        result["parse_error"] = None
    except ValueError as error:
        result.update(content="", tool_calls=[], parse_error=str(error))
    result["timings"] = {**stats.get("timings", {}), "parse_seconds": time.monotonic() - started}
    return result


class LocalLLM:
    def __init__(self, model_path, *, precision="bfloat16"):
        dtypes = {"bfloat16": torch.bfloat16, "float16": torch.float16}
        if precision not in dtypes:
            raise ValueError("precision must be bfloat16 or float16")
        self.identity = {"kind": "local_llm", **inference_identity(model_path, generation_policy(), precision),
                         "checkpoint": json.loads((Path(model_path) / "checkpoint.json").read_text(encoding="utf-8"))}
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            trust_remote_code=True,
            local_files_only=True,
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            dtype=dtypes[precision],
            device_map="cuda",
            trust_remote_code=True,
            local_files_only=True,
        ).eval()

    @torch.inference_mode()
    def generate(self, messages, tools=None, *, deadline=None,
                 max_context_tokens=Budget().context_tokens, max_new_tokens=Budget().output_tokens):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Hết thời gian trước lượt LLM.")
        prepared_at = time.monotonic()
        inputs = prepare_inputs(self.tokenizer, messages, tools).to(self.model.device)
        if self.model.device.type == "cuda":
            torch.cuda.synchronize(self.model.device)
        render_seconds = time.monotonic() - prepared_at
        input_length = inputs["input_ids"].shape[1]
        remaining = remaining_context(input_length, max_context_tokens)

        class Deadline(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return deadline is not None and time.monotonic() >= deadline

        generation_config = generation_policy(min(max_new_tokens, remaining))
        started = time.monotonic()
        output = self.model.generate(
            **inputs,
            generation_config=generation_config,
            stopping_criteria=StoppingCriteriaList([Deadline()]),
        )
        if self.model.device.type == "cuda":
            torch.cuda.synchronize(self.model.device)
        generated_tokens = output[0, input_length:]
        stats = {
            "seconds": time.monotonic() - started,
            "timed_out": deadline is not None and time.monotonic() >= deadline,
            "timings": {"render_tokenize_seconds": render_seconds,
                        "inference_seconds": time.monotonic() - started},
        }
        eos = self.model.generation_config.eos_token_id
        eos = eos if isinstance(eos, list) else [eos]
        stats["hit_token_limit"] = (
            len(generated_tokens) == generation_config.max_new_tokens
            and int(generated_tokens[-1]) not in eos
        )
        return decode_response(self.tokenizer, generated_tokens, inputs["input_ids"][0],
                               tools, **stats)
