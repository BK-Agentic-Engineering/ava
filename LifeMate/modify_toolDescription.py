"""Chuẩn hóa mô tả tool từ metadata của catalog LifeMate.

Có thể dùng normalize_catalog khi nạp catalog hoặc chạy script với đường dẫn
catalog để in kết quả JSON ra stdout.
"""

import argparse
import copy
import json
import sys
from pathlib import Path


LABELS = {
    "read": "[TRA CỨU (Không đổi trạng thái)]",
    "write": "[HÀNH ĐỘNG (Thay đổi trạng thái)]",
    "meta": "[HỆ THỐNG]",
}


def normalize_description(tool):
    kind = tool.get("kind")
    parts = [LABELS.get(kind, ""), tool.get("description", "").strip()]

    if kind == "read" and tool.get("returns"):
        parts.append(f"Trả về: {tool['returns']}.")
    elif kind == "write":
        parameters = tool.get("parameters", {})
        properties = parameters.get("properties", {})
        references = [
            name for name in parameters.get("required", [])
            if properties.get(name, {}).get("x-ref")
        ]
        if references:
            names = ", ".join(references)
            parts.append(f"Nếu chưa biết {names}, tra cứu thông tin cần thiết trước khi gọi.")

    return " ".join(part for part in parts if part)


def normalize_catalog(catalog):
    """Trả về catalog mới, chỉ thay đổi description của các tool."""
    result = copy.deepcopy(catalog)
    for app in result["apps"]:
        for tool in app["tools"]:
            tool["description"] = normalize_description(tool)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path, help="Đường dẫn đến catalog JSON")
    args = parser.parse_args()

    with args.catalog.open(encoding="utf-8") as file:
        catalog = json.load(file)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    json.dump(normalize_catalog(catalog), sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
