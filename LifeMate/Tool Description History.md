# Tool Description History

## Literature Review: DocsChisel

- **Title:** DOCSCHISEL: Adaptive Tool Documentation Optimization Framework for LLM Agents.
- **Authors / Org:** You Lu, Kun Zhang, Bihuan Chen, Xin Peng — Fudan University.
- **Date & Freshness:** arXiv v1 ngày 10/08/2026.
- **Venue / Source:** arXiv preprint, [arXiv:2608.10037](https://arxiv.org/abs/2608.10037).

### Phương pháp

Paper khảo sát 24.955 tool từ 14 dataset và phân loại 17 trường thông tin trong tài liệu công cụ. Tác dụng của từng trường phụ thuộc vào miền bài toán, mô hình và kiến trúc tác tử.

| Nhóm | Các trường trong taxonomy |
| --- | --- |
| Danh tính và chức năng | Tool Name (TN), Functionality Description (FD), Task Domain (TD) |
| Đầu vào | Input Parameter Name (IPN), Description (IPD), Type (IPT), Default Parameter Value (DPV), Parameter Required Flag (PRF), Parameter Optional Flag (POF) |
| Đầu ra | Return Parameter Name (RPN), Description (RPD), Type (RPT) |
| Cách sử dụng | Code Implementation (CI), Usage Example (UE), Response Template (RT), Usage Guidance (UG), Invocation Constraint (IC) |

Quy trình tối ưu tài liệu offline qua nhiều vòng:
1. Chạy tác tử trên tập tối ưu, đối chiếu trace thất bại với tài liệu hiện tại và nhãn chuẩn để tìm lỗi do mô tả công cụ.
2. Lập kế hoạch thêm, bỏ hoặc sửa từng trường thông tin dựa trên tài liệu gốc.
3. Sinh bản mô tả ứng viên, đánh giá trên tập validation và chọn bản có tỷ lệ hoàn thành tác vụ cao nhất (ưu tiên bản ngắn hơn khi bằng điểm).

### Kết quả và giới hạn

- Đánh giá trên 74 tool, 2.072 truy vấn thuộc 9 miền từ WorkBench và API-Bank với GPT-4o, GLM-5 và Claude Haiku 4.5.
- Task Success tăng tương đối 95,89% so với mô tả gốc, 75,15% so với trung bình hai baseline (EASYTOOL, DRAFT) và 46,11% so với baseline tốt nhất ở từng thiết lập. Tool Invocation Correctness (so khớp tập tên tool) tăng tương đối 30,83%.

| Chi phí trung bình mỗi tool | Gốc | EASYTOOL | DRAFT | DocsChisel |
| --- | ---: | ---: | ---: | ---: |
| Độ dài tài liệu (token) | 152,58 | 82,68 | 189,56 | 189,23 |
| Token quá trình tối ưu | — | 237,81 | 4.784,39 | 4.480,81 |
| Thời gian tối ưu (phút) | — | 0,23 | 2,26 | 12,65 |

### Áp dụng cho LifeMate

Dùng taxonomy của DocsChisel (FD, RPN/RPD, IC, UG) để chọn lọc các trường metadata có sẵn trong catalog của BTC và đưa vào chuỗi mô tả công cụ.

## Literature Review: DRAFT

- **Title:** From Exploration to Mastery: Enabling LLMs to Master Tools via Self-Driven Interactions.
- **Authors / Org:** Changle Qu et al. — Renmin University of China.
- **Date & Freshness:** ICLR 2025, arXiv v2 ngày 26/02/2025.
- **Venue / Source:** ICLR 2025, CORE A*, [Proceedings](https://proceedings.iclr.cc/paper_files/paper/2025/hash/8c22e5e918198702765ecff4b20d0a90-Abstract-Conference.html) · [arXiv:2410.08197](https://arxiv.org/abs/2410.08197) · [quchangle1/DRAFT](https://github.com/quchangle1/DRAFT) (58 stars).

### Phương pháp

DRAFT tinh chỉnh tài liệu của từng công cụ qua 3 bước lặp dựa trên tương tác thực thi:
1. Explorer sinh tình huống và tham số thử nghiệm để gọi công cụ và lấy kết quả trả về.
2. Analyzer đối chiếu mô tả hiện tại với kết quả thực thi và lịch sử sửa đổi để phát hiện điểm thiếu sót hoặc mơ hồ.
3. Rewriter cập nhật lại mô tả công cụ và ràng buộc tham số, dừng khi độ tương đồng giữa các phiên bản hội tụ.

### Kết quả và giới hạn

- Đánh giá trên ToolBench I3-Instruction và RestBench (TMDB, Spotify), dùng GPT-4o tối ưu tài liệu rồi kiểm tra trên GPT-4o, GPT-4o-mini và Llama-3-70B.
- Với GPT-4o-mini trên ToolBench, Correct Path Rate đạt 47% (so với 35% của ReAct và 42% của EASYTOOL).

### Áp dụng cho LifeMate

Làm rõ các ràng buộc đầu vào và đầu ra dựa trên hành vi thực thi thực tế của công cụ trong môi trường.

## Literature Review: EASYTOOL

- **Title:** EASYTOOL: Enhancing LLM-based Agents with Concise Tool Instruction.
- **Authors / Org:** Siyu Yuan, Kaitao Song et al. — Fudan University, Microsoft Research Asia & Zhejiang University.
- **Date & Freshness:** NAACL 2025, arXiv v3 ngày 27/03/2024.
- **Venue / Source:** NAACL 2025 Long Papers, CORE A, [ACL Anthology](https://aclanthology.org/2025.naacl-long.44/) · [arXiv:2401.06201](https://arxiv.org/abs/2401.06201) · [microsoft/JARVIS/easytool](https://github.com/microsoft/JARVIS/tree/main/easytool) (~25,6k stars toàn repo).

### Phương pháp

EASYTOOL chuẩn hóa tài liệu công cụ không đồng nhất qua hai bước:
1. Tóm tắt chức năng cốt lõi từ tài liệu gốc, loại bỏ các đoạn mô tả dài dòng hoặc trùng lặp.
2. Chuẩn hóa mô tả tham số và bổ sung tình huống sử dụng ngắn gọn.

### Kết quả và giới hạn

- Giảm độ dài tài liệu trung bình từ 2.530 xuống 748 token/tool trên ToolBench (70,43%) và từ 3.881 xuống 103 token/tool trên RestBench (97,35%).
- Trên ToolBench (I2-Category và I3-Instruction) với ChatGPT + DFSDT, tỷ lệ thành công trung bình đạt 52,8% so với 15,0% khi dùng tài liệu gốc.

### Áp dụng cho LifeMate

Giữ câu mô tả công cụ ngắn gọn, đồng nhất cấu trúc giữa các công cụ và nêu rõ điều kiện kích hoạt theo ý định người dùng.

---

## Baseline

Sử dụng nguyên gốc chuỗi `description` trong `train_tools_catalog.json`.

```text
weather.get_forecast: Dự báo theo ngày
smart_home.light_set: Bật/tắt/chỉnh sáng đèn
sys.ask_missing_info: Báo các tham số bắt buộc còn thiếu của một tool
```

---

## Manual Finding

Khảo sát `train_tools_catalog.json` (147 công cụ) cho thấy catalog có sẵn các trường metadata cấu trúc nhưng chưa được đưa vào chuỗi `description` khi truyền qua `apply_chat_template`:

| Trường metadata trong Catalog | Hiện trạng trong Baseline | Giá trị khai thác |
| --- | --- | --- |
| `kind` (`read`, `write`, `meta`) | Có ở 147/147 tool nhưng không xuất hiện trong `description`. | Phân biệt công cụ tra cứu dữ liệu (`read`), công cụ thay đổi trạng thái (`write`) và công cụ hệ thống (`meta`). |
| `returns` | Có khóa ở 147/147 tool (70 tool có giá trị như `devices[]`, `bills[]`, `alarms[]`). | Xác định tên dữ liệu trả về của công cụ đọc. |
| `parameters.properties.<param>.x-ref` và `description` | Có ở 65 tool, chứa liên kết tham chiếu (như `smart_home.devices`) kèm chú thích nguồn lấy ID (`lấy từ smart_home.get_status`). | Xác định công cụ tra cứu nguồn cần gọi khi chưa biết ID, tránh việc mô hình tự đoán giá trị tham chiếu. |
| `parameters.properties`, `required` và `x-one-of` | Chứa các tham số lọc tùy chọn (`room`, `floor`, `type`, `query`) và nhóm tham số thay thế. | Nhận diện các bộ lọc tùy chọn có thể bỏ bớt khi kết quả tra cứu trả về rỗng. |

---

## Thiết kế Enhanced Tool Description

Thiết kế kết hợp 4 nhóm thông tin từ taxonomy của DocsChisel và quy tắc rút gọn của EASYTOOL, trích xuất tự động từ metadata của catalog:

### 1. Cấu trúc 4 nhóm thông tin

| Nhóm thông tin | Nguồn từ catalog | Quy tắc tổng hợp |
| --- | --- | --- |
| Chức năng và tác động (FD) | `kind`, `description` | Gắn nhãn `[TRA CỨU]`, `[HÀNH ĐỘNG]` hoặc `[HỆ THỐNG]` theo `kind` vào đầu mô tả gốc. |
| Đầu ra (RPN/RPD) | `returns` | Với công cụ `read` có `returns` khác rỗng, nối thêm `Trả về <returns>.`. |
| Điều kiện gọi và tham chiếu (IC) | `x-ref`, `description` của tham số, `required`, `x-one-of` | Với tham số có `x-ref`, gợi ý tra cứu qua công cụ nguồn (nếu xác định được từ catalog và nằm trong tập tool được cấp) khi chưa biết ID, giữ nguyên tính tùy chọn hoặc thay thế của tham số trong `x-one-of`. |
| Hướng dẫn dùng bộ lọc (UG) | `properties`, `required`, `x-one-of` | Với công cụ `read` trả về danh sách (`[]`) và có các tham số lọc tùy chọn (`room`, `floor`, `type`, `query` không nằm trong `required` hay `x-one-of`), gợi ý cân nhắc bỏ bộ lọc nếu truy vấn không ra kết quả. |

### 2. Đối chiếu Baseline và Enhanced

| Công cụ | Baseline | Enhanced |
| --- | --- | --- |
| `weather.get_forecast` | `Dự báo theo ngày` | `[TRA CỨU] Dùng khi cần dự báo thời tiết theo ngày. Trả về forecast.` |
| `smart_home.get_status` | `Lấy thiết bị và trạng thái, lọc theo phòng/tầng/loại, không lọc thì trả về cả danh sách ngữ cảnh (scenes) đã lưu` | `[TRA CỨU] Lấy thiết bị và trạng thái, lọc theo phòng/tầng/loại, không lọc thì trả về cả danh sách ngữ cảnh (scenes) đã lưu. Trả về devices[]. Nếu lọc không ra kết quả, cân nhắc bỏ bộ lọc tùy chọn: room, floor, type.` |
| `smart_home.light_set` | `Bật/tắt/chỉnh sáng đèn` | `[HÀNH ĐỘNG] Bật/tắt/chỉnh sáng đèn. Nếu cần device_id mà chưa biết, tra qua smart_home.get_status nếu có. Không tự đoán ID.` |
| `contacts.search` | `Tìm liên hệ theo tên, quan hệ hoặc số điện thoại, so chuỗi con, không phân biệt hoa thường và dấu, không truyền query thì trả cả danh bạ` | `[TRA CỨU] Tìm liên hệ theo tên, quan hệ hoặc số điện thoại, so chuỗi con, không phân biệt hoa thường và dấu, không truyền query thì trả cả danh bạ. Trả về contacts[]. Nếu lọc không ra kết quả, cân nhắc bỏ bộ lọc tùy chọn: query.` |
| `phone.call` | `Gọi thoại cho liên hệ hoặc số điện thoại. Bắt buộc một trong: contact_id hoặc phone_number` | `[HÀNH ĐỘNG] Gọi thoại cho liên hệ hoặc số điện thoại. Bắt buộc một trong: contact_id hoặc phone_number. Nếu chọn contact_id mà chưa biết, tra qua contacts.search nếu có. Không tự đoán ID.` |
| `sys.ask_missing_info` | `Báo các tham số bắt buộc còn thiếu của một tool` | `[HỆ THỐNG] Báo các tham số bắt buộc còn thiếu của một tool.` |
