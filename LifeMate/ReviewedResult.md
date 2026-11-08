## 1. Phân rã toàn bộ 1.545 mẫu Benchmark & Bằng chứng định lượng trên `ablation_03_results`

### 1.1. Phân hoạch tổng thể 1.545 mẫu toàn bộ tập Train

Phân hoạch toàn bộ **1.545 mẫu** của tập Train trên `ablation_03_results` ([traces](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/kaggle/ablation_03_results/traces)) cho thấy toàn bộ 1.545 mẫu rơi vào 6 nhóm loại trừ nhau hoàn toàn (`630 + 355 + 318 + 131 + 79 + 32 = 1.545 mẫu`):

| Phân nhóm (trên tổng số 1.545 mẫu tập Train) | Số mẫu / Tổng tập Train | Tỷ lệ trên 1.545 mẫu | Tác động lên `Final state match` & `Contest Score` |
| :--- | :---: | :---: | :--- |
| **1. Không gọi tool trong khi Gold yêu cầu gọi (`G != []`, `S = []`)** | **630 / 1.545** | **40.78%** | **Điểm nghẽn #1:** `Contest Score = 0.0` ở cả 630 mẫu. Trong 630 mẫu này: `147 / 630` mẫu (`9.51%` toàn tập Train) có `state_hash` khớp giả tạo vì Gold chỉ gồm lệnh `read` hoặc `sys.ask_missing_info` (không đổi state), còn `483 / 630` mẫu (`31.26%` toàn tập Train) lệch `state_hash`. |
| **2. Có gọi tool nhưng chưa chạm vào State (`S != []`, `expected_delta > 0`, `observed_delta = 0`)** | **355 / 1.545** | **22.98%** | **Điểm nghẽn #2:** Trong 355 mẫu này, `337 / 355` mẫu (`94.93%` nhóm 2) tự dừng bình thường sau khi mới chỉ gọi hàm `read` ở Turn 1 rồi quay ra nói chuyện/hỏi xác nhận bằng lời ở Turn 2 thay vì gọi hàm `write`. |
| **3. Gọi tool và làm thay đổi sai/thiếu State (`S != []`, `observed_delta > 0`, lệch `state_hash`)** | **318 / 1.545** | **20.58%** | Trong 318 mẫu này: `187 / 318` mẫu sửa nhầm khóa (`SSR = 0, USMR = 1`), `52 / 318` mẫu sửa đúng một phần (`0 < SSR < 1`), và `74 / 318` mẫu chạm trần 20 lượt. |
| **4. Có gọi tool và khớp hoàn toàn `state_hash` (`S != []`, `state_match = True`)** | **131 / 1.545** | **8.48%** | Đóng góp chính vào `Contest Score` (`210 = 131 + 79` mẫu đúng thực chất trên 1.545 mẫu), nhưng nhiều mẫu trong nhóm 131 mẫu này bị giảm Precision $P = \frac{M}{M+U}$ do dư các lệnh `read` lặp hoặc lệnh lỗi trong `env.get_tool_calls()`. |
| **5. Từ chối đúng ngoài phạm vi (`G = []`, `S = []`)** | **79 / 1.545** | **5.11%** | Đạt điểm tuyệt đối (`1.0`). Model từ chối đúng `79 / 111` mẫu (`71.17%`) có nhãn Gold rỗng (`G = []`) trên toàn tập Train. |
| **6. Gọi nhầm tool khi đáng lẽ phải từ chối (`G = []`, `S != []`)** | **32 / 1.545** | **2.07%** | Bị phạt `0.0` do ảo giác gọi tool trên `32 / 111` mẫu (`28.83%`) ngoài phạm vi (`G = []`). |

### 1.2. Bằng chứng định lượng theo trạng thái dừng (`calls == []`) và nhãn Gold

Trước hết, phân loại toàn bộ **1.545 nhãn Gold của tập Train** theo bản chất chuỗi lệnh cần đạt (`1.093 + 217 + 124 + 111 = 1.545 mẫu`):
- **Nhóm Gold cần kết thúc bằng `write` (`has_write`):** `1.093 / 1.545` mẫu (**70.74%** toàn tập Train)
- **Nhóm Gold cần kết thúc bằng `sys.ask_missing_info` (`has_ask`):** `217 / 1.545` mẫu (**14.05%** toàn tập Train)
- **Nhóm Gold chỉ đọc (`read_only`):** `124 / 1.545` mẫu (**8.03%** toàn tập Train)
- **Nhóm Gold từ chối ngoài phạm vi (`empty`, `G = []`):** `111 / 1.545` mẫu (**7.18%** toàn tập Train)

$\Rightarrow$ Như vậy, **1.310 / 1.545 mẫu (`84.79%` toàn bộ tập Train)** chỉ thực sự hoàn tất khi model thực hiện ít nhất một lệnh **`write`** (`1.093` mẫu) hoặc gọi **`sys.ask_missing_info`** (`217` mẫu).

Khi đối chiếu với thời điểm model dừng (`calls == []`) trong [`sandbox.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/sandbox.py#L147-L172) trên 1.545 mẫu của `ablation_03_results`:

| Trạng thái phiên khi model dừng (`calls == []`) | Tổng số mẫu rơi vào trạng thái này | Gold là `has_write` (trên 1.093 mẫu) | Gold là `has_ask` (trên 217 mẫu) | Gold là `read_only` (trên 124 mẫu) | Gold là `empty` (trên 111 mẫu) | Tỷ lệ dừng sai trong trạng thái này |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Dừng ngay ở Turn 1 mà không gọi tool nào (`S = []`)** | **709 / 1.545 mẫu** (`45.89%` tập Train) | `474 / 709` (`66.85%`) | `102 / 709` (`14.39%`) | `54 / 709` (`7.62%`) | `79 / 709` (`11.14%` — *Dừng đúng*) | **630 / 709 mẫu (`88.86%`) dừng sai** |
| **Dừng sau khi mới chỉ gọi hàm `read` (`S` chỉ chứa `read`)** | **478 / 1.545 mẫu** (`30.94%` tập Train) | `345 / 478` (`72.18%`) | `52 / 478` (`10.88%`) | `59 / 478` (`12.34%` — *Dừng đúng*) | `22 / 478` (`4.60%`) | **419 / 478 mẫu (`87.66%`) dừng sai** (trong đó `397 / 478 = 83.05%` thiếu lệnh `write` hoặc `ask`) |

### 1.3. Bằng chứng thực nghiệm từ Traces quy về 3 vấn đề gốc

1. **Vấn đề gốc 1 — Model dùng ngôn ngữ tự nhiên để phản hồi/hỏi lại thay vì gọi tool (`985 / 1.545` mẫu = `63.75%` toàn bộ tập Train, gồm `630` mẫu ở Turn 1 + `355` mẫu ở Turn 2):**
   - **Ở Turn 1 (`619 / 630` mẫu = `98.25%` trong nhóm bỏ sót hoàn toàn tool `G != [], S = []`):**
     - `619 / 630` mẫu dừng ngay ở Turn 1 vì model sinh văn bản tiếng Việt thay vì thẻ `<tool_call>` (chỉ có `11 / 630` mẫu là do lỗi cú pháp thẻ hoặc chạm giới hạn token):
     - *Hỏi người dùng bằng lời thay vì gọi `read` tra ID:* `train_0039` (ASR yêu cầu tìm tin nhắn trong nhóm *"Dự án X"*, model trả lời *"Hãy cho tôi biết ID cuộc trò chuyện (`chat_id`) của nhóm 'Dự án X'..."* thay vì gọi `chat_ott.list_chats`), `train_0047` (hỏi người dùng thiết bị nào thay vì gọi `smart_home.get_status`).
     - *Tự tính xong tham số nhưng hỏi xác nhận thay vì gọi `write`:* `train_0027` (tự tính ra `2026-11-18T19:45:00+07:00` trong câu trả lời nhưng hỏi *"Bạn muốn tạo một cảnh báo... vào giờ tối mai?"* thay vì gọi `reminders.create`).
     - *Nhắc tên hàm trong văn xuôi mà quên mở thẻ `<tool_call>` (`Tool Format Collapse`):* `train_0014` (viết *"Mình sẽ dùng công cụ `smart_home.get_status` với tham số `room`..."* không bọc thẻ `<tool_call>`).
   - **Ở Turn 2 sau khi đã gọi `read` (`337 / 355` mẫu = `94.93%` trong nhóm có gọi tool nhưng chưa chạm vào State):**
     - Trên tổng số `478 / 1.545` mẫu mà model chỉ gọi các hàm `read` rồi dừng, có tới **`345 / 478` mẫu (`72.18%`)** nhãn Gold yêu cầu gọi tiếp hàm `write` và **`52 / 478` mẫu (`10.88%`)** nhãn Gold yêu cầu gọi tiếp `sys.ask_missing_info`.
     - `train_0004`: Turn 1 gọi `smart_home.get_status(room="phòng ngủ")`, lấy được `light_bedroom2`. Sang Turn 2 hỏi *"Bạn muốn giảm độ sáng của đèn phòng ngủ nhỏ xuống mức nào?"* thay vì gọi `smart_home.light_set(device_id="light_bedroom2", brightness=50)`.
     - `train_0033`: Turn 1 gọi `calendar.list_events({})`, thấy lịch họp `19:30`. Sang Turn 2 tự tính `17:30` trong văn bản rồi hỏi *"Bạn muốn nhắc báo thức trước lịch họp này không?"* thay vì gọi `alarm.create`.
   - **Trên nhóm thiếu dữ kiện bắt buộc (`216 / 217` mẫu thất bại trên tổng số `217` mẫu có nhãn Gold là `sys.ask_missing_info` = `99.54%`):**
     - Trên toàn bộ `1.545` mẫu tập Train, có `217 / 1.545` mẫu (`14.05%`) Gold yêu cầu gọi `sys.ask_missing_info`. Tuy nhiên model chỉ gọi hàm này ở `23 / 1.545` mẫu, trùng tên hàm với Gold ở `3 / 217` mẫu, và khớp đúng cả `(tool_name, params)` ở **đúng `1 / 217` mẫu (`0.46%`)**.
     - Trong `216 / 217` mẫu `sys.ask_missing_info` bị bỏ sót: **`102 / 217` mẫu (`47.00%`)** model hỏi người dùng bằng văn bản ngay ở Turn 1 (`S = []`, ví dụ `train_0026`), **`52 / 217` mẫu (`23.96%`)** model gọi hàm `read` ở Turn 1 rồi hỏi người dùng bằng văn bản ở Turn 2, và **`60 / 217` mẫu (`27.65%`)** model gọi `read` xong tự đoán bừa tham số để gọi hàm `write`.

2. **Vấn đề gốc 2 — Model lặp lại lệnh `read` nhiều lần (`183 / 1.545` mẫu = `11.84%` toàn tập Train, với `664 / 3.214` lượt có gọi tool ở `ablation_03_results`):**
   - Trong [`metrics_eval.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/metrics_eval.py#L431-L453), `Action Score` tính $F_1$ trực tiếp trên `submission["tool_calls"] = env.get_tool_calls()` với Precision $P = \frac{M}{M+U}$ ($M$ là số lệnh khớp Gold, $U$ là số lệnh gọi thừa không khớp Gold).
   - Ở bản chạy `ablation_03_results`, `precheck` mới chỉ chặn (`blocked = True`) các lệnh `write` thất bại lặp lại, còn các lệnh `read` lặp lại vẫn đi qua `env.call()` rồi mới nhắc ở `observe`. Điều này làm toàn bộ `664` lượt `read` lặp (trên `183 / 1.545` mẫu) bị ghi nhận vào `env.get_tool_calls()`, làm phình mẫu số $M+U$ và kéo tụt `Contest Score`.

3. **Vấn đề gốc 3 — Nhiễu tiểu từ cuối câu của ASR trong tham số tìm kiếm:**
   - Khi ASR chép lời nói tự nhiên không có dấu câu (trên `1.545` mẫu), model thường cắt cả tiểu từ khẩu ngữ cuối câu (`"nha"`, `"nhé"`, `"giùm"`, `"với"`) đưa vào tham số truy vấn của các hàm `read`.
   - Ví dụ `train_0018` (ASR: *"GỌI GIÙM TÔI BỐ NHA"*): Turn 1 gọi `contacts.search(query="Bố Nha")` nhận về `[]` (`empty_read`), sang Turn 2 kết luận không tìm thấy liên hệ `"Bố Nha"` và dừng luôn thay vì thử lại với từ khóa gốc `"Bố"` hoặc bỏ bộ lọc (`{}`).

### 1.4. Đánh giá kết quả thực nghiệm `ablation_03_1_results` (`+ Sandbox 3.1 Runtime Checks`)

Đối chiếu trực tiếp **1.545 mẫu** giữa [`ablation_03_results`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/kaggle/ablation_03_results/benchmark_diagnostics.json) (`+ Sandbox`) và [`ablation_03_1_results`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/kaggle/ablation_03_1_results/benchmark_diagnostics.json) (`+ Sandbox 3.1`) cùng mô phỏng đối chứng trên traces giải thích chính xác tại sao các chỉ số kiểm soát vòng lặp và tác vụ `write` đạt mức tốt nhất nhưng các chỉ số tổng hợp ở Table 1 (`Contest Score`, `USMR`, `SHR`, `MI/Abs F1`) lại giảm:

#### A. Vì sao nhóm chỉ số Chống lặp, Kiểm soát vòng lặp và Tác vụ `write` đạt mức tốt nhất?

1. **Chặn lặp thực thi trong `submission["tool_calls"]` giảm 86.56% số lượt gọi trùng (`662` $\rightarrow$ `89` lượt):**
   - Trong `submission["tool_calls"]` (`env.get_tool_calls()`), số mẫu chứa lệnh gọi lặp thực thi giảm từ **`182 / 1.545` mẫu (`11.78%`, `662` lượt trùng) ở `3.0` xuống chỉ còn `41 / 1.545` mẫu (`2.65%`, `89` lượt trùng) ở `3.1`** (trong đó 89 lượt này là các lần đọc lại hợp lệ sau khi state đã thay đổi).
   - Trên Table 2 của [`baseline_benchmark.tex`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/kaggle/baseline_benchmark.tex#L70-L71), chỉ số này đã được tách thành 2 dòng tường minh: `Repeated tool calls (attempted)` (`196 / 1.545` mẫu = `12.69%`, phản ánh xu hướng gọi lặp của LLM bao gồm cả lệnh bị `precheck` chặn) và `Repeated tool calls (executed)` (`41 / 1.545` mẫu = `2.65%`, phản ánh số mẫu thực sự chạy lệnh lặp vào `ToolEnv`).
2. **Giảm chạm trần 20 lượt và giảm bỏ sót tool xuống mức thấp nhất toàn bảng:**
   - Số mẫu chạm trần 20 lượt (`Reached 20-turn limit`) giảm từ **`85 / 1.545` mẫu (`5.50%`) xuống `62 / 1.545` mẫu (`4.01%`)**.
   - Số mẫu không gọi tool nào (`No submitted tool calls`) giảm từ **`709 / 1.545` (`45.89%`) xuống `673 / 1.545` (`43.56%`)**, và số mẫu bỏ sót tool khi Gold yêu cầu (`No calls, gold has calls`) giảm từ **`630 / 1.545` (`40.78%`) xuống `609 / 1.545` (`39.42%`)**.
3. **Số mẫu giải đúng hoàn toàn các tác vụ `write` thay đổi trạng thái (trên `1.167` mẫu của `DDR`) tăng mạnh nhất:**
   - Trên `1.167 / 1.545` mẫu yêu cầu thay đổi state, số mẫu khớp hoàn toàn `state_hash` tăng từ **`37 / 1.167` (Full) và `45 / 1.167` (Target) ở `3.0` lên `47 / 1.167` (Full) và `59 / 1.167` (Target) ở `3.1`** — giải đúng thêm **`+10` mẫu `write` phức tạp** (tăng **+27.03%** tương đối).

#### B. Vì sao các Metrics tổng hợp ở Table 1 (`Contest Score`, `USMR`, `SHR`, `MI/Abs F1`) lại giảm?

1. **Phản ứng dây chuyền kép giữa `read_without_action` và `tool_name_without_call` (`277 / 1.545` mẫu) làm hỏng `58` mẫu `state_match` và đẩy `USMR` từ `16.31%` lên `20.71%`:**
   - Thống kê chuỗi kích hoạt 2 chốt dừng trên `1.545` mẫu của `3.1`: không kích hoạt chốt nào ở `886 / 1.545` mẫu, chỉ kích hoạt `tool_name_without_call` ở `243 / 1.545` mẫu, chỉ kích hoạt `read_without_action` ở `139 / 1.545` mẫu, và **kích hoạt nối tiếp cả 2 chốt ở `277 / 1.545` mẫu** (`193` mẫu theo chiều `read_without_action` $\rightarrow$ `tool_name_without_call` và `84` mẫu theo chiều ngược lại).
   - *Cơ chế phản ứng dây chuyền:* Ở Turn 1 model gọi hàm `read`; sang Turn 2 model định dừng (`calls = []`) thì bị `read_without_action` chặn lại kèm câu `hint` có chữ `"sys.ask_missing_info"`. Ở Turn 3, khi model viết câu giải thích bằng lời có nhắc lại tên hàm vừa chạy ở Turn 1 (`contacts.search` 37 lần, `smart_home.get_status` 24 lần) hoặc nhắc lại chính chữ `sys.ask_missing_info` (44 lần) trong `hint`, chốt `tool_name_without_call` lại kích hoạt tiếp ở Turn 3 ép model sinh `<tool_call>`. Bị ép 2 lượt liên tiếp, sang Turn 4 model `1.7B` gọi bừa một hàm `write`, làm mất `58` mẫu đang khớp `state_hash` (trong đó `37 / 58` mẫu thuộc nhóm không được đổi state: `16` mẫu Gold `has_ask`, `13` mẫu `read_only`, `8` mẫu `empty`) và làm `184 / 1.545` mẫu chuyển từ `USMR = 0` sang `USMR = 1`.
   - *Bằng chứng mô phỏng đối chứng khi tách riêng từng chốt dừng trên tập 1.545 traces của `3.1`:*

| Cấu hình đối chứng trên `3.1` (1.545 mẫu) | Contest Score $\uparrow$ | Final State Match $\uparrow$ | Exact Ordered $\uparrow$ | SSR $\uparrow$ | USMR $\downarrow$ | MI/Abs F1 $\uparrow$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **3.1 hiện tại (Giữ cả 2 chốt dừng)** | 6.96 | 371 / 1.545 | 90 / 1.545 | 26.61 | 20.71 | 11.70 |
| **Bỏ `read_without_action` (Chỉ giữ `tool_name_without_call`)** | **7.01** | **380 / 1.545** | **92 / 1.545** | **27.00** | 17.73 | **12.23** |
| **Bỏ `tool_name_without_call` (Chỉ giữ `read_without_action`)** | 6.71 | 375 / 1.545 | 87 / 1.545 | 26.43 | 15.60 | 11.87 |
| **Bỏ cả 2 chốt dừng** | 6.73 | **380 / 1.545** | 88 / 1.545 | 26.68 | **14.76** | 12.08 |

   - Bảng trên chứng minh: **`read_without_action` gây hại trên mọi chỉ số** (bỏ chốt này giúp hồi phục ngay `380 / 1.545` mẫu `Final State Match` và giảm `USMR` gần `3%`), trong khi **`tool_name_without_call` có ích ở Turn 1** (`Contest Score` tăng từ `6.73` lên `7.01`, `Exact Ordered` từ `88` lên `92`, `SSR` từ `26.68%` lên `27.00%`) nhưng gây tác dụng phụ khi chạy ở `Turn > 1`.

2. **Dịch chuyển System Prompt ở Turn 1 (`+151` input tokens) kết hợp với ám thị `sys.ask_missing_info` (`23` $\rightarrow$ `130` mẫu) làm mất `13` mẫu `True Abstention` (`tp: 79` $\rightarrow$ `66`):**
   - Bản `3.0` chạy với System Prompt cũ (`5.510` input tokens trung bình ở Turn 1), còn bản `3.1` chạy với System Prompt mới (`5.661` input tokens ở Turn 1, dài hơn `+151` tokens do thêm 3 câu hướng dẫn chi tiết).
   - Kiểm tra trực tiếp các mẫu ngoài phạm vi (`G = []`) bị mất điểm ngay tại Turn 1 (`train_0057`, `train_0082`, `train_0248`, `train_0530`, `train_0565`, `train_0602`, `train_0606`) cho thấy: chính câu nhắc *"Dùng context để lấy thời gian hiện tại (current_time), vị trí (location) và hồ sơ người dùng (user_profile)"* đã kích thích model `1.7B` bám vào `location`/`current_time` trong `context` để gọi `smart_home.get_status` hoặc `calendar.list_events` ở Turn 1 thay vì từ chối.
   - Cộng thêm việc nhắc tên `sys.ask_missing_info` trong cả 3 câu `hint` khiến model gọi hàm này tăng từ `23 / 1.545` mẫu lên `130 / 1.545` mẫu (nhưng truyền lệch tập `params`), bộ đếm `MI/Abs F1` chuyển từ `tp = 79, fp = 651, fn = 249` (`14.93%`) sang `tp = 66, fp = 734, fn = 262` (`11.70%`). Riêng `13 / 111` mẫu `True Abstention` bị mất đã làm `Contest Score` hụt $13 / 1.545 = \mathbf{0.84\%}$ — giải thích toàn bộ mức giảm `0.68%` từ `7.64%` xuống `6.96%`.

3. **Bản chất sự sụt giảm của `SHR` (`27.44% [309/1.126]` $\rightarrow$ `22.30% [188/843]`): Cắt bỏ `128` sự kiện "phục hồi ảo" từ vòng lặp Ping-Pong và giảm 20% tổng lỗi tồn đọng:**
   - **Ở Turn 1 (phục hồi lỗi lần đầu, không bị nhiễu bởi vòng lặp):** Bản `3.1` đạt **`52 / 164` (`31.71%`)**, tương đương bản `3.0` (**`47 / 148` = `31.76%`**) và có số ca tự sửa thành công ngay sau Turn 1 cao hơn (`52` so với `47` ca).
   - **Ở các lượt lặp từ lần thứ 2 trở đi trong cùng một mẫu (`>= 2 recovered events / sample`):** Ở bản `3.0`, do `repeated_read` chưa bị chặn ở `precheck` (`blocked = False`), các mẫu bị kẹt trong vòng lặp Ping-Pong giữa `read(filter)` (`empty_read`) và `read({})` (`recovered = True`) đã tạo ra tới **`186 / 309` sự kiện `recovered` trùng lặp** (ví dụ riêng mẫu `train_1265` được cộng `+7` lần `recovered`, các mẫu `train_0231`, `train_0414`, `train_0760`, `train_1593` mỗi mẫu cộng `+5` lần). Sang bản `3.1`, khi [`precheck`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/self_healing.py#L53-L57) chặn đứng `repeated_read` (`blocked = True`), vòng lặp Ping-Pong bị cắt ngay từ lần thứ 2, làm số sự kiện `recovered` trùng lặp giảm từ **`186` xuống `58` (`-128` sự kiện lặp ảo — khớp trực tiếp với độ giảm tử số `309 - 188 = 121`)**.
   - **Xét trên mẫu số cố định toàn tập ($N = 1.545$ mẫu):** Tổng số lỗi không phục hồi được ($N_{\text{errors}} - N_{\text{recovered}}$) ở `3.1` giảm xuống còn **`655` lỗi (`0.42` lỗi/mẫu)** — thấp nhất toàn bảng (giảm `19.83%` so với `817` lỗi = `0.53` lỗi/mẫu của `3.0`, và giảm `38.44%` so với `1.064` lỗi = `0.69` lỗi/mẫu của Baseline). *(Lưu ý: điều kiện `record["call"]["name"] != ASK_TOOL` trong [`recovery_events`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/metrics_eval.py#L154) thực tế chỉ gặp `8` lần model gọi `sys.ask_missing_info` ngay sau `empty_read` ở `3.1`, trong đó chỉ có `1` lần Gold có `ask`, nên giữ nguyên `metrics_eval.py`).*

---

### 1.5. Đánh giá kết quả thực nghiệm `ablation_03_2_results`

Đối chiếu mẫu-đối-mẫu giữa [Sandbox 3.0](kaggle/ablation_03_results/), [Sandbox 3.1](kaggle/ablation_03_1_results/) và [Sandbox 3.2](kaggle/ablation_03_2_results/) trên 1.545 mẫu với cùng 5.036 phiên âm ASR, context 16.384 token và không đặt trần output riêng mỗi lượt.

#### A. Các vấn đề đã cải thiện đúng theo thiết kế (Lập mốc tốt nhất toàn bảng)

1. **Loại bỏ hiệu ứng ám thị `sys.ask_missing_info` và hành vi gọi bừa hàm `write`:**
   - Số mẫu dừng vì gọi `sys.ask_missing_info` giảm thẳng từ **130 mẫu (`3.1`) xuống 20 mẫu (`3.2`)** — trở về mức tự nhiên của bản `3.0` (**23 mẫu**).
   - Nhờ gỡ bỏ chốt `read_without_action`, tỷ lệ sửa đổi trạng thái không an toàn (**`USMR`**) giảm mạnh **5,24 điểm phần trăm** (từ **20,71%** ở `3.1` xuống **15,47%** ở `3.2`, tốt hơn cả **16,31%** của `3.0`). Có 189 mẫu chuyển từ có sang không có thay đổi ngoài ý muốn và 108 mẫu chuyển theo chiều ngược lại so với `3.1`.
   - Số lượng sự kiện gọi nhầm (`boundary FP` của `Missing-Info & Abstention F1`) giảm từ **734 mẫu (`3.1`) về 654 mẫu (`3.2`)** (tương đương mức **651 mẫu** của `3.0`), giúp `MI/Abs F1` phục hồi từ **11,70%** lên **12,42%** (trên 111 mẫu Gold rỗng, số mẫu không thực thi tool tăng từ 64 lên 65).
2. **Kiểm soát vòng lặp và tiết kiệm chi phí suy luận tốt nhất trong cả 6 cấu hình:**
   - `Repeated tool calls (executed)`: giảm từ **41 mẫu (`3.1`) xuống 27 / 1.545 mẫu (1,75% ở `3.2`)** (so với **182 mẫu** ở `3.0`). Lệnh đã thực thi có thể bao gồm lượt đọc lại hợp lệ sau khi state thay đổi.
   - `Repeated tool calls (attempted)` (tính cả lệnh bị chặn ở `precheck`): giảm từ **196 mẫu (`3.1`) xuống 148 / 1.545 mẫu (9,58% ở `3.2`)** (so với **183 mẫu** ở `3.0`).
   - `Reached 20-turn limit`: giảm từ **62 mẫu (`3.1`) xuống 56 mẫu (3,62% ở `3.2`)** — thấp nhất toàn bảng (so với **85 mẫu** ở `3.0`). Số mẫu chạm giới hạn context tăng từ 6 lên 7 và cả hai run không có mẫu dừng vì lỗi parse output.
   - Tổng số lượt suy luận toàn tập giảm từ **6.965 lượt (`3.1`)** và **5.983 lượt (`3.0`)** xuống **5.412 lượt (`3.2`)**. Input cộng dồn qua các lượt giảm từ **33.987 xuống 26.677 token/mẫu**; output cộng dồn giảm từ **1.307 xuống 1.061 token/mẫu** (thấp nhất từ Baseline đến nay).
3. **`DDR` về tỷ lệ tương đối đạt mức thấp nhất toàn bảng (`8,33%`):**
   - Giảm mạnh từ **20,34%** (`3.1`) và **17,78%** (`3.0`) xuống **8,33%** (`3.2`).

#### B. Các vấn đề còn tồn đọng và kiểm chứng nguyên nhân làm giảm `Contest Score` (`6,96%` $\rightarrow$ `6,66%`)

Mặc dù `Final state match` tăng ròng từ **371 (`3.1`) lên 373 (`3.2`)** (gồm 53 mẫu từ sai sang đúng và 51 mẫu theo chiều ngược lại), điểm `Contest Score` ước tính giảm từ **6,96% xuống 6,66%**, `SSR` giảm từ **26,61% xuống 26,03%** và `Exact ordered tool calls` giảm từ **90 xuống 87**. Kiểm chứng trực tiếp trên các trace cho thấy 4 cơ chế nhân quả cụ thể:

1. **Vế câu *"hoặc dừng lại / hoặc trả lời kết thúc"* trong [`self_healing.py`](self_healing.py) làm model bỏ cuộc sớm (Premature Surrender), kéo `SHR` từ `27,44%` (`3.0`) $\rightarrow$ `22,30%` (`3.1`) $\rightarrow$ `17,81%` (`3.2`):**
   - Trong `self_healing.py`, bản `3.2` bỏ nhắc `sys.ask_missing_info` nhưng thêm vế *"hoặc dừng lại nếu không tìm thấy đối tượng phù hợp"* (ở `empty_read`) và *"hoặc trả lời kết thúc nếu đã đủ thông tin"* (ở `repeated_read`).
   - Phân phối hành động ở lượt ngay sau sự kiện `empty_read` chứng minh model `1.7B` coi vế này là lối thoát sớm thay vì nỗ lực tự sửa lỗi:
     | Phiên bản | Tổng sự kiện `empty_read` | Lượt kế tiếp: **Dừng ngay (`0 calls`)** | Lượt kế tiếp: **Thử gọi tool khác** | Số lần phục hồi thành công (`SHR` trên `empty_read`) |
     | :--- | :---: | :---: | :---: | :---: |
     | **Sandbox 3.0** | 1.073 | **97 lần (9,0%)** | **942 lần (87,8%)** | **303 / 1.073 (28,2%)** |
     | **Sandbox 3.1** | 766 | 182 lần (23,8%) | 575 lần (75,1%) | 176 / 766 (23,0%) |
     | **Sandbox 3.2** | 676 | **155 lần (22,9%)** | **520 lần (76,9%)** | **132 / 676 (19,5%)** |
   - Tỷ lệ dừng ngay lập tức (`0 calls`) sau `empty_read` ở `3.2` là **22,9%**, cao gấp **2,5 lần** so với mức **9,0%** của `3.0`.
2. **Sự kiện `not_done` (gọi hàm `write` thất bại) bị lặp lại lệnh lỗi làm sụp tỷ lệ phục hồi `not_done` từ `15,6%` (`3.1`) xuống `3,7%` (`3.2`):**
   - Khi tách riêng 2 nhóm sự kiện trong `SHR` (`empty_read` và `not_done`): ở `3.1`, nhóm `not_done` phục hồi được **12 / 77 sự kiện (15,6%)** với **0 lần** lặp lại đúng lệnh `write` vừa lỗi.
   - Ở `3.2`, nhóm `not_done` chỉ phục hồi được **3 / 82 sự kiện (3,7%)** vì có tới **38 / 82 lần (46,3%)** ngay ở lượt sau khi lệnh `write` báo lỗi (ví dụ ví điện tử không đủ số dư ở `train_0313`), model gọi lặp lại y hệt lệnh `write` vừa thất bại (`called_exact_same_failed_call = 38`). Do `has_repeated_read_call` trong `self_healing.py` chỉ chặn lệnh lặp có `kind == "read"`, các lệnh `write` lỗi lặp lại này vẫn đi qua và bị `metrics_eval.py` đánh dấu `same_failed_call` (`recovered = False`).
3. **Sự đánh đổi hai mặt khi gỡ bỏ `read_without_action`: Cứu được `USMR` nhưng mất 14 mẫu `write` thành công (làm giảm `SSR` và số mẫu tuyệt đối của `DDR` từ `47/59` xuống `33/36`):**
   - Khi đối chiếu `3.1 -> 3.2`, bản `3.2` mất **30 mẫu `state_match` thuộc nhóm `write`** (gỡ lại 18 mẫu, âm ròng `-12` mẫu `write`). Trên 1.167 mẫu cần thay đổi state của `DDR`, số mẫu khớp state bản `full` giảm từ **47 xuống 33 mẫu** và bản `target` giảm từ **59 xuống 36 mẫu**.
   - Trên 508 mẫu chỉ thực thi `read` ở `3.2`, Gold cần `write` ở **368 mẫu** và cần `sys.ask_missing_info` ở **56 mẫu** (tăng mạnh so với **225 mẫu** và **29 mẫu** tương ứng ở `3.1`). Ngoài ra, số mẫu bỏ sót toàn bộ tool khi Gold yêu cầu (`No calls, gold has calls`) tăng từ **609 lên 636 mẫu** (153 mẫu bắt đầu gọi tool và 180 mẫu chuyển sang không gọi tool).
4. **Tác động của `+73` token mới còn giữ lại trong [`system_prompt.py`](system_prompt.py) ngay tại Turn 1 (Giải thích vì sao `MI/Abs F1` của `3.2` đạt `12,42%`, vẫn thấp hơn `14,93%` của `3.0`):**
   - So với `3.0` (`tp = 79`, `fp = 651`, `fn = 249`), bản `3.2` đã kéo `fp` về `654` nhưng vẫn hụt **14 mẫu `tp`** (`tp = 65`, `fn = 263`). Ngoài ra, trong 217 mẫu có Gold là `sys.ask_missing_info`, số mẫu model gọi cùng tên tool giảm từ 23 xuống 3 và số mẫu khớp cả lời gọi giảm từ 3 xuống 0.
   - Kiểm chứng tại **Turn 1** (trước khi bất kỳ cơ chế `self_healing` hay `sandbox` nào chạy, nơi khác biệt duy nhất giữa `3.0` và `3.2` là 2 dòng quy tắc mới trong mục `2. QUY TRÌNH THỰC HIỆN` của `system_prompt.py` làm tăng `+73` input token từ `5.510` lên `5.583`):
     - Có **1.530 / 1.545 mẫu** thay đổi chuỗi suy luận ở Turn 1 và **466 / 1.545 mẫu (30,2% toàn tập) thay đổi hẳn quyết định gọi tool ngay tại Turn 1** giữa `3.0` và `3.2`.
     - Trong **14 mẫu `Abstain TP` bị mất** giữa `3.0` và `3.2`, có **10 / 14 mẫu** bị mất ngay tại Turn 1 thuộc nhóm `466` mẫu lệch quyết định do `+73` token System Prompt (ở `3.0` model không gọi tool ở Turn 1, sang `3.2` model gọi tool ngay ở Turn 1), và **4 / 14 mẫu** còn lại nằm ở nhóm có quyết định Turn 1 giống `3.0` nhưng bị chốt `tool_name_without_call` đẩy sang gọi tool.

#### C. Phân nhóm toàn bộ 1.545 mẫu

Các nhóm được tính lại theo cùng thứ tự ưu tiên cho hai run. Trước hết tách Gold rỗng, sau đó xét không gọi tool, khớp state, state cần đổi nhưng không đổi và các trường hợp sai state còn lại. `S` là danh sách tool đã thực thi. Cách ưu tiên Gold rỗng có thể cho số lượng 3.1 khác với các nhóm ở mục 1.4.

| Nhóm loại trừ nhau | Sandbox 3.1 | Sandbox 3.2 | Tỷ lệ 3.2 |
| :--- | ---: | ---: | ---: |
| Gold có tool, `S` rỗng | 609 | 636 | 41,17% |
| Gold có tool, đã gọi tool, state cần đổi nhưng không đổi | 353 | 412 | 26,67% |
| Gold có tool, đã gọi tool, state cuối sai trong các trường hợp còn lại | 338 | 260 | 16,83% |
| Gold có tool, đã gọi tool, state cuối khớp | 134 | 126 | 8,16% |
| Gold rỗng, `S` rỗng | 64 | 65 | 4,21% |
| Gold rỗng, `S` có tool | 47 | 46 | 2,98% |
| Tổng | 1.545 | 1.545 | 100% |

- Trong 636 mẫu bỏ sót toàn bộ tool ở 3.2, Gold cần `write` ở 473 mẫu, cần `sys.ask_missing_info` ở 106 mẫu và chỉ cần `read` ở 57 mẫu. Có 146 mẫu vẫn khớp state do state không cần đổi.
- Trong 260 mẫu đã gọi tool và sai state thuộc nhóm còn lại, 229 mẫu có USMR bằng 1. [train_0004](kaggle/ablation_03_2_results/traces/train_0004.json) tìm đúng `light_bedroom2` nhưng gửi `brightness=80`, trong khi Gold là `50`. [train_0033](kaggle/ablation_03_2_results/traces/train_0033.json) chỉ thực thi `calendar.list_events` dù Gold có thêm `alarm.create`.
- Chưa tách được hiệu quả độc lập của quy tắc xử lý tiểu từ ASR: `train_0018` ở 3.2 không thực thi tool nên chưa cho thấy riêng hiệu quả sửa tham số tìm kiếm.

### 1.6. Tổng hợp các lỗi còn tồn đọng sau Sandbox 3.2

Trên toàn bộ 1.545 mẫu của [`ablation_03_2_results`](kaggle/ablation_03_2_results/), các lỗi còn tồn đọng tập trung vào 5 nhóm chính:

1. **Nhóm 1: Tương tác bằng ngôn ngữ tự nhiên / Trò chuyện thay vì hành động (Điểm nghẽn lớn nhất — chiếm >60% toàn tập):**
   - **Bỏ sót hoàn toàn tool ngay từ Turn 1 (`636 / 1.545` mẫu = `41,17%`):** Model sinh văn bản trả lời, tự phân tích suy luận trong `<think>` hoặc hỏi người dùng (ví dụ: hỏi ID thiết bị, hỏi tên nhóm chat) thay vì mở thẻ `<tool_call>` để tra cứu.
   - **Dừng non sau bước đọc (`412 / 1.545` mẫu = `26,67%`):** Sau khi đã gọi thành công hàm `read` ở Turn 1 (lấy được ID đèn, lịch họp, v.v.), model quay ra tóm tắt thông tin hoặc hỏi xác nhận *"Bạn có muốn tôi đặt báo thức không?"* ở Turn 2 rồi tự dừng, bỏ qua bước `write` hoặc `sys.ask_missing_info` cần thiết.
2. **Nhóm 2: Thất bại với `sys.ask_missing_info` và nhận diện ranh giới câu lệnh:**
   - **Không biết dùng công cụ hỏi thiếu thông tin (`217` mẫu Gold):** Model chỉ gọi đúng tên `sys.ask_missing_info` ở **3 / 217 mẫu (1,38%)** và **0 mẫu** khớp đúng tham số. Model gần như luôn hỏi người dùng bằng câu thoại tiếng Việt thông thường thay vì xuất thẻ công cụ này.
   - **Ảo giác gọi tool trên mẫu từ chối (`111` mẫu Gold rỗng):** Model gọi nhầm công cụ trên **46 / 111 mẫu (41,44%)**, chỉ giữ được **65 mẫu** từ chối đúng (do nhạy cảm với các thông tin thời gian/địa điểm trong `context` ở Turn 1).
3. **Nhóm 3: Cơ chế tự phục hồi (Self-Healing) bị nghẽn và model bỏ cuộc sớm:**
   - **Bỏ cuộc sớm sau khi tra cứu rỗng (`empty_read`):** Sau khi nhận `[]`, model dừng lại luôn ở **22,9%** số lần (cao gấp 2,5 lần mức 9,0% của bản 3.0) do câu `hint` có vế gợi ý *"hoặc dừng lại nếu không tìm thấy"*.
   - **Lặp lại lệnh lỗi ở nhóm `write` (`not_done`):** Khi lệnh ghi báo lỗi (ví dụ không đủ số dư ví), có tới **46,3%** trường hợp model gọi lặp lại y hệt lệnh vừa lỗi ở lượt sau vì cơ chế `precheck` hiện tại chỉ mới chặn các lệnh `read`.
4. **Nhóm 4: Sai lệch giá trị tham số khi thực thi lệnh ghi (`write`):**
   - Chiếm **260 / 1.545 mẫu (16,83%)**. Model xác định đúng công cụ cần ghi nhưng truyền sai giá trị (ví dụ: độ sáng 80 thay vì 50, sai tài khoản thanh toán, nhầm thời gian hẹn), dẫn đến bị phạt `USMR = 1` trên 229 mẫu.
5. **Nhóm 5: Vòng lặp suy luận và tiêu tốn lượt:**
   - Dù bản 3.2 đã kiểm soát các lệnh gọi lặp thực thi xuống còn **1,75% (27 mẫu)** và chạm trần 20 lượt xuống **3,62% (56 mẫu)**, vẫn còn **148 mẫu (9,58%)** model có ý định sinh lại các lệnh đọc trùng lặp và bị `precheck` chặn, gây lãng phí lượt suy luận.

---

## 2. Sandbox 3.1 — Giải quyết ba vấn đề gốc

### 2.1. Ngăn mô hình trả lời bằng văn bản thay vì gọi công cụ

- **[x] Đã cập nhật trong [`self_healing.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/self_healing.py#L101-L105) và [Sandbox History.md](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/Sandbox%20History.md#L244-L253):**
  - Đã sửa câu `hint` của `empty_read` và `repeated_read` để điều hướng model gọi `sys.ask_missing_info` khi thiếu dữ kiện bắt buộc (thay vì câu nhắc cũ *"Dùng dữ liệu đã có để chọn bước tiếp theo"* khiến model 1.7B tự đoán tham số hoặc hỏi bằng văn bản).
- **[x] Đã cập nhật trong [`sandbox.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/sandbox.py#L118-L172) và kiểm thử tại [`test_enhanced_sandbox.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/tests/test_enhanced_sandbox.py#L163-L208):**
  - Đã bổ sung 2 chốt kiểm tra trạng thái tất định (không bắt chữ hay kiểm tra dấu câu tiếng Việt) khi `calls == []` và `self_heal=True`, mỗi chốt kích hoạt tối đa 1 lần/mẫu khi `turn < max_turns`:
    1. **Tín hiệu 1 — Kiểm tra rò rỉ định danh Schema (`stop_trigger = "tool_name_without_call"`, `any(name in content for name in specs)`):** Chỉ kiểm tra trên phần `content` sau khi đã tách `<think>...</think>`, nhận diện lỗi quên bọc thẻ `<tool_call>` (như `train_0014`) mà không ảnh hưởng tới các mẫu từ chối ngoài phạm vi có nhắc tên hàm trong `<think>`.
    2. **Tín hiệu 2 — Chốt kiểm tra trạng thái `Read-Without-Action` (`stop_trigger = "read_without_action"`):** Khi phiên **đã thực thi ít nhất một lệnh `read`** (`bool(healer.seen_reads)`), nhưng **chưa có lệnh `write` nào làm thay đổi state** (`not state_changed_by_write`) và **chưa gọi `sys.ask_missing_info`** (`not asked_for_info`), nếu model định dừng (`calls == []`), runtime nhắc tối đa 1 lần để model gọi công cụ `write`, gọi `sys.ask_missing_info`, hoặc xác nhận kết thúc nếu yêu cầu chỉ cần tra cứu.

### 2.2. Chặn lệnh `read` lặp lại

- **[x] Đã cập nhật trong [`system_prompt.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/system_prompt.py#L18) và [System Prompt History.md](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/System%20Prompt%20History.md#L90):**
  - Đã thêm ràng buộc phủ định chống `Confirmatory Tool Usage` vào `ENHANCED` System Prompt: *"Không gọi lại công cụ tra cứu với cùng tham số khi đã có kết quả từ lượt trước."*
- **[x] Đã cập nhật trong [`self_healing.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/self_healing.py#L53-L57) và kiểm thử tại [`test_enhanced_sandbox.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/tests/test_enhanced_sandbox.py#L148-L162):**
  - Đã chuyển việc bắt `repeated_read` (`spec.get("kind") == "read" and call_key(call) in self.seen_reads`) lên tiền kiểm ở [`precheck`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/self_healing.py#L53-L57) (`blocked = True`), kèm câu `hint` mở đường thoát an toàn.
  - Khi `blocked = True`, [`sandbox.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/sandbox.py#L184-L187) không gọi `env.call()`, giữ sạch `env.get_tool_calls()` để không làm giảm Precision $P = \frac{M}{M+U}$ của `Contest Score`. Sau khi có một lệnh làm thay đổi state (`state_changed=True`), `seen_reads` được xóa để cho phép đọc lại trạng thái mới.

### 2.3. Loại tiểu từ khẩu ngữ khỏi tham số tìm kiếm

Không sử dụng danh sách cắt chuỗi cứng (tránh cắt nhầm tên riêng tiếng Việt), xử lý tổng quát qua 2 tầng:
- **[x] Đã cập nhật trong [`system_prompt.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/system_prompt.py#L17):**
  - Đã bổ sung hướng dẫn trích xuất tham số tìm kiếm từ lời nói ASR có bảo vệ tên riêng: *"Khi trích xuất tham số tìm kiếm từ lời nói, giữ tên hoặc thực thể cần tìm và bỏ các tiểu từ khẩu ngữ cuối câu như "nha", "nhé", "giùm", "với" nếu chúng không thuộc tên riêng."*
- **[x] Đã cập nhật trong [`self_healing.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/self_healing.py#L101-L105) và [`system_prompt.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/system_prompt.py#L19):**
  - Nhánh `empty_read` trong `observe` phát hiện khi hàm `read` có tham số lọc tùy chọn trả về rỗng `[]` và nhắc model: *"Kết quả rỗng với tham số tùy chọn ... Cân nhắc bỏ bớt bộ lọc nếu vẫn giữ đúng yêu cầu, hoặc gọi sys.ask_missing_info nếu thiếu dữ kiện bắt buộc và không tra cứu thêm được, không tự đoán tham số để gọi lệnh ghi."*


---

## 3. Sandbox 3.2 — Tinh chỉnh cơ chế

Dựa trên bằng chứng định lượng tại mục `1.4`, thiết kế **Sandbox 3.2** giữ lại các thành phần mang lại lợi ích ròng dương (chặn `repeated_read` ở `precheck` giúp giảm 86.56% lượt lặp thực thi, quy tắc lọc tiểu từ khẩu ngữ ASR giúp tăng +27.03% số mẫu `write` đúng) và loại bỏ 3 tác nhân gây tụt điểm ở Table 1:

### 3.1. Điều chỉnh chốt dừng trong [`sandbox.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/sandbox.py#L147-L172)

- **[x] Xóa bỏ hoàn toàn chốt `read_without_action`:**
  - Chốt này kích hoạt `416` lần ở `3.1`, gây ra chuỗi phản ứng dây chuyền kép trên `277 / 1.545` mẫu, làm hỏng `9` mẫu `Final State Match` ròng (`380` $\rightarrow$ `371`) và làm tăng `USMR` thêm `+2.98%` (`17.73%` $\rightarrow$ `20.71%`).
- **[x] Giới hạn chốt `tool_name_without_call` chỉ kích hoạt ở `turn == 1`:**
  - Điều kiện mới: `if self_heal and turn == 1 and turn < max_turns and any(name in content for name in specs):`.
  - Ở `turn == 1` (khi chưa có lệnh gọi công cụ nào trong phiên), nếu model viết tên hàm thuộc `specs` trong phần văn bản `content` thì đúng là lỗi quên mở thẻ `<tool_call>` (như `train_0014`, giúp tăng `Contest Score` từ `6.73` lên `7.01`, `Exact Ordered` từ `88` lên `92`, và `SSR` từ `26.68%` lên `27.00%`).
  - Từ `turn >= 2` trở đi, không kích hoạt chốt này để tránh bắt nhầm tên công cụ mà model nhắc lại trong câu báo cáo kết quả sau khi đã gọi tool ở Turn 1.

### 3.2. Giữ chặn `repeated_read` và sửa `hint` trong [`self_healing.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/self_healing.py#L53-L105)

- **[x] Giữ nguyên cơ chế chặn `repeated_read` tại `precheck` (`blocked = True`):**
  - Bảo toàn hiệu quả giảm mẫu lặp thực thi trong `submission["tool_calls"]` xuống `41 / 1.545` mẫu (`2.65%`) và giảm chạm trần 20 lượt xuống `62 / 1.545` mẫu (`4.01%`).
- **[x] Bỏ nhắc tên `sys.ask_missing_info` trong câu `hint` của `repeated_read` và `empty_read`:**
  - Thay bằng câu hướng dẫn thoát trung lập để không kích thích model `1.7B` gọi `sys.ask_missing_info` tràn lan (`130` lần ở `3.1`, gây thêm `+83` False Positives ở `MI/Abs F1`):
    - `repeated_read`: `"Lệnh tra cứu này đã chạy và state chưa đổi. Dùng dữ liệu đã có hoặc trả lời kết thúc nếu đã đủ thông tin, không tự đoán tham số để gọi lệnh ghi."`
    - `empty_read`: `"Kết quả rỗng với tham số tùy chọn ... Cân nhắc bỏ bớt bộ lọc nếu vẫn giữ đúng yêu cầu, hoặc dừng lại nếu không tìm thấy đối tượng phù hợp, không tự đoán tham số để gọi lệnh ghi."`

### 3.3. Rút gọn `ENHANCED` System Prompt trong [`system_prompt.py`](file:///c:/HCMUT/Projects/ZaloAiChallenge/LifeMate/system_prompt.py#L8-L20)

- **[x] Khôi phục khối `1. NGUỒN DỮ LIỆU` về bản súc tích của `ablation_02_results` / `ablation_03_results`:**
  - Lược bỏ câu liệt kê chi tiết `current_time`, `location`, `user_profile` (vốn làm tăng `+151` input tokens ở Turn 1 và kích thích model `1.7B` bám vào `location`/`current_time` để gọi tool trên `13 / 111` mẫu ngoài phạm vi `G = []`, làm mất `0.84%` `Contest Score`), trong khi vẫn giữ lại quy tắc lọc tiểu từ khẩu ngữ ASR (`"nha"`, `"nhé"`, `"giùm"`, `"với"`) và quy tắc chống gọi lặp công cụ tra cứu.
