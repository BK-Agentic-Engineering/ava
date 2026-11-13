## 1. Tóm tắt kết quả Benchmark và Bài học thực nghiệm trên 1.545 mẫu

### 1.1. Bảng đối chiếu chỉ số Benchmark qua các phiên bản (Baseline đến Sandbox 3.3*)

Toàn bộ thực nghiệm được đánh giá trên 1.545 mẫu tập Train với mô hình `LFM3-1.7B` và bộ phiên âm ASR cố định:

| Cấu hình | Contest Score $\uparrow$ | SSR $\uparrow$ | USMR $\downarrow$ | SHR (Rec./Err.) $\uparrow$ | MI/Abs F1 $\uparrow$ | DDR $\downarrow$ | Final State Match $\uparrow$ | Exact Ordered $\uparrow$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline** | 6,83 | 26,57 | 19,22 | 20,77% (279/1.343) | 14,23 | 65,62 | 367 (23,75%) | 87 (5,63%) |
| **+ Tool Descriptions** | 7,72 | 27,30 | 16,05 | 23,64% (265/1.121) | 14,65 | 55,00 | 386 (24,98%) | 99 (6,41%) |
| **+ System Prompt** | 7,66 | 27,09 | 15,08 | 23,83% (345/1.448) | 14,88 | 11,63 | 389 (25,18%) | 100 (6,47%) |
| **+ Sandbox (3.0)** | 7,64 | 26,85 | 16,31 | 27,44% (309/1.126) | 14,93 | 17,78 | 380 (24,60%) | 100 (6,47%) |
| **+ Sandbox 3.1** | 6,96 | 26,61 | 20,71 | 22,30% (188/843) | 11,70 | 20,34 | 371 (24,01%) | 90 (5,83%) |
| **+ Sandbox 3.2** | 6,66 | 26,03 | 15,47 | 17,81% (135/758) | 12,42 | 8,33 | 373 (24,14%) | 87 (5,63%) |
| **+ Sandbox 3.3\*** | 6,54 | 30,37 | 24,92 | 18,08% (232/1.283) | 9,54 | 38,93 | 399 (25,83%) | 60 (3,88%) |

*Ghi chú:* Cấu hình Sandbox 3.3\* chuyển sang backend llama.cpp, bật thinking (Thinking: on) và dùng ASR FP32 (khác 45/5.036 phiên âm so với bản 3.2). DDR ghi nhận 91/149 mẫu thay đổi state khớp hoàn toàn (mức tuyệt đối cao nhất từ trước đến nay).

### 1.2. Phân loại 1.545 mẫu và 3 điểm nghẽn gốc trên traces

Phân hoạch 1.545 mẫu của `ablation_03_2_results` thành 6 nhóm loại trừ nhau:

| Phân nhóm mẫu (Sandbox 3.2) | Số mẫu | Tỷ lệ | Tác động chính |
| :--- | ---: | ---: | :--- |
| **1. Gold có tool, submission rỗng (`G != []`, `S = []`)** | 636 | 41,17% | Điểm nghẽn #1: Mô hình trả lời bằng văn bản tự nhiên thay vì mở thẻ `<tool_call>`. |
| **2. Gold có tool, dừng sau khi mới chỉ `read`** | 412 | 26,67% | Điểm nghẽn #2: Gọi `read` thành công ở Turn 1 nhưng bỏ cuộc sớm, không gọi `write` hay `sys.ask_missing_info`. |
| **3. Gold có tool, gọi tool nhưng sai state** | 260 | 16,83% | Lệch tham số hoặc sai logic nghiệp vụ (229/260 mẫu bị phạt `USMR = 1`). |
| **4. Gold có tool, khớp hoàn toàn final state** | 126 | 8,16% | Đóng góp điểm số cốt lõi (tổng toàn run có 373 mẫu khớp final state). |
| **5. Gold rỗng, từ chối đúng (`G = []`, `S = []`)** | 65 | 4,21% | Từ chối đúng trên 65/111 mẫu Out-of-Scope (OOS). |
| **6. Gold rỗng, gọi nhầm tool (`G = []`, `S != []`)** | 46 | 2,98% | Ảo giác gọi tool trên 46/111 mẫu OOS khi bị kích thích bởi thông tin thời gian/địa điểm. |

Ba vấn đề gốc giải thích hơn 80% lỗi:
1. **Phản hồi bằng ngôn ngữ tự nhiên thay vì xuất thẻ công cụ (>60% lỗi):** 636 mẫu dừng ngay ở Turn 1 (`S = []`) và 412 mẫu dừng sau khi mới chỉ đọc đệm.
2. **Lặp lại lệnh đọc:** Dù đã giảm mạnh ở bản 3.2, xu hướng lặp lại lệnh `read` từng chiếm 11,8% số mẫu ở bản 3.0 khi chưa có chặn precheck.
3. **Nhiễu tiểu từ khẩu ngữ ASR:** Các từ như `"nha"`, `"nhé"`, `"giùm"` bị cắt nhầm vào chuỗi truy vấn khiến lệnh `read` trả về rỗng.

### 1.3. Bài học thực nghiệm then chốt từ Sandbox 3.1 và Sandbox 3.2

1. **Bài học từ Sandbox 3.1 — Phản ứng dây chuyền kép làm tăng `USMR`:**
   - *Thành công:* Chuyển chặn `repeated_read` lên `precheck` (`blocked = True`) đã giảm 86,56% số lượt gọi lặp thực thi (`182` $\rightarrow$ `41` mẫu) và giảm chạm trần 20 lượt (`85` $\rightarrow$ `62` mẫu).
   - *Hạn chế:* Chốt `read_without_action` kết hợp với `tool_name_without_call` tạo phản ứng dây chuyền trên 277 mẫu, ép mô hình gọi bừa lệnh `write` khi không có dữ liệu, đẩy `USMR` từ 16,31% lên 20,71% và làm hỏng 58 mẫu `state_match`. Đồng thời, thêm câu hướng dẫn chi tiết vào System Prompt (+151 input tokens) làm mất 13 mẫu từ chối đúng OOS.
2. **Bài học từ Sandbox 3.2 — Đánh đổi giữa an toàn state và bẫy dừng sớm (Premature Surrender):**
   - *Thành công:* Gỡ bỏ chốt `read_without_action` giúp đưa `USMR` về mức thấp kỷ lục 15,47% (tốt nhất trong toàn bộ các cấu hình) và giảm tỷ lệ chạm trần 20 lượt xuống 3,62% (56 mẫu).
   - *Hạn chế:* Việc thêm vế *"hoặc dừng lại nếu không tìm thấy đối tượng phù hợp"* (ở `empty_read`) và *"hoặc trả lời kết thúc nếu đã đủ thông tin"* (ở `repeated_read`) trong `self_healing.py` đã tạo lối thoát sớm cho mô hình 1.7B. Tỷ lệ dừng ngay sau `empty_read` tăng từ 9,0% (`3.0`) lên 22,9% (`3.2`), kéo chỉ số phục hồi lỗi `SHR` giảm từ 27,44% xuống 17,81%.

---

## 2. Sandbox 3.1 — Giải quyết ba vấn đề gốc

### 2.1. Ngăn mô hình trả lời bằng văn bản thay vì gọi công cụ

- **[x] Đã cập nhật trong `self_healing.py` và Sandbox History.md:**
  - Đã sửa câu `hint` của `empty_read` và `repeated_read` để điều hướng model gọi `sys.ask_missing_info` khi thiếu dữ kiện bắt buộc (thay vì câu nhắc cũ *"Dùng dữ liệu đã có để chọn bước tiếp theo"* khiến model 1.7B tự đoán tham số hoặc hỏi bằng văn bản).
- **[x] Đã cập nhật trong `sandbox.py` và kiểm thử tại `test_enhanced_sandbox.py`:**
  - Đã bổ sung 2 chốt kiểm tra trạng thái tất định (không bắt chữ hay kiểm tra dấu câu tiếng Việt) khi `calls == []` và `self_heal=True`, mỗi chốt kích hoạt tối đa 1 lần/mẫu khi `turn < max_turns`:
    1. **Tín hiệu 1 — Kiểm tra rò rỉ định danh Schema (`stop_trigger = "tool_name_without_call"`, `any(name in content for name in specs)`):** Chỉ kiểm tra trên phần `content` sau khi đã tách `<think>...</think>`, nhận diện lỗi quên bọc thẻ `<tool_call>` (như `train_0014`) mà không ảnh hưởng tới các mẫu từ chối ngoài phạm vi có nhắc tên hàm trong `<think>`.
    2. **Tín hiệu 2 — Chốt kiểm tra trạng thái `Read-Without-Action` (`stop_trigger = "read_without_action"`):** Khi phiên đã thực thi ít nhất một lệnh `read` (`bool(healer.seen_reads)`), nhưng chưa có lệnh `write` nào làm thay đổi state (`not state_changed_by_write`) và chưa gọi `sys.ask_missing_info` (`not asked_for_info`), nếu model định dừng (`calls == []`), runtime nhắc tối đa 1 lần để model gọi công cụ `write`, gọi `sys.ask_missing_info`, hoặc xác nhận kết thúc nếu yêu cầu chỉ cần tra cứu.

### 2.2. Chặn lệnh `read` lặp lại

- **[x] Đã cập nhật trong `system_prompt.py` và System Prompt History.md:**
  - Đã thêm ràng buộc phủ định chống `Confirmatory Tool Usage` vào `ENHANCED` System Prompt: *"Không gọi lại công cụ tra cứu với cùng tham số khi đã có kết quả từ lượt trước."*
- **[x] Đã cập nhật trong `self_healing.py` và kiểm thử tại `test_enhanced_sandbox.py`:**
  - Đã chuyển việc bắt `repeated_read` (`spec.get("kind") == "read" and call_key(call) in self.seen_reads`) lên tiền kiểm ở `precheck` (`blocked = True`), kèm câu `hint` mở đường thoát an toàn.
  - Khi `blocked = True`, `sandbox.py` không gọi `env.call()`, giữ sạch `env.get_tool_calls()` để không làm giảm Precision $P = \frac{M}{M+U}$ của `Contest Score`. Sau khi có một lệnh làm thay đổi state (`state_changed=True`), `seen_reads` được xóa để cho phép đọc lại trạng thái mới.

### 2.3. Loại tiểu từ khẩu ngữ khỏi tham số tìm kiếm

Không sử dụng danh sách cắt chuỗi cứng (tránh cắt nhầm tên riêng tiếng Việt), xử lý tổng quát qua 2 tầng:

- **[x] Đã cập nhật trong `system_prompt.py`:**
  - Đã bổ sung hướng dẫn trích xuất tham số tìm kiếm từ lời nói ASR có bảo vệ tên riêng: *"Khi trích xuất tham số tìm kiếm từ lời nói, giữ tên hoặc thực thể cần tìm và bỏ các tiểu từ khẩu ngữ cuối câu như "nha", "nhé", "giùm", "với" nếu chúng không thuộc tên riêng."*
- **[x] Đã cập nhật trong `self_healing.py` và `system_prompt.py`:**
  - Nhánh `empty_read` trong `observe` phát hiện khi hàm `read` có tham số lọc tùy chọn trả về rỗng `[]` và nhắc model: *"Kết quả rỗng với tham số tùy chọn ... Cân nhắc bỏ bớt bộ lọc nếu vẫn giữ đúng yêu cầu, hoặc gọi sys.ask_missing_info nếu thiếu dữ kiện bắt buộc và không tra cứu thêm được, không tự đoán tham số để gọi lệnh ghi."*

---

## 3. Sandbox 3.2 — Tinh chỉnh cơ chế

### 3.1. Tổng hợp luồng chuyển tiếp từ Sandbox 3.1 sang 3.2

1. **Các thành phần giữ lại:**
   - **Chặn `repeated_read` tại `precheck` (`blocked = True`):** Giảm 86,56% số lượt gọi lặp thực thi trong `ToolEnv` (`182` $\rightarrow$ `41` mẫu) và giảm chạm trần 20 lượt (`85` $\rightarrow$ `62` mẫu).
   - **Chốt `tool_name_without_call` tại `turn == 1`:** Bắt lỗi quên bọc thẻ `<tool_call>` ở lượt đầu (như `train_0014`), giúp cải thiện `Contest Score` (`6,73%` $\rightarrow$ `7,01%`) và `Exact Ordered` (`88` $\rightarrow$ `92` mẫu) trong mô phỏng đối chứng.
   - **Quy tắc lọc tiểu từ khẩu ngữ ASR (`"nha"`, `"nhé"`, `"giùm"`, `"với"`) và chống gọi lặp trong `ENHANCED` System Prompt:** Hỗ trợ trích xuất tham số tìm kiếm sạch hơn từ lời nói ASR.
2. **Các thành phần loại bỏ:**
   - **Loại bỏ chốt `read_without_action`:** Kích hoạt `416` lần ở `3.1` và tạo phản ứng dây chuyền kép trên `277` mẫu, ép model `1.7B` gọi bừa hàm `write` làm `USMR` tăng từ `16,31%` lên `20,71%` và mất `9` mẫu `Final State Match` ròng (`380` $\rightarrow$ `371`).
   - **Loại bỏ `tool_name_without_call` từ `turn >= 2`:** Tránh bắt nhầm tên công cụ khi model chỉ đang nhắc lại tên hàm vừa chạy ở Turn 1 trong câu trả lời kết thúc.
   - **Loại bỏ việc nhắc tên `sys.ask_missing_info` trong câu `hint` của `repeated_read` và `empty_read`:** Tránh ám thị khiến model gọi `sys.ask_missing_info` tràn lan (`23` $\rightarrow$ `130` mẫu) nhưng sai tham số, làm tăng `+83` False Positives ở `MI/Abs F1`.
   - **Loại bỏ câu liệt kê chi tiết `current_time`, `location`, `user_profile` ở mục 1 của `ENHANCED` System Prompt:** Tránh tăng `+151` input tokens ở Turn 1 và tránh kích thích model bám vào `location`/`current_time` để gọi nhầm công cụ trên `13 / 111` mẫu Gold rỗng (`G = []`).

### 3.2. Chi tiết triển khai trong Sandbox 3.2

- **[x] `sandbox.py`:** Xóa bỏ `read_without_action`; giới hạn `tool_name_without_call` chỉ chạy ở `turn == 1` (`if self_heal and turn == 1 and turn < max_turns and any(name in content for name in specs):`).
- **[x] `self_healing.py`:** Giữ chặn `repeated_read` tại `precheck` (`blocked = True`); đổi câu `hint` sang hướng dẫn thoát trung lập:
  - `repeated_read`: `"Lệnh tra cứu này đã chạy và state chưa đổi. Dùng dữ liệu đã có hoặc trả lời kết thúc nếu đã đủ thông tin, không tự đoán tham số để gọi lệnh ghi."`
  - `empty_read`: `"Kết quả rỗng với tham số tùy chọn ... Cân nhắc bỏ bớt bộ lọc nếu vẫn giữ đúng yêu cầu, hoặc dừng lại nếu không tìm thấy đối tượng phù hợp, không tự đoán tham số để gọi lệnh ghi."`
- **[x] `system_prompt.py`:** Rút gọn khối `1. NGUỒN DỮ LIỆU` về bản súc tích của `3.0`, giữ lại 2 dòng quy tắc lọc tiểu từ ASR và chống lặp tra cứu ở khối `2. QUY TRÌNH THỰC HIỆN`.

---

## 4. Sandbox 3.3 — Cấu hình tối ưu tinh gọn (Golden Lean Sandbox)

### 4.1. Tổng hợp luồng chuyển tiếp từ Sandbox 3.2 sang 3.3

1. **Các thành phần giữ lại:**
   - **Chặn `repeated_read` tại `precheck` (`blocked = True`):** Duy trì tỷ lệ gọi lặp thực thi ở mức thấp (1,75%) và hạn chế chạm trần 20 lượt (3,62%).
   - **Gỡ bỏ `read_without_action`:** Duy trì tỷ lệ `USMR` thấp ở mức 15,47% (tránh ép model gọi bừa lệnh `write`).
   - **Chốt `tool_name_without_call` tại `turn == 1`:** Tiếp tục hỗ trợ phát hiện lỗi quên bọc thẻ `<tool_call>` ở lượt đầu tiên.
2. **Các thành phần loại bỏ:**
   - **Loại bỏ câu `hint` của Sandbox 3.2 trong `self_healing.py`:** Vế *"hoặc trả lời kết thúc nếu đã đủ thông tin"* (`repeated_read`) và *"hoặc dừng lại nếu không tìm thấy đối tượng phù hợp"* (`empty_read`) tạo lối thoát sớm cho model `1.7B`, khiến tỷ lệ dừng ngay sau `empty_read` tăng vọt lên 22,9% (so với 9,0% ở bản 3.0) và kéo `SHR` giảm từ 27,44% xuống 17,81%.
   - **Loại bỏ hoàn toàn cơ chế dò tiếp nối cưỡng bức (Prefix Continuation Probe):** Triệt tiêu hoàn toàn rủi ro ép gọi bừa lệnh `write` làm tăng `USMR` ở Turn $\ge 2$. Thực nghiệm trên trace cho thấy các mẫu trượt thẻ ở mô hình gốc vốn phân vân với xác suất thấp ($< 0,74$), do đó bài toán gọi công cụ cần được giải quyết triệt để ở tầng huấn luyện trọng số (SFT) thay vì áp dụng các cơ chế can thiệp hình thức (assurance theatre) ở runtime.

### 4.2. Loại bỏ câu hint gây hại trong self_healing.py

- **[x] `self_healing.py`:** Đã loại bỏ hoàn toàn các vế câu hint gây hại của Sandbox 3.2, khôi phục nội dung biến `hint` của `repeated_read` và `empty_read` về nguyên bản ngắn gọn của Sandbox 3.0 (vẫn giữ cơ chế chặn `repeated_read` ở `precheck`):
  - `repeated_read`: `"Lệnh tra cứu này đã chạy và state chưa đổi. Dùng dữ liệu đã có để chọn bước tiếp theo, không lặp lại lệnh đọc."` (Loại bỏ vế *"hoặc trả lời kết thúc nếu đã đủ thông tin"*).
  - `empty_read`: `"Kết quả rỗng với tham số tùy chọn [...]. Cân nhắc bỏ bớt bộ lọc nếu vẫn giữ đúng yêu cầu, không tự đoán tham số."` (Loại bỏ vế *"hoặc dừng lại nếu không tìm thấy đối tượng phù hợp"*).
  - **Mục tiêu thiết kế:** Triệt tiêu lối thoát dừng sớm sau khi tra cứu rỗng, kéo tỷ lệ dừng ngay sau `empty_read` từ 22,9% trở về mức 9,0% và phục hồi `SHR`. (Thực tế trên benchmark Sandbox 3.3* với `llama.cpp` và bật thinking, số lượt tương tác và số sự kiện lỗi phát sinh tăng lên 1.283 lỗi, đạt `SHR` thực tế 18,08% với 232 ca phục hồi thành công).
