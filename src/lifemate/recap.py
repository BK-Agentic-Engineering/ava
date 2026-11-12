"""Offline recap from canonical session results, or legacy run exports."""

from html import escape
import json
from pathlib import Path

from .data import read_jsonl


def render_recap(run_dir, destination=None):
    run_dir = Path(run_dir)
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    summaries = list(read_jsonl(run_dir / "samples.jsonl"))
    metric_path = run_dir / "metrics.json"
    metrics = json.loads(metric_path.read_text(encoding="utf-8")) if metric_path.exists() else {}
    details = {d["id"]: d for d in metrics.get("details", [])}
    rows = []
    for sample in summaries:
        sid = sample["id"]
        record_file = run_dir / "sessions" / sid / "result.json"
        if not record_file.exists():
            record_file = run_dir / "sessions" / sid / "last_attempt.json"
        record = json.loads(record_file.read_text(encoding="utf-8")) if record_file.exists() else None
        if record:
            calls = record["calls"]
            source = record.get("source", {})
        else:
            path = run_dir / "traces" / f"{sid}.jsonl"
            calls = [e for e in read_jsonl(path) if e["event"] == "tool"] if path.exists() else []
            source = {"format": "legacy exports"}
        detail = details.get(sid, {})
        metric = detail.get("local_btc_metric", detail)
        value = metric.get("score")
        score = "—" if value is None else f"{value:.3f}"
        seconds = sample.get("elapsed_seconds")
        elapsed = "—" if seconds is None else f"{seconds:.3f}"
        evidence = {"calls_and_results": calls, "final_text": sample.get("final_text"),
                    "error": sample.get("error"), "reason": sample.get("reason"),
                    "verification": detail, "source": source}
        rows.append(f"<tr><td>{escape(sid)}</td><td>{escape(sample['status'])}</td><td>{elapsed}</td>"
            f"<td>{len(calls)}</td><td>{score}</td><td><details><summary>Xem</summary><pre>"
            f"{escape(json.dumps(evidence, ensure_ascii=False, indent=2))}</pre></details></td></tr>")
    score = metrics.get("score_0_to_100")
    score_label = "Chưa có điểm đầy đủ" if score is None else f"{score:.2f}/100 (local)"
    html = f"""<!doctype html><html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>LifeMate local</title>
<style>body{{font:15px/1.6 system-ui;margin:24px;color:#20313a;background:#f5f7f8}}
main{{max-width:1150px;margin:auto}}section{{padding:20px;background:white;border:1px solid #dbe3e8;border-radius:10px;margin:16px 0;overflow:auto}}
table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #e0e5e9}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;max-width:650px;font-size:12px}}</style>
<main><h1>LifeMate · {escape(run_dir.name)}</h1><p>{escape(score_label)} · {len(summaries)} session records</p>
<section><h2>Cấu hình</h2><details><summary>Xem cấu hình nguồn</summary><pre>{escape(json.dumps(metadata,ensure_ascii=False,indent=2))}</pre></details></section>
<section><h2>Kết quả</h2><table><thead><tr><th>ID</th><th>Trạng thái</th><th>Giây</th><th>Calls</th><th>Điểm 0–1</th><th>Chi tiết</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></section>
<section><h2>Cách đọc</h2><p>Completed là kết thúc phiên, không đồng nghĩa đạt mục tiêu.
Điểm matcher local, hash replay và oracle là các kết quả riêng. Fuzzy dùng NFC,
lowercase và whitespace token-F1 &gt;0,6; optional defaults chưa được chuẩn hóa.
Không khẳng định parity với evaluator BTC. Deadline là soft deadline.</p>
<p>Result đã commit là nguồn chuẩn của run mới; submission/summary là bản xuất lại.
Mẫu dở hoặc recovery_required cần xem journal và lý do dừng.</p></section></main></html>"""
    destination = Path(destination) if destination else run_dir / "recap.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination

