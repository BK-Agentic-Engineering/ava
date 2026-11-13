# System Prompt History

## Literature Review: GEPA

- **Title:** GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning.
- **Authors / Org:** Lakshya A. Agrawal et al. — UC Berkeley, Stanford, BespokeLabs.ai, University of Notre Dame, Databricks & MIT.
- **Date & Freshness:** ICLR 2026 Oral, repo cập nhật năm 2026.
- **Venue / Source:** ICLR 2026 Oral, CORE A*, [arXiv:2507.19457](https://arxiv.org/abs/2507.19457) · [gepa-ai/gepa](https://github.com/gepa-ai/gepa) (~7,3k stars) · [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) (~39k stars).

### Phương pháp

GEPA tối ưu hóa prompt dựa trên phản tư từ vết thực thi (execution traces):
1. Chạy prompt ứng viên trên tập mẫu và thu thập trace thực thi cùng tín hiệu phản hồi từ môi trường.
2. Dùng mô hình ngôn ngữ đọc các trace thất bại để xác định nguyên nhân lỗi và viết lại quy tắc tương ứng trong prompt.
3. Giữ lại tập ứng viên trên đường biên Pareto qua các mẫu đánh giá và kết hợp các quy tắc bổ trợ nhau mà không cập nhật trọng số mô hình.

### Kết quả và giới hạn

- Trên 6 tác vụ thực nghiệm của paper, GEPA cải thiện kết quả trung bình 6% (tối đa 20%) so với GRPO với số lượt rollout ít hơn tới 35 lần, và cao hơn MIPROv2 trên 10%.
- Chất lượng prompt phụ thuộc vào khả năng chẩn đoán trace của mô hình phản tư và độ rõ ràng của tín hiệu lỗi.

### Áp dụng cho LifeMate

Dùng các mẫu lỗi thực tế quan sát được trên trace tập train (bỏ sót vế trong câu ghép, bỏ qua điều kiện, tự đặt giá trị tham số khi thiếu dữ kiện, lặp lệnh đọc đã có kết quả) để viết thành các quy tắc cụ thể trong System Prompt.

## Literature Review: SysBench

- **Title:** SysBench: Can Large Language Models Follow System Messages?
- **Authors / Org:** Yanzhao Qin et al. — Peking University & Baichuan Inc.
- **Date & Freshness:** ICLR 2025, mở rộng sang VSysBench tại EMNLP 2026.
- **Venue / Source:** ICLR 2025, CORE A*, [arXiv:2408.10943](https://arxiv.org/abs/2408.10943) · [PKU-Baichuan-MLSystemLab/SysBench](https://github.com/PKU-Baichuan-MLSystemLab/SysBench).

### Phương pháp

SysBench đánh giá khả năng tuân thủ system message trong hội thoại nhiều lượt và chia cấu trúc System Prompt thành 6 khối chức năng:

| Khối chức năng | Nội dung | Cách áp dụng trong LifeMate |
| --- | --- | --- |
| Role | Chức năng của tác tử. | Giữ ngắn gọn ở câu mở đầu. |
| Background | Môi trường hoạt động và nguồn thông tin hợp lệ. | Quy định chỉ lấy dữ liệu từ `request`, `context`, `history` và kết quả công cụ trả về. |
| Action | Quy trình xử lý yêu cầu theo từng bước. | Hướng dẫn thực hiện đủ các vế câu ghép, kiểm tra điều kiện, tra cứu trước khi ghi và sửa lỗi theo phản hồi. |
| Content | Ràng buộc về thông tin bắt buộc, điều cấm và điều kiện dừng/hỏi lại. | Cấm tự đoán ID hoặc số liệu, quy định điều kiện gọi `sys.ask_missing_info` và cách trả lời khi yêu cầu ngoài phạm vi. |
| Format | Quy ước định dạng đầu ra. | Lược bỏ vì `apply_chat_template` và tool schema của LFM3 đã đảm nhiệm. |
| Style | Văn phong giao tiếp. | Lược bỏ vì bài toán chỉ chấm `tool_calls` và `state_hash`. |

### Kết quả và giới hạn

- Độ tuân thủ giảm mạnh ở hai khối Action và Content khi viết gộp quy trình làm việc và điều cấm trong cùng một đoạn văn xuôi, hoặc sau nhiều lượt gọi công cụ liên tiếp.
- Tách riêng từng khối và viết dưới dạng các quy tắc đơn lẻ (atomic rules) giúp giảm tỷ lệ vi phạm ràng buộc qua nhiều lượt.

### Áp dụng cho LifeMate

Thay đoạn văn xuôi ở Baseline bằng cấu trúc 3 khối tách biệt (Nguồn dữ liệu, Quy trình thực hiện, Xử lý thiếu thông tin và ngoài phạm vi), lược bỏ hoàn toàn phần Format và Style.

---

## Baseline

```text
Bạn là trợ lý thực hiện yêu cầu bằng các công cụ được cung cấp.
Hãy phân tích kỹ yêu cầu của người dùng trước khi tiến hành để hiểu đúng ý định, tránh nhầm lẫn bởi từ lóng hoặc yêu cầu mơ hồ, sau đó sử dụng công cụ phù hợp.
```

---

## Thiết kế Enhanced System Prompt

Kết hợp cách chia khối của SysBench với các quy tắc xử lý lỗi rút ra từ trace thực thi theo hướng GEPA:

### 1. Cấu trúc ánh xạ thiết kế

| Khối chức năng (SysBench) | Lỗi quan sát từ Trace (GEPA Diagnosis) | Quy tắc trong Enhanced System Prompt |
| --- | --- | --- |
| Role & Background | Tự suy diễn dữ liệu ngoài ngữ cảnh hoặc bịa đặt tham số khi thiếu dữ kiện. | Chỉ sử dụng thông tin từ `request`, `context`, `history` và kết quả công cụ. Không tự đoán hoặc bịa đặt mã định danh (ID), số điện thoại, số tiền hay giá trị tham số. |
| Action — Phân rã & Điều kiện | Bỏ sót vế trong câu ghép nhiều yêu cầu (`train_0003`), bỏ qua mệnh đề điều kiện "nếu... thì..." (`train_0008`). | Thực hiện đầy đủ mọi yêu cầu trong câu lệnh. Nếu có điều kiện (thời tiết, thời gian, trạng thái), gọi công cụ tra cứu để kiểm tra điều kiện trước khi hành động. |
| Action — Thứ tự Tra cứu trước Ghi | Gọi thẳng công cụ `write` khi chưa biết ID hoặc số liệu thực tế (`train_0003`, `train_0004`, `train_0048`). | Khi cần ID hoặc dữ liệu chưa biết để thực hiện lệnh ghi, ưu tiên gọi công cụ tra cứu liên quan trước. |
| Action — Lọc tiểu từ ASR | Nhiễu tiểu từ khẩu ngữ ASR (`"nha"`, `"nhé"`, `"giùm"`, `"với"`) dính vào chuỗi tìm kiếm khiến lệnh `read` trả về rỗng. | Khi trích xuất tham số tìm kiếm từ lời nói, giữ tên hoặc thực thể cần tìm và bỏ các tiểu từ khẩu ngữ cuối câu nếu không thuộc tên riêng. |
| Action — Thích ứng & Chống lặp | Lặp lại cùng một lệnh đọc đã có kết quả (`train_0008`) hoặc dừng lại khi bộ lọc hẹp trả về danh sách rỗng (`train_0004`). | Không gọi lại công cụ tra cứu với cùng tham số khi đã có kết quả từ lượt trước. Nếu tra cứu trả về rỗng hoặc công cụ báo lỗi, kiểm tra lại điều kiện, cân nhắc bỏ bộ lọc tùy chọn hoặc sửa tham số theo phản hồi, không gọi lặp lại y nguyên lệnh vừa chạy. |
| Content & Boundary | Tự đặt số điện thoại, số tiền, mã định danh khi thiếu dữ kiện, hoặc gọi công cụ với yêu cầu ngoài phạm vi (`train_0019`, `train_0048`). | Không tự đoán ID, số điện thoại, số tiền hay giá trị tham số. Chỉ gọi `sys.ask_missing_info` khi thiếu tham số bắt buộc mà không có công cụ tra cứu hoặc đã tra cứu nhưng vẫn không xác định được. Trả lời trực tiếp và không gọi công cụ nếu yêu cầu ngoài phạm vi. |

### 2. Nội dung Enhanced System Prompt

```text
Bạn là trợ lý thực hiện yêu cầu người dùng thông qua các công cụ được cung cấp. Tuân thủ các quy tắc sau:

1. NGUỒN DỮ LIỆU:
- Chỉ sử dụng thông tin có trong request, context, history và kết quả trả về của công cụ.
- Không tự đoán hoặc bịa đặt mã định danh (ID), số điện thoại, số tiền hay giá trị tham số.

2. QUY TRÌNH THỰC HIỆN:
- Thực hiện đầy đủ mọi yêu cầu trong câu lệnh, không bỏ sót vế khi người dùng nêu nhiều việc cùng lúc.
- Nếu yêu cầu có điều kiện (như thời tiết, thời gian, trạng thái), gọi công cụ tra cứu để kiểm tra điều kiện trước khi thực hiện hành động.
- Khi cần ID hoặc dữ liệu chưa biết để thực hiện lệnh ghi, ưu tiên gọi công cụ tra cứu liên quan trước.
- Khi trích xuất tham số tìm kiếm từ lời nói, giữ tên hoặc thực thể cần tìm và bỏ các tiểu từ khẩu ngữ cuối câu như "nha", "nhé", "giùm", "với" nếu chúng không thuộc tên riêng.
- Không gọi lại công cụ tra cứu với cùng tham số khi đã có kết quả từ lượt trước.
- Nếu tra cứu trả về danh sách rỗng hoặc công cụ báo lỗi, kiểm tra lại điều kiện, cân nhắc bỏ bộ lọc tùy chọn hoặc sửa tham số theo phản hồi, không gọi lặp lại y nguyên lệnh vừa chạy.

3. XỬ LÝ THIẾU THÔNG TIN VÀ NGOÀI PHẠM VI:
- Chỉ gọi sys.ask_missing_info khi thiếu tham số bắt buộc mà không có công cụ tra cứu tương ứng, hoặc đã tra cứu nhưng vẫn không xác định được đối tượng.
- Nếu yêu cầu nằm ngoài khả năng của các công cụ được cung cấp, trả lời trực tiếp cho người dùng và không gọi công cụ.
```

### 3. Đối chiếu Baseline và Enhanced System Prompt

| Tiêu chí | Baseline | Enhanced System Prompt |
| --- | --- | --- |
| Cấu trúc trình bày | Đoạn văn xuôi 2 câu gộp chung việc phân tích ý định và gọi công cụ. | Chia 3 khối tách biệt (Nguồn dữ liệu, Quy trình thực hiện, Xử lý thiếu thông tin và ngoài phạm vi) theo SysBench. |
| Phân định ranh giới ngữ cảnh | Không giải thích vai trò của `request`, `context`, `history`. | Tinh gọn ranh giới dữ liệu, không diễn giải rườm rà các trường `current_time`, `location`, `user_profile` (+151 tokens) để tránh kích thích ảo giác gọi tool trên mẫu ngoài phạm vi. |
| Xử lý câu ghép và điều kiện | Không có chỉ dẫn cụ thể. | Quy định thực hiện đủ các vế và kiểm tra điều kiện bằng công cụ tra cứu trước khi hành động. |
| Phối hợp với Tool Description và Sandbox | Độc lập, không gắn với cơ chế tra cứu hoặc phản hồi lỗi. | Khớp trực tiếp với luồng tra cứu lấy ID, cấm gọi lại lệnh tra cứu đã có kết quả, bỏ bộ lọc tùy chọn khi rỗng và không lặp lại lệnh lỗi. |
| Ranh giới gọi `sys.ask_missing_info` | Chỉ nhắc tránh nhầm lẫn bởi yêu cầu mơ hồ, không nêu điều kiện gọi `sys.ask_missing_info`. | Cấm tự đoán ID/số điện thoại/số tiền, ưu tiên tra cứu trước và chỉ gọi `sys.ask_missing_info` khi không thể tra cứu hoặc kết quả vẫn thiếu dữ kiện. |
