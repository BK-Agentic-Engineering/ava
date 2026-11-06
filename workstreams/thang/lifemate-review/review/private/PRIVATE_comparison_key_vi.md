# Khóa đối chiếu riêng cho Thắng

Chỉ gửi reviewer_sheet_vi.md cho người đọc độc lập. Giữ khóa này riêng đến khi người đọc trả lại câu trả lời. Chưa có câu trả lời hay phán quyết nào được điền.

## Quy tắc đối chiếu

- Lưu nguyên văn câu trả lời, gồm cả các mốc giờ và nhận xét khác kỳ vọng. Ghi nhận xét của Thắng riêng, không sửa câu trả lời để khớp gold.
- Đồng ý với kỳ vọng khi xác định đúng event, các mốc trước/sau tương đương và thông tin giữ nguyên. Chấp nhận cách diễn đạt tiếng Việt và các định dạng ngày giờ, múi giờ tương đương. Mốc rút gọn dùng ngày/múi giờ của phiếu khi ngữ cảnh rõ.
- Cách hiểu khác có cơ sở khi người đọc giải thích hợp lý một kết quả khác từ câu chữ và lịch được cung cấp. Ghi rõ chênh lệch với thiết kế, không tự coi là sai vì không trùng oracle.
- Chưa đủ thông tin khi câu trả lời thiếu mốc hoặc kết quả để đối chiếu, hoặc người đọc thấy cần hỏi lại. Không tự điền phần thiếu theo gold. Nếu có giải thích hợp lý về sự mơ hồ của yêu cầu, ghi thêm nhận xét về cách hiểu khác có cơ sở.
- Khác biệt đáng kể khi chọn sai buổi/ngày, sai hướng hoặc số phút, đổi nội dung/địa điểm/trạng thái hay tạo/xóa mục trái yêu cầu mà không có cách hiểu hợp lý. Có thể ghi riêng phần đồng ý và phần chưa đủ thông tin của một câu trả lời.

## Nguồn và thứ tự

YAML nguồn data/synthetic/design/train_wave_17.yaml. Replay nguồn artifacts/synthetic/train_wave_17_replay/replay.json. Các selector bên dưới dùng chỉ số từ 0, YAML được xem như object sau khi parse. Mỗi lịch lấy từ chính response calendar.list_events thành công trong trace standard của case đó. Các event giữ nguyên thứ tự trả về, nhãn A/B thay internal ID.

Thứ tự P01–P06 là thứ tự cố định đã trộn. P02 và P06 có request giống hệt nhau nhưng end ban đầu khác. Không gộp hai mục. Context chung là 2027-11-07T16:00:00+07:00 và Asia/Ho_Chi_Minh. Ngày mai là 08/11/2027.

Kỳ vọng hiện tại của thiết kế là dời buổi giữ thời lượng của chính buổi đó, còn kéo dài buổi giữ giờ bắt đầu và tăng giờ kết thúc. Đây là giả định để đối chiếu sau review, không tiết lộ trong phiếu.

## P01

- Scenario ID TR17_CAL_EXTEND. Replay row 23, trace_case standard.
- Response nguồn /replays/23/calls/0/result/events. Oracle nguồn YAML /scenarios/3/oracle_draft.
- Expected final event trong replay /replays/23/final_state/calendar/events, chọn theo ID.
- Nhãn A → w17_b, B → w17_a.
- Event kỳ vọng thay đổi **B**, Duyệt men, Xưởng Sen.
- Trước: 2027-11-08T09:10:00+07:00 → 2027-11-08T09:55:00+07:00.
- Sau kỳ vọng: 2027-11-08T09:10:00+07:00 → 2027-11-08T10:25:00+07:00.
- Giữ nguyên trên event đích {"id": "w17_a", "title": "Duyệt men", "location": "Xưởng Sen", "status": "confirmed", "start": "2027-11-08T09:10:00+07:00"}.
- Giữ nguyên toàn bộ event khác và các trường không nêu thay đổi. Không thêm/xóa event. Oracle cũng giữ nguyên app/record ngoài lịch. Không dùng thông tin private ngoài phiếu để suy diễn câu trả lời.
- Đối chiếu đúng mục, ngày, bắt đầu, kết thúc, thông tin giữ nguyên và tác động lên mục còn lại. Áp dụng bốn mức ở trên, giữ phần giải thích của người đọc.

**Câu trả lời nguyên văn của người đọc**


**Nhận xét đối chiếu riêng của Thắng**



## P02

- Scenario ID TR17_CAL_LONG. Replay row 8, trace_case standard.
- Response nguồn /replays/8/calls/0/result/events. Oracle nguồn YAML /scenarios/1/oracle_draft.
- Expected final event trong replay /replays/8/final_state/calendar/events, chọn theo ID.
- Nhãn A → w17_b, B → w17_a.
- Event kỳ vọng thay đổi **B**, Duyệt men, Xưởng Sen.
- Trước: 2027-11-08T09:10:00+07:00 → 2027-11-08T10:30:00+07:00.
- Sau kỳ vọng: 2027-11-08T09:40:00+07:00 → 2027-11-08T11:00:00+07:00.
- Giữ nguyên trên event đích {"id": "w17_a", "title": "Duyệt men", "location": "Xưởng Sen", "status": "confirmed"}.
- Giữ nguyên toàn bộ event khác và các trường không nêu thay đổi. Không thêm/xóa event. Oracle cũng giữ nguyên app/record ngoài lịch. Không dùng thông tin private ngoài phiếu để suy diễn câu trả lời.
- Đối chiếu đúng mục, ngày, bắt đầu, kết thúc, thông tin giữ nguyên và tác động lên mục còn lại. Áp dụng bốn mức ở trên, giữ phần giải thích của người đọc.

**Câu trả lời nguyên văn của người đọc**


**Nhận xét đối chiếu riêng của Thắng**



## P03

- Scenario ID TR17_CAL_OTHER. Replay row 37, trace_case standard.
- Response nguồn /replays/37/calls/0/result/events. Oracle nguồn YAML /scenarios/5/oracle_draft.
- Expected final event trong replay /replays/37/final_state/calendar/events, chọn theo ID.
- Nhãn A → w17_b, B → w17_a.
- Event kỳ vọng thay đổi **A**, Duyệt men, Xưởng Sồi.
- Trước: 2027-11-08T14:00:00+07:00 → 2027-11-08T15:10:00+07:00.
- Sau kỳ vọng: 2027-11-08T14:30:00+07:00 → 2027-11-08T15:40:00+07:00.
- Giữ nguyên trên event đích {"id": "w17_b", "title": "Duyệt men", "location": "Xưởng Sồi", "status": "confirmed"}.
- Giữ nguyên toàn bộ event khác và các trường không nêu thay đổi. Không thêm/xóa event. Oracle cũng giữ nguyên app/record ngoài lịch. Không dùng thông tin private ngoài phiếu để suy diễn câu trả lời.
- Đối chiếu đúng mục, ngày, bắt đầu, kết thúc, thông tin giữ nguyên và tác động lên mục còn lại. Áp dụng bốn mức ở trên, giữ phần giải thích của người đọc.

**Câu trả lời nguyên văn của người đọc**


**Nhận xét đối chiếu riêng của Thắng**



## P04

- Scenario ID TR17_CAL_REPHRASE. Replay row 16, trace_case standard.
- Response nguồn /replays/16/calls/0/result/events. Oracle nguồn YAML /scenarios/2/oracle_draft.
- Expected final event trong replay /replays/16/final_state/calendar/events, chọn theo ID.
- Nhãn A → w17_b, B → w17_a.
- Event kỳ vọng thay đổi **B**, Duyệt men, Xưởng Sen.
- Trước: 2027-11-08T09:10:00+07:00 → 2027-11-08T09:55:00+07:00.
- Sau kỳ vọng: 2027-11-08T09:40:00+07:00 → 2027-11-08T10:25:00+07:00.
- Giữ nguyên trên event đích {"id": "w17_a", "title": "Duyệt men", "location": "Xưởng Sen", "status": "confirmed"}.
- Giữ nguyên toàn bộ event khác và các trường không nêu thay đổi. Không thêm/xóa event. Oracle cũng giữ nguyên app/record ngoài lịch. Không dùng thông tin private ngoài phiếu để suy diễn câu trả lời.
- Đối chiếu đúng mục, ngày, bắt đầu, kết thúc, thông tin giữ nguyên và tác động lên mục còn lại. Áp dụng bốn mức ở trên, giữ phần giải thích của người đọc.

**Câu trả lời nguyên văn của người đọc**


**Nhận xét đối chiếu riêng của Thắng**



## P05

- Scenario ID TR17_CAL_EARLY. Replay row 30, trace_case standard.
- Response nguồn /replays/30/calls/0/result/events. Oracle nguồn YAML /scenarios/4/oracle_draft.
- Expected final event trong replay /replays/30/final_state/calendar/events, chọn theo ID.
- Nhãn A → w17_b, B → w17_a.
- Event kỳ vọng thay đổi **B**, Duyệt men, Xưởng Sen.
- Trước: 2027-11-08T09:10:00+07:00 → 2027-11-08T09:55:00+07:00.
- Sau kỳ vọng: 2027-11-08T08:55:00+07:00 → 2027-11-08T09:40:00+07:00.
- Giữ nguyên trên event đích {"id": "w17_a", "title": "Duyệt men", "location": "Xưởng Sen", "status": "confirmed"}.
- Giữ nguyên toàn bộ event khác và các trường không nêu thay đổi. Không thêm/xóa event. Oracle cũng giữ nguyên app/record ngoài lịch. Không dùng thông tin private ngoài phiếu để suy diễn câu trả lời.
- Đối chiếu đúng mục, ngày, bắt đầu, kết thúc, thông tin giữ nguyên và tác động lên mục còn lại. Áp dụng bốn mức ở trên, giữ phần giải thích của người đọc.

**Câu trả lời nguyên văn của người đọc**


**Nhận xét đối chiếu riêng của Thắng**



## P06

- Scenario ID TR17_CAL_SHIFT. Replay row 0, trace_case standard.
- Response nguồn /replays/0/calls/0/result/events. Oracle nguồn YAML /scenarios/0/oracle_draft.
- Expected final event trong replay /replays/0/final_state/calendar/events, chọn theo ID.
- Nhãn A → w17_b, B → w17_a.
- Event kỳ vọng thay đổi **B**, Duyệt men, Xưởng Sen.
- Trước: 2027-11-08T09:10:00+07:00 → 2027-11-08T09:55:00+07:00.
- Sau kỳ vọng: 2027-11-08T09:40:00+07:00 → 2027-11-08T10:25:00+07:00.
- Giữ nguyên trên event đích {"id": "w17_a", "title": "Duyệt men", "location": "Xưởng Sen", "status": "confirmed"}.
- Giữ nguyên toàn bộ event khác và các trường không nêu thay đổi. Không thêm/xóa event. Oracle cũng giữ nguyên app/record ngoài lịch. Không dùng thông tin private ngoài phiếu để suy diễn câu trả lời.
- Đối chiếu đúng mục, ngày, bắt đầu, kết thúc, thông tin giữ nguyên và tác động lên mục còn lại. Áp dụng bốn mức ở trên, giữ phần giải thích của người đọc.

**Câu trả lời nguyên văn của người đọc**


**Nhận xét đối chiếu riêng của Thắng**


