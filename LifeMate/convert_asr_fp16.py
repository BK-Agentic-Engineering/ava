"""Chuyển Gipformer ONNX FP32 sang FP16, giữ kiểu I/O cho sherpa-onnx."""

import sys
from pathlib import Path

import onnx
from onnxconverter_common import float16

MODEL_DIR = Path(sys.executable).resolve().parents[2] / "models" / "gipformer1.5-68M-rnnt"


def original_float_casts(graph):
    names = set()
    for node in graph.node:
        if node.op_type == "Cast" and any(a.name == "to" and a.i == 1 for a in node.attribute):
            names.add(node.name)
        for attr in node.attribute:
            if attr.type == onnx.AttributeProto.GRAPH:
                names.update(original_float_casts(attr.g))
    return names


def fix_float_casts(graph, names):
    # onnxconverter-common không đổi thuộc tính Cast gốc từ FLOAT sang FLOAT16.
    for node in graph.node:
        if node.op_type == "Cast" and node.name in names:
            for attr in node.attribute:
                if attr.name == "to" and attr.i == 1:
                    attr.i = 10
        for attr in node.attribute:
            if attr.type == onnx.AttributeProto.GRAPH:
                fix_float_casts(attr.g, names)


def main():
    out = MODEL_DIR / "fp16"
    out.mkdir(exist_ok=True)
    for name in ("encoder", "decoder", "joiner"):
        model = onnx.load(MODEL_DIR / f"{name}.onnx")
        names = original_float_casts(model.graph)
        model = float16.convert_float_to_float16(model, keep_io_types=True)
        fix_float_casts(model.graph, names)
        onnx.save(model, out / f"{name}.onnx")
        print(f"Đã lưu {out / (name + '.onnx')}")


if __name__ == "__main__":
    main()
