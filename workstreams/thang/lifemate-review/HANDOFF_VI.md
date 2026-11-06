# Tin nhắn để Thắng gửi cho nhóm

Mình gửi gói review hai phần việc: kết quả benchmark GIPFormer–VALSEA trên ViMD/VN-SLU và 1.000 scenario WORLD tổng hợp kèm gold/verifier, provenance và bằng chứng replay cục bộ. 984 case được implementor đánh giá phù hợp trong phạm vi đã kiểm tra; 16 case còn chờ quyết định. Tất cả vẫn spec_only, chưa được export/train hay xác nhận chạy qua harness.

Tài xem README và ba case trong integration/three_cases để đối chiếu cách render Jaz, khởi tạo state sau history, quyền tool, run ID thực, trace/submission và scorer. Gold/state riêng không được đưa vào input model; không chạy lại history. SDK/catalog không đi kèm vì chưa xác nhận quyền phân phối; lệnh verify nhận bản SDK v3.2.0 mà người chạy được phép sử dụng.

Tú xem phần tiêu thụ dữ liệu dự kiến, serialization và loss masking; chưa chuyển thành training data. Nhóm cần chốt 16 hold và xem lại độ đa dạng/quan hệ split. Nếu nhờ người đọc mù Wave 17, chỉ gửi review/blind/reviewer_sheet_vi.md; không gửi key hoặc cả gói gold trước khi họ trả lời.

Đây là lời nhắn dự thảo cho Thắng tự gửi, chưa có tin nhắn hay yêu cầu reviewer nào được gửi tự động.

Gói mã nguồn và bằng chứng có thể chuyển sang máy khác, nhưng replay cần bản SDK được phép sử dụng ở ngoài gói; chấm lại ASR đầy đủ cần các input được phép sử dụng hiện vẫn giữ riêng. Đã xác nhận repository BK-Agentic-Engineering/ava, nhánh gốc main; gói nằm tại workstreams/thang/lifemate-review/. Trạng thái commit/push/Draft PR được ghi riêng trong VALIDATION.md, không suy ra từ việc chuẩn bị gói. VALIDATION.md phân biệt kết quả kiểm tra lịch sử với các kiểm tra của lượt sửa tài liệu này.
