# Thử nghiệm System Prompt

Tài liệu này ghi nhận nội dung prompt, thiết lập thử nghiệm và kết quả đo lường trên 5 mẫu train đại diện (`train_0003`, `train_0004`, `train_0008`, `train_0019`, `train_0048`) qua hai phiên bản V1 và V2.

---

## 1. System Prompt V1 (Baseline)

### Nội dung Prompt

```text
Bạn là trợ lý sử dụng công cụ để thực hiện yêu cầu. Chỉ dùng các công cụ được cung cấp. Nếu thiếu thông tin cần thiết, hãy dùng sys.ask_missing_info.
```

### Thiết lập Thử nghiệm

- **Mô hình & Tham số:** `LiquidAI/LFM3-1.7B` FP16, suy luận greedy decoding (`TEMPERATURE = 0`), context tối đa 16.384 tokens.
- **Tập mẫu đánh giá:** 5 mẫu train đại diện cho các tình huống khác nhau:
  - `train_0004`: Điều khiển thiết bị đơn lẻ (cần xác định đúng phòng và thiết bị).
  - `train_0003`: Tác vụ nhiều bước (tra cứu hóa đơn và thanh toán).
  - `train_0008`: Hội thoại nhiều lượt, yêu cầu phụ thuộc vào lịch sử (`history`).
  - `train_0019`: Yêu cầu ngoài phạm vi công cụ (nhãn không gọi tool nào).
  - `train_0048`: Thiếu dữ kiện, nhãn yêu cầu gọi `sys.ask_missing_info`.
- **Cấu trúc đầu vào:** Sau system prompt, mô hình nhận message người dùng gồm câu lệnh phiên âm từ ASR, `context` và `history`. Tool schema được nạp qua chat template. Mô hình không được truy cập trực tiếp state và nhãn.

### Bảng Kết quả

| Điều kiện Schema | Tool-call Match (Đúng thứ tự) | State Match | STLE trung bình (nats/token) | SVR Runtime |
| :--- | :---: | :---: | :---: | :---: |
| **Full** *(Thứ tự gốc)* | 1/5 | 2/5 | 0.0811 | 0/8 |
| **Reverse** *(Đảo thứ tự)* | 1/5 | 3/5 | 0.0431 | 0/16 |
| **Target** *(Chỉ cấp tools trong nhãn)* | 1/5 | 3/5 | 0.1336 | 0/8 |

Ghi chú: Điều kiện `Target` là thiết lập nhằm đo ảnh hưởng của công cụ gây nhiễu, không dùng khi chạy thực tế.

### Kết quả V1

- **PSS:** 0/8. Khi đảo thứ tự khai báo schema, mô hình không giữ nguyên quyết định gọi tool đầu tiên ở cả 4 mẫu có tool mục tiêu. Tỷ lệ giữ nguyên quyết định (bất kể đúng hay sai) là 25%.
- **DDR:** Không xác định được do độ chính xác ở lượt gọi đầu tiên của cả `Full` và `Target` đều là 0/4 (mẫu số bằng 0).
- **STLE:** Đạt 0.0811 ở Full, 0.0431 ở Reverse và 0.1336 nats/token ở Target. Mức entropy này chưa được hiệu chuẩn trên tập mẫu đủ lớn, chưa thể dùng làm ngưỡng tin cậy.
- **SVR Runtime:** 0/32 trên các lệnh gọi đã parse. Trên 5 mẫu này, mô hình không sinh ra trường lạ ngoài schema.
- **Vấn đề quan sát được từ trace:**
  - Ở mẫu `train_0008/Full`, mô hình lặp lại lệnh `alarm.list` liên tiếp và phải dừng sau 3 lần lặp giống nhau.
  - Ở mẫu `train_0048`, mô hình tự sinh một số điện thoại để gọi thay vì dùng `sys.ask_missing_info` khi thiếu thông tin.

---

## 2. System Prompt V2

### Nội dung Prompt

```text
Bạn là trợ lý điều khiển thiết bị và dịch vụ qua công cụ. Tuân thủ nghiêm ngặt các quy tắc sau:
1. Chỉ dùng thông tin từ context, history và kết quả trả về của các công cụ. Tuyệt đối không suy diễn dữ liệu ngoài các nguồn này.
2. Khi thiếu thông tin để thực hiện, ưu tiên dùng công cụ tra cứu liên quan. Chỉ gọi sys.ask_missing_info khi không có công cụ tra cứu hoặc tra cứu không xác định được.
3. Không gọi lại cùng một công cụ với cùng bộ tham số nếu công cụ đó đã trả về kết quả ở lượt trước.
4. Với yêu cầu ngoài phạm vi công cụ, phản hồi trực tiếp cho người dùng, không gọi tool.
```

### Thiết lập & Mục đích Thay đổi

- **Mục đích:** Dựa trên trace lỗi của V1, bổ sung 4 quy tắc ngắn gọn nhằm:
  - Bổ sung nguồn kết quả trả về của công cụ để mô hình biết sử dụng dữ liệu từ các bước trước.
  - Phân tầng việc tra cứu trước khi hỏi lại người dùng.
  - Chặn việc gọi lặp lại cùng một công cụ với cùng tham số.
  - Xử lý các câu lệnh ngoài phạm vi công cụ.
- **Cấu hình:** Giữ nguyên mô hình `LiquidAI/LFM3-1.7B` FP16, greedy decoding (`TEMPERATURE = 0`), context 16.384 tokens và cùng tập 5 mẫu train với cùng bản phiên âm ASR.

### Bảng Kết quả

| Điều kiện Schema | Tool-call Match (Đúng thứ tự) | State Match | STLE trung bình (nats/token) | SVR Runtime |
| :--- | :---: | :---: | :---: | :---: |
| **Full** *(Thứ tự gốc)* | 1/5 | 2/5 | 0.0390 | 0/6 |
| **Reverse** *(Đảo thứ tự)* | 1/5 | 3/5 | 0.1000 | 0/22 |
| **Target** *(Chỉ cấp tools trong nhãn)* | 1/5 | 3/5 | 0.0047 | 0/3 |

### So sánh & Đánh giá với V1

- **Điểm cải thiện:** Ở mẫu `train_0008/Full`, Quy tắc 3 giúp mô hình tự dừng sau 1 lượt gọi `alarm.list` thay vì lặp 3 lần như V1.
- **Các lỗi chưa giải quyết được:**
  - Tỷ lệ khớp chính xác toàn chuỗi tool call vẫn giữ nguyên 1/5 ở cả V1 và V2.
  - `train_0008`: Mô hình dừng lặp nhưng vẫn không gọi công cụ kiểm tra thời tiết theo đúng yêu cầu điều kiện.
  - `train_0048`: Mô hình vẫn tự sinh số điện thoại ngoài context thay vì gọi `sys.ask_missing_info`.
  - `train_0003`: Mô hình vẫn bỏ sót việc tra cứu hóa đơn và chuyển sai số tiền.
  - `train_0003/Reverse`: Xuất hiện lỗi parse do mô hình sinh giá trị `amount=???`. Lượt chạy này bị dừng và không thể thực thi.
- **Đánh giá tổng thể:** Việc điều chỉnh prompt thủ công giúp ngắt được hành vi lặp đơn giản nhưng chưa cải thiện được khả năng lập luận đa bước hay xử lý mệnh đề điều kiện. Thử nghiệm trên 5 mẫu chỉ mang tính khảo sát sơ bộ, chưa đủ để đưa ra kết luận khái quát cho toàn bộ tập dữ liệu.
