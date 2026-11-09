# Tin nhắn để Thắng gửi cho nhóm

Snapshot 1.000 mẫu lịch sử bên dưới được giữ nguyên. Bản hiện tại là dataset_v1_candidate: 1.063 ID nguồn, 990 demonstration train và 57 dev đủ điều kiện tích hợp; 16 hold bị loại khỏi demonstration. Các locator riêng của candidate trỏ tới workspace nguồn mới, không trỏ tới snapshot lịch sử. Chưa xác nhận native harness, serialization hay loss masking.

Mình gửi gói review hai phần việc: kết quả benchmark GIPFormer–VALSEA–QUAN trên ViMD/VN-SLU và 1.000 scenario WORLD tổng hợp kèm gold/verifier, provenance và bằng chứng replay cục bộ. 984 case được implementor đánh giá phù hợp trong phạm vi đã kiểm tra; 16 case còn chờ quyết định. Tất cả vẫn spec_only, chưa được export/train hay xác nhận chạy qua harness.

Tài xem README và ba case trong integration/three_cases để đối chiếu cách render Jaz, khởi tạo state sau history, quyền tool, run ID thực, trace/submission và scorer. Gold/state riêng không được đưa vào input model; không chạy lại history. SDK/catalog không đi kèm vì chưa xác nhận quyền phân phối; lệnh verify nhận bản SDK v3.2.0 mà người chạy được phép sử dụng.

Tú xem candidate độc lập model để triển khai serialization và loss masking; chưa chạy training. Nhóm cần chốt 16 hold và xem lại độ đa dạng/quan hệ split. Nếu nhờ người đọc mù Wave 17, chỉ gửi review/blind/reviewer_sheet_vi.md; không gửi key hoặc cả gói gold trước khi họ trả lời.

Đây là lời nhắn dự thảo cho Thắng tự gửi, chưa có tin nhắn hay yêu cầu reviewer nào được gửi tự động.

Gói mã nguồn và bằng chứng có thể chuyển sang máy khác, nhưng replay cần bản SDK được phép sử dụng ở ngoài gói; chấm lại ASR đầy đủ cần các input được phép sử dụng hiện vẫn giữ riêng. Đã xác nhận repository BK-Agentic-Engineering/ava, nhánh gốc main; gói nằm tại workstreams/thang/lifemate-review/. Trạng thái commit/push/Draft PR được ghi riêng trong VALIDATION.md, không suy ra từ việc chuẩn bị gói. VALIDATION.md phân biệt kết quả kiểm tra lịch sử với các kiểm tra của lượt sửa tài liệu này.

Cập nhật benchmark ba model: đề xuất GIPFormer 1.5 làm ASR baseline chính cho LifeMate vì WER/CER thấp nhất trên ViMD, tốt hơn QUAN ở cả hai tập và đã có đường chạy một T4 với revision cố định. Đây là đề xuất chờ nhóm thống nhất. VALSEA tốt nhất trên VN-SLU; giữ làm đối chứng không đồng nghĩa tự động fallback. QUAN dùng FP32 weights/FP16 autocast và sửa attention FP32; ViMD có trong nguồn training công bố, overlap test chưa rõ. Xem closeout và aggregate metrics mới; không có transcript/audio bổ sung. Bước kiểm chứng đề xuất là so sánh cùng tác vụ LifeMate khi dùng transcript gold và audio qua GIPFormer, đo lỗi target/value/time/tool và task/state. Chưa chạy bước này hoặc cập nhật PR.
