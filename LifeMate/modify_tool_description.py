"""Tạo Enhanced Tool Description từ catalog LifeMate.

normalize_catalog trả về bản sao và chỉ thay description. Truyền available_tools
khi biết toolset của mẫu để chỉ gợi ý các tool tra cứu hiện có.
"""

import argparse
import copy
import json
import re
import sys
from pathlib import Path


LABELS = {
    "read": "[TRA CỨU]",
    "write": "[HÀNH ĐỘNG]",
    "meta": "[HỆ THỐNG]",
}

# Chỉ liệt kê các tham số đã xác minh là bộ lọc trong catalog/ToolEnv.
FILTERS = {
    "smart_home.get_status": ("room", "floor", "type"),
    "appliances.list": ("type",),
    "bill_payment.list_bills": ("type",),
    "gold_price.get_price": ("type",),
    "fuel_price.get_price": ("type",),
    "contacts.search": ("query",),
    "library.search": ("query",),
    "calendar.list_events": ("date_from", "date_to"),
    "bike_rental.find_bikes": ("near",),
}


def normalize_description(tool, read_tools=None):
    """Tạo mô tả từ metadata; read_tools là các tool đọc hiện khả dụng."""
    read_tools = set(read_tools or ())
    kind = tool.get("kind")
    name = tool["name"]
    parameters = tool.get("parameters", {})
    properties = parameters.get("properties", {})
    required = set(parameters.get("required", []))
    alternatives = {param for group in parameters.get("x-one-of", []) for param in group}

    description = tool.get("description", "").strip()
    if name == "weather.get_forecast" and description == "Dự báo theo ngày":
        description = "Dùng khi cần dự báo thời tiết theo ngày"
    if description and not description.endswith((".", "!", "?")):
        description += "."
    parts = [LABELS.get(kind, ""), description]

    if kind == "read":
        if tool.get("returns"):
            parts.append(f"Trả về {tool['returns']}.")
        filters = [
            param for param in FILTERS.get(name, ())
            if param in properties and param not in required | alternatives
        ]
        if filters:
            parts.append(
                "Nếu lọc không ra kết quả, cân nhắc bỏ bộ lọc tùy chọn: "
                + ", ".join(filters) + "."
            )

    has_id_reference = False
    for param, schema in properties.items():
        if not schema.get("x-ref"):
            continue
        source = schema.get("description", "").partition("lấy từ ")[2].strip().rstrip(".")
        sources = set(re.findall(r"\b\w+\.\w+\b", source))
        prefix = f"Nếu chọn {param}" if param in alternatives and param not in required else f"Nếu cần {param}"
        if sources and sources <= read_tools and name not in sources:
            parts.append(f"{prefix} mà chưa biết, tra qua {source} nếu có.")
        elif name not in sources:
            parts.append(f"{prefix} mà chưa biết, tra cứu trước nếu có thể.")
        if param.endswith("_id") or param == "id":
            has_id_reference = True
    if has_id_reference:
        parts.append("Không tự đoán ID.")
    return " ".join(part for part in parts if part)


def normalize_catalog(catalog, available_tools=None):
    """Trả về catalog mới, chỉ thay description; không lọc danh sách tool."""
    result = copy.deepcopy(catalog)
    if available_tools is not None:
        available_tools = set(available_tools)
    read_tools = {
        tool["name"]
        for app in result["apps"]
        for tool in app["tools"]
        if tool.get("kind") == "read"
        and (available_tools is None or tool["name"] in available_tools)
    }
    for app in result["apps"]:
        for tool in app["tools"]:
            tool["description"] = normalize_description(tool, read_tools)
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
