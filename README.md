# LifeMate

Audio → Gipformer ASR → LFM3-1.7B → Jaz → LifeMate SDK → submission JSONL → chấm local.
Inference hỗ trợ BF16/FP16; local mặc định BF16. Không quantization, sinh greedy.

## Cài đặt và dữ liệu

Dùng Python 3.12 và Git. Với máy local CUDA 13:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\python.exe -m pip install -e .
```

Dependencies và commit Jaz được khai báo trong `pyproject.toml`. Inference không tải model;
cần có sẵn `models/llm/lfm3-1.7b/`, `models/asr/tokens.txt` và ba file ONNX trong
`models/asr/fp16/`. ASR nhận audio 16 kHz.

Dataset root phải chứa `<split>/<split>.jsonl`, catalog, `zaic_tools/`, environments
và audio. Mặc định: `../train+public_test/train+public_test/`; đổi bằng `--data-root`.
Không đưa dataset, weights, runs hoặc credentials lên GitHub.

## Chạy local

Từ thư mục dự án:

```powershell
# 20 mẫu train bằng audio, gồm audio user history
.\.venv\Scripts\python.exe -X utf8 run.py --audio --limit 20 --output runs\train20
# Tiếp tục cùng selection, source, assets và budget
.\.venv\Scripts\python.exe -X utf8 run.py --audio --limit 20 --output runs\train20 --resume
# Toàn bộ public: xuất submission và kiểm tra SDK replay, không có điểm local
.\.venv\Scripts\python.exe -X utf8 run.py --audio --split public_test --all --output runs\public
# Chấm lại train hoặc tạo recap
.\.venv\Scripts\python.exe -X utf8 run.py --score-run runs\train20
.\.venv\Scripts\python.exe -X utf8 run.py --recap-run runs\train20
```

Audio là opt-in. Text là mặc định của CLI và chỉ dùng transcript train; chọn `--text`
khi debug. Dùng `--id ID` để chọn một mẫu, `--all` để chạy đủ split, `--help` để xem
các tùy chọn còn lại. Không nộp submission subset train lên public leaderboard.

Adapter synthetic dùng cùng runner:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m lifemate.synthetic --package data\synthetic\handoff_v01 --output runs\synthetic
```

Reference/gold/oracle không vào model input. History đã áp dụng vào WORLD; chỉ các
call mới được thực thi, theo thứ tự, kể cả call bị SDK từ chối.

## Kết quả và resume

- `sessions/<id>/result.json`: kết quả chuẩn đã commit; `journal.jsonl`: bằng chứng phục hồi.
- `last_attempt.json`: lượt dở; `traces/`: input, raw model output, calls/results và lỗi.
- `submission.jsonl`: đúng `id`, `tool_calls`, `state_hash`, lấy từ SDK.
- `metadata.json`, `samples.jsonl`, `metrics.json` hoặc `verification.json`: phạm vi, runtime, điểm/replay.
- `recap.html`: tạo bằng `--recap-run`.

Hoàn tất batch nghĩa là đủ kết quả đã đóng và có submission, không đồng nghĩa task
đúng. Preparation error giữ error record nhưng không tạo state hash giả.

Resume bỏ qua inference của mẫu đã commit. Mẫu dở chỉ tiếp tục khi ordered replay
khớp result/hash; journal ghi dở, intent thiếu result hoặc chi phí inference chưa xác
định sẽ báo lỗi, không đoán. Giữ một writer/run và đúng snapshot source/config/assets.
Thay code sẽ đổi identity; dùng snapshot cũ để resume run cũ.

Budget mặc định: 30 giây/mẫu gồm ASR/preparation, context 16.384 token, output tối đa
512 token/lượt. Deadline mềm; không hủy cưỡng bức CUDA/SDK.

## Code và kiểm thử

Các module nằm trong `src/lifemate/`:

| Thành phần | File |
|---|---|
| Audio / inference | asr.py, llm.py |
| Vòng Jaz và tool protocol | agent.py, tools.py |
| Input và adapter | data.py, synthetic.py |
| SDK và output | sdk.py, submission.py |
| Batch, journal, trace | batch.py, store.py, trace.py |
| Local evaluation / recap | evaluate.py, verify.py, recap.py |

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/check_offline.py
```

Test native dùng tokenizer/parser, Jaz và SDK thật với bộ sinh token có kịch bản;
không nạp weights LLM hoặc chạy ASR/GPU. Cần tokenizer local và handoff private ở
`data/synthetic/handoff_v01/`. Test không chứng minh chất lượng model hay parity evaluator BTC.

Matching, optional defaults và giới hạn điểm local: [SCORING.md](docs/SCORING.md).
Public không có gold nên không có exact local public score.
