"""Kiểm tra và tạo phản hồi sửa lỗi cho một phiên ToolEnv."""

import json
import re


def call_key(call):
    return json.dumps(call, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def reference_sources(spec, specs):
    sources = []
    for param in spec.get("parameters", {}).get("properties", {}).values():
        if not param.get("x-ref"):
            continue
        description = param.get("description", "").partition("lấy từ ")[2].strip().rstrip(".")
        names = re.findall(r"\b\w+\.\w+\b", description)
        if (names and all(name != spec.get("name") and specs.get(name, {}).get("kind") == "read"
                          for name in names) and description not in sources):
            sources.append(description)
    return sources


class SelfHealer:
    """Theo dõi các lần đọc và lệnh ghi lỗi khi state chưa thay đổi."""

    def __init__(self, specs):
        self.specs = specs
        self.seen_reads = set()
        self.failed_writes = set()

    def precheck(self, env, call):
        name, arguments = call["name"], call["arguments"]
        spec = self.specs.get(name)
        if spec is None:
            return "unknown_tool", f"Công cụ {name} không có trong danh sách được cấp. Chỉ chọn công cụ hiện có."
        if not isinstance(arguments, dict):
            return "invalid_arguments", f"Tham số của {name} phải là một đối tượng."
        properties = spec.get("parameters", {}).get("properties", {})
        unknown = sorted(set(arguments) - set(properties))
        validation = env.validate(name, arguments)
        if unknown or not validation["ok"]:
            errors = []
            if not validation["ok"]:
                errors.append(validation["error"])
            if unknown:
                errors.append(f"khóa không hợp lệ: {', '.join(unknown)}")
            hint = f"Lệnh {name} không hợp lệ: {'; '.join(errors)}."
            sources = reference_sources(spec, self.specs)
            if sources and not validation["ok"] and ("thiếu" in validation["error"] or "cần một trong" in validation["error"]):
                hint += f" Nếu thiếu ID, cân nhắc tra cứu qua {', '.join(sources)}."
            return ("unknown_parameters" if validation["ok"] else "schema_error"), hint
        if spec.get("kind") == "read" and call_key(call) in self.seen_reads:
            return ("repeated_read",
                    "Lệnh tra cứu này đã chạy và state chưa đổi. Dùng dữ liệu đã có để chọn bước tiếp theo, "
                    "không lặp lại lệnh đọc.")
        if spec.get("kind") == "write" and call_key(call) in self.failed_writes:
            return ("repeated_failed_write",
                    "Lệnh ghi này đã thất bại và state chưa đổi. Sửa tham số hoặc tra cứu trước khi thử lại.")
        return None, None

    def observe(self, call, result, state_changed):
        """Ghi nhận lệnh đã thực thi và trả về (trigger, hint)."""
        if state_changed:
            self.seen_reads.clear()
            self.failed_writes.clear()

        spec = self.specs.get(call["name"], {})
        kind = spec.get("kind")
        key = call_key(call)
        failed = result.get("ok") is False or result.get("done") is False
        if failed:
            if kind == "write":
                self.failed_writes.add(key)
            if result.get("ok") is False:
                hint = f"Lệnh bị từ chối: {result.get('error', 'không rõ nguyên nhân')}. Sửa theo schema."
                sources = reference_sources(spec, self.specs)
                if sources:
                    hint += f" Nếu thiếu ID, cân nhắc tra cứu qua {', '.join(sources)}."
                return "rejected", hint
            return "not_done", "Thao tác chưa hoàn tất. Kiểm tra kết quả, tra cứu hoặc sửa tham số trước khi thử lại."

        if kind != "read" or result.get("ok") is not True:
            return None, None
        self.seen_reads.add(key)
        hints = []
        returns = spec.get("returns", "")
        schema = spec.get("parameters", {})
        excluded = set(schema.get("required", [])) | {
            name for group in schema.get("x-one-of", []) for name in group
        }
        optional = [
            name for name, value in call["arguments"].items()
            if name in schema.get("properties", {}) and name not in excluded
            and name not in {"limit", "offset", "page", "page_size", "max_results"}
            and value not in (None, "", [], {})
        ]
        list_names = re.findall(r"(?:^|,\s*)(\w+)\[\]", returns)
        empty = bool(optional and list_names) and all(result.get(name) == [] for name in list_names)
        if empty:
            hints.append(f"Kết quả rỗng với tham số tùy chọn {', '.join(optional)}. "
                         "Cân nhắc bỏ bớt bộ lọc nếu vẫn giữ đúng yêu cầu, không tự đoán tham số.")
        if hints:
            return "empty_read", " ".join(hints)
        return None, None
