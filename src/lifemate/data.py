"""Đọc input và chuẩn bị dữ liệu được phép gửi cho agent."""

import json


def read_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def samples(data_root, split, *, limit=None, ids=None, text=False):
    if text and split != "train":
        raise ValueError("Text mode chỉ dùng train.")
    wanted = set(ids or [])
    count = 0
    found = set()
    for row in read_jsonl(data_root / split / f"{split}.jsonl"):
        if wanted and row["id"] not in wanted:
            continue
        # Whitelist: không chuyển label sang agent.
        item = {key: row[key] for key in ("id", "audio", "context")}
        keys = {"role", "audio", "text", "tool_calls", "tool_results"}
        if text:
            item["audio_text"] = row["audio_text"]
            keys.add("audio_text")
        item["history"] = [
            {key: value for key, value in turn.items() if key in keys}
            for turn in row["history"]
        ]
        yield item
        count += 1
        found.add(item["id"])
        if limit is not None and count >= limit:
            break
    if wanted - found:
        raise ValueError(f"Không tìm thấy ID: {sorted(wanted - found)}")


def build_messages(item, data_root, split, *, asr=None, text=False):
    """ASR cho mọi lượt user; history đã thực hiện, không replay tool."""
    if text and split != "train":
        raise ValueError("Chế độ text chỉ dùng transcript chuẩn của train.")

    def transcript(turn):
        if text:
            return turn["audio_text"]
        return asr.transcribe(data_root / split / turn["audio"])

    context = {
        key: value for key, value in item["context"].items()
        if key != "installed_apps"
    }
    messages = [{
        "role": "system",
        "content": (
            "Bạn thực hiện yêu cầu tiếng Việt bằng các tool được cung cấp. "
            "Chỉ gọi tool được phép, không bịa ID hoặc kết quả. "
            "History đã được thực hiện trong môi trường; "
            "không chạy lại hành động cũ. "
            "Đọc dữ liệu qua tool khi cần. "
            "Nếu thiếu thông tin không thể tìm bằng tool, "
            "dùng sys.ask_missing_info theo schema. "
            "Chỉ xử lý yêu cầu hiện tại.\n"
            "Context: " + json.dumps(context, ensure_ascii=False)
        ),
    }]

    for index, turn in enumerate(item["history"]):
        if turn["role"] == "user":
            messages.append({"role": "user", "content": transcript(turn)})
        elif turn["role"] == "assistant":
            content = turn.get("text", "")
            calls = turn.get("tool_calls", [])
            results = turn.get("tool_results", [])
            if calls and len(calls) == len(results):
                paired_calls = [
                    {
                        "id": f"history_{index}_{n}",
                        "type": "function",
                        "function": call,
                    }
                    for n, call in enumerate(calls)
                ]
                messages.append({
                    "role": "assistant", "content": content,
                    "tool_calls": paired_calls,
                })
                for call, result in zip(paired_calls, results):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                # Devkit cho phép history có call mà không kèm result.
                # Giữ dữ liệu được cung cấp, không tự tạo result thay thế.
                if calls or results:
                    content += "\nLịch sử tool đã thực hiện: " + json.dumps(
                        {"tool_calls": calls, "tool_results": results},
                        ensure_ascii=False,
                    )
                messages.append({"role": "assistant", "content": content})

    messages.append({"role": "user", "content": transcript(item)})
    return messages


def prepare_btc(item, root, split, *, text=True, asr=None):
    from .sdk import environment_ref
    from .tools import load_allowed_tools
    return {"id": item["id"],
            "messages": build_messages(item, root, split, text=text, asr=asr),
            "tools": load_allowed_tools(root, split, item),
            "environment": environment_ref(root, split, item["id"]),
            "source": {"kind": "btc", "intended_split": split, "mode": "text" if text else "audio"}}
