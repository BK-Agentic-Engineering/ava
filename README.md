# LifeMate

Pipeline bàn giao cho Tú dùng audio hiện tại và audio user trong history. Gipformer
ONNX FP16 chuyển audio thành text, smolagents `ToolCallingAgent` điều phối LFM3-1.7B
F16 GGUF qua llama.cpp, rồi LifeMate SDK thực thi từng tool và trả kết quả về model.
History đã được áp dụng vào trạng thái ban đầu. Mỗi mẫu có một ToolEnv riêng.

Theo xác nhận của đội, BTC đã chạy và trả điểm cho Docker v3. Image
`lifemate-smolagents:handoff-local` đã build và chạy smoke test audio thật trên GPU
local. BTC chưa kiểm chứng image này. Việc tiếp theo là cải thiện độ chính xác của
model/agent và kiểm chứng checkpoint sau huấn luyện.

| Muốn chỉnh | Vị trí |
| --- | --- |
| ASR, audio history và context | `src/lifemate/asr.py`, `src/lifemate/data.py` |
| Vòng agent, system prompt, dispatch và phản hồi SDK | `src/lifemate/smolagents_harness.py` |
| Tool được phép và schema | `load_allowed_tools` trong `src/lifemate/tools.py`, catalog theo split của BTC |
| llama.cpp API, checkpoint và tham số sinh | `src/lifemate/llamacpp_client.py` |
| Load model, giới hạn, CLI và output | `src/lifemate/deploy.py`, `docker/predict.sh` |
| Tạo ToolEnv và lấy calls/hash | `src/lifemate/sdk.py`, `src/lifemate/submission.py` |

## Cài đặt và checkpoint

Cần Git, Python 3.12 để chạy công cụ build/kiểm tra, Docker với BuildKit và GPU NVIDIA
được cấp vào container Linux amd64 (Docker Desktop + WSL2 trên Windows). Docker cài
dependencies đã khóa trong `docker/requirements.txt` và `docker/cuda-requirements.txt`,
gồm smolagents 1.26.0, ONNX Runtime GPU 1.26.0, CUDA 12.8/cuDNN 9 và llama.cpp b12110.
Không cần `pip install -e .` để chạy pipeline này.

Lấy devkit từ BTC. Thư mục dữ liệu phải chứa `<split>/<split>.jsonl`, catalog,
`zaic_tools/`, audio và environments của split. Thư mục assets build cần:

```text
asr/fp16/{encoder,decoder,joiner}.onnx
asr/tokens.txt
asr/checkpoint.json
llm/lfm3-1.7b-gguf/LFM3-1.7B-F16.gguf
llm/lfm3-1.7b/LICENSE
```

Checkpoint hiện tại là `LFM3-1.7B-F16.gguf` từ `LiquidAI/LFM3-1.7B-GGUF`, revision
`cd0c74c575b5c416f3011b5b4c298077f26ca8c2`. SHA-256 và thông tin ASR nằm trong
[model provenance](docker/training_code/README.md).

### Tích hợp checkpoint sau huấn luyện

1. Nếu đầu ra huấn luyện là weights Hugging Face, cần export và kiểm chứng bản GGUF
   F16 tương thích với llama.cpp b12110 trước khi dùng cho inference. Kiểm tra chat
   template Jinja của LFM3 với context 16.384 token. Server cần trả
   `message.tool_calls` có ID duy nhất trong mỗi lượt, tên tool và arguments giải mã
   được thành JSON object. Phản hồi SDK được ghép bằng `tool_call_id`.
   `final_answer` phải đứng riêng trong lượt kết thúc.
2. Đặt GGUF vào thư mục assets truyền qua `-Assets`. Cập nhật SHA-256 của model
   trong `LlamaCpp.__init__` tại `src/lifemate/llamacpp_client.py`. Nếu đổi tên
   hoặc đường dẫn file, sửa đồng bộ lệnh `COPY` trong `Dockerfile` và đường dẫn
   `-m` trong `load_models` tại `src/lifemate/deploy.py`. Cập nhật provenance.
3. Rebuild bằng lệnh bên dưới với tag mới. Chạy smoke public, kiểm tra replay SDK,
   rồi so điểm train trên cùng mẫu và cùng giới hạn với checkpoint gốc.

## Build và chạy local

Từ thư mục repo, dùng PowerShell. Nhập đường dẫn thư mục assets và devkit đã chuẩn bị.

```powershell
$Assets = (Resolve-Path -LiteralPath (Read-Host 'Thư mục model assets')).Path
$Data = (Resolve-Path -LiteralPath (Read-Host 'Thư mục devkit chứa các split')).Path
$Image = 'lifemate-smolagents:handoff-local'
.\docker\build.ps1 -Image $Image -Assets $Assets

$Result = Join-Path $PWD 'runs\smoke-public-0039'
New-Item -ItemType Directory -Path $Result -ErrorAction Stop
docker run --rm --gpus 'device=0' --network none `
  --mount "type=bind,source=$Data,target=/data,readonly" `
  --mount "type=bind,source=$Result,target=/result" `
  $Image /code/predict.sh --split public_test --smoke-test --sample-id public_0039
```

Giữ nguyên image tag đã dùng cho bản nộp. Dùng thư mục kết quả mới cho mỗi lần chạy.
Khi gọi mặc định, `/code/predict.sh` chạy toàn bộ `private_test` từ `/data` và ghi
`/result/submission.jsonl` với `id`, `tool_calls`, `state_hash` và `time` (ms).
Notebook dùng cùng runtime và ghi `jupyter_submission.jsonl`. Xem lệnh notebook
và export image tại [Docker workflow](docker/README.md).

## Kiểm thử và đánh giá

```powershell
docker run --rm --network none --entrypoint python -e LIFEMATE_TEST_DATA=/data `
  --mount "type=bind,source=$Data,target=/data,readonly" `
  --mount "type=bind,source=$PWD\tests,target=/tests,readonly" `
  $Image /tests/test_smolagents_deploy.py -v

$env:PYTHONPATH = Join-Path $PWD 'src'
python -B scripts/verify_docker_run.py $Result --data-root $Data --split public_test --sample-id public_0039
```

Test dùng SDK thật với phản hồi model/ASR có kịch bản. Lệnh verify chạy sau inference,
kiểm tra đủ ID, replay theo thứ tự và so kết quả từng call cùng state hash. Dùng
`--sample-id` cho smoke và bỏ cờ này khi đã chạy toàn split. Public không có gold.
Để kiểm tra cả bước chấm local, chạy một mẫu train có gold:

```powershell
$TrainResult = Join-Path $PWD 'runs\smoke-train-0001'
New-Item -ItemType Directory -Path $TrainResult -ErrorAction Stop
docker run --rm --gpus 'device=0' --network none `
  --mount "type=bind,source=$Data,target=/data,readonly" `
  --mount "type=bind,source=$TrainResult,target=/result" `
  $Image /code/predict.sh --split train --smoke-test --sample-id train_0001
python -B scripts/verify_docker_run.py $TrainResult --data-root $Data --split train --sample-id train_0001 --score-train
```

Điểm ghi vào `metrics.json` theo [công thức local](docs/SCORING.md). Một mẫu train
chỉ cho điểm của mẫu đó. Dùng cùng phạm vi mẫu để so sánh các checkpoint.

## Giới hạn

- Seed 0, greedy, 8 lượt model, context 16.384 token, output tối đa 2.048 token/lượt.
  Thời gian mẫu gồm ASR và SDK, giới hạn 30 giây. Khởi động model tính riêng.
  Thao tác native đang chạy có thể vượt deadline trước khi Python lấy lại quyền điều khiển.
- Đọc `submission/results.jsonl`, `submission/traces/` và `submission_runtime/`
  trong output để phân biệt lỗi thực thi, hết lượt, và hành động model chọn sai.
  SDK `ok: true` chỉ xác nhận tool đã được gọi. Xem thêm `done` và kết quả thực tế.
- Giữ weights, dataset, credentials, cache và outputs ngoài Git. README và các lệnh
  của pipeline trước đây có thể xem bằng `git show c36b705:README.md`.
