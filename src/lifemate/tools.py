"""Đọc catalog BTC và chuyển đầu ra LFM3 thành tool call cho SDK."""

import json
import re


RESPONSE_TEMPLATE = {
    "defaults": {"role": "assistant"},
    "start_anchor": "<|im_start|>assistant\n",
    "fields": {
        "reasoning_content": {
            "open": "<think>",
            "close": "</think>",
            "content": "text",
        },
        "tool_calls": {
            "open_pattern": (
                r"<tool_call>\s*<function=(?P<name>[^>\s]+)>"
            ),
            "close_pattern": r"</function>\s*</tool_call>",
            "repeats": True,
            "content": "xml-inline",
            "content_args": {
                "tag_pattern": (
                    r"<parameter=(?P<key>[^>]+)>\s*"
                    r"(?P<value>.*?)\s*</parameter>"
                ),
            },
            "transform": {
                "type": "function",
                "function": {
                    "name": "{name}",
                    "arguments": "{content}",
                },
            },
        },
        "content": {
            "close": "<|im_end|>",
            "content": "text",
        },
    },
}


def load_allowed_tools(data_root, split, item):
    """Lấy schema thật, chỉ giữ các tool mẫu được phép sử dụng."""
    catalog_path = data_root / split / f"{split}_tools_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    allowed = {
        name
        for app in item["context"]["installed_apps"].values()
        for name in app["tools"]
    }
    # System tool luôn được phép theo SDK hiện tại.
    allowed.add("sys.ask_missing_info")

    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for app in catalog["apps"]
        for tool in app["tools"]
        if tool["name"] in allowed
    ]


def parse_tool_response(tokenizer, generated_tokens, prompt_tokens, tools):
    """Parse cú pháp LFM3; kiểm tra schema/hành vi thuộc về SDK."""
    raw_text = tokenizer.decode(
        generated_tokens,
        skip_special_tokens=False,
    )
    call_count = raw_text.count("<tool_call>")

    if call_count != raw_text.count("</tool_call>"):
        raise ValueError("Tool call chưa đóng đủ thẻ.")

    # Không để parser âm thầm ghi đè tham số bị lặp.
    blocks = re.findall(r"<tool_call>(.*?)</tool_call>", raw_text, flags=re.S)
    for block in blocks:
        parameter_names = re.findall(r"<parameter=([^>]+)>", block)
        if len(parameter_names) != block.count("</parameter>"):
            raise ValueError("Tham số tool chưa đóng đủ thẻ.")
        if len(parameter_names) != len(set(parameter_names)):
            raise ValueError("Tool call có tham số bị lặp tên.")

    message = tokenizer.parse_response(
        generated_tokens,
        schema=RESPONSE_TEMPLATE,
        prefix=prompt_tokens,
        tools=tools,
    )

    # Chuyển format message của model sang format call của BTC.
    tool_calls = [
        {
            "name": call["function"]["name"],
            "arguments": call["function"]["arguments"],
        }
        for call in message.get("tool_calls", [])
    ]
    if len(tool_calls) != call_count:
        raise ValueError("Không parse được đầy đủ tool call của LFM3.")

    return {
        "raw_text": raw_text,
        "content": message.get("content", ""),
        "tool_calls": tool_calls,
    }
