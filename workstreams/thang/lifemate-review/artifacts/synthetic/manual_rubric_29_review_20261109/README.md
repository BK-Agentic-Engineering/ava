# Review ngữ nghĩa 29 rubric cases — 2026-11-09

Kết quả: **28 pass / 0 fail / 1 unresolved** trên các canonical final-answer demonstrations hiện tại. Đã đọc trực tiếp request, context, history, mọi calls/results và rubric của từng case. Đây là review bằng AI có tiếp cận gold và lịch sử dự án, không phải independent/blind human adjudication. Không chấm toàn bộ các alternative/adversarial probes trong lượt này.

Mỗi phán quyết được ràng buộc với exact final text và source trace trong [judgments.jsonl](judgments.jsonl). Đã đối chiếu 29 source selectors và calls với candidate; 29 evidence locators đều resolve. Không chạy lại SDK/model/API và không dùng private WORLD làm bằng chứng cho answer.

## Điểm chưa chốt

`TR12_BANK_LOOK`: số dư, người thụ hưởng, ngân hàng và tài khoản đều đúng. Riêng đơn vị “đồng” được rubric tác giả giả định nhưng không nằm trong agent-visible request/context/history, response hoặc tool schema. Chưa kết luận câu trả lời sai tiền tệ; cần xác nhận quy ước mặc định VND thực sự được render cho agent. Nếu không có, có thể dùng “Số dư Quỹ Ván là 900000; An Tường, ngân hàng Mộc, số tài khoản 12000003.” rồi review/rebuild theo quy trình. Chưa chỉnh target hay eligibility ở lượt chấm này.

Đây là vấn đề mới ngoài 16 holds lịch sử. Candidate đã publish vẫn giữ số ready cũ; báo cáo được bổ sung vào PR theo phê duyệt của Thắng; không tự xác nhận lại eligibility của case trên.

## Kết quả từng case

| Case | Kết quả | Final answer | Căn cứ |
|---|---|---|---|
| TR8_FLIGHT_KEEP | pass | Chưa làm thủ tục. | Chọn vé HAN→HUI ngày 11/2 lúc 11:30, checked_in=false; câu trả lời đúng trạng thái, không nhận là đã check-in. |
| TR8_PODCAST_LOOK | pass | Ngày 10/2/2027. | Nối Đồi Vân với show_id=w8_show_9, chọn Qua Bãi published=2027-02-10; không lấy tập trùng tên của Bến Giấy. |
| TR8_SECURITY_LOOK | pass | Chưa xác nhận. | Báo door tại Cửa Kho lúc 08:05 hôm nay có acknowledged=false; không nhầm với trạng thái bật hệ thống an ninh. |
| TR8_SUB_KEEP | pass | Gói Đèn Chiếu đã bị hủy từ trước. | Đèn Chiếu đã có status=cancelled khi đọc; “từ trước” phân biệt trạng thái có sẵn với hành động vừa thực hiện, không suy ra ngày hủy. |
| TR8_CHORE_LOOK | pass | An Mi phụ trách. | Lau Kệ tại Phòng Mây, done=false, assignee=An Mi; loại bản đã xong của Hạ Thư và bản ở Phòng Sỏi. |
| TR9_CAL_LOOK | pass | Phòng Bậc Đá. | Soát Mẫu Lụa ngày 12/3 lúc 09:00 có location=Phòng Bậc Đá; trả lời đúng phòng được hỏi. |
| TR9_NEWS_LOOK | pass | Bản Tin Sợi. | Bài Góc Khung Sáng thuộc tech có source=Bản Tin Sợi; response broad theo topic không đoán trước nguồn. |
| TR9_PARCEL_LOOK | pass | Giao rồi. | Track không truyền mã đoán; chọn Lưới Chắn, carrier Vệt Gỗ, status=delivered từ response; “Giao rồi” đầy đủ cho câu hỏi yes/no. |
| TR10_REM_LOOK | pass | Hằng tuần. | Cất Kẹp Tre ngày 11/4 lúc 08:30 có repeat=weekly; done=true không thay đổi đáp án về kiểu lặp. |
| TR10_ACCESS_LOOK | pass | Đang khóa. | Cửa Kho Mành có locked=true; “Đang khóa” mô tả khóa, không khẳng định cánh cửa đóng hay mở vật lý. |
| TR10_CLIMATE_LOOK | pass | Chế độ làm mát, 26 độ. | Đúng tên máy và Phòng Nâu; trả lời đủ mode=cool và temperature=26. Không gọi đây là nhiệt độ phòng đo được, không tự thêm Celsius. |
| TR10_ROBOT_LOOK | pass | Lau nhà. | Request hỏi mặc định lưu, nên dùng mode=mop ở cấp trên; không dùng current_job.mode=vacuum. “Lau nhà” đúng chế độ mặc định. |
| TR11_TASK_LOOK | pass | Việc Xếp Kẹp Mây chưa xong, hạn 9 giờ ngày 12/5/2027, ưu tiên thấp. | Request mới nhất chỉ kiểm tra việc đã tồn tại. Response là done=false, due 09:00 ngày 12/5, priority=low; không áp dụng dự định 16:00/cao trong history. |
| TR11_CHORE_LOOK | pass | Hà Khuê. | Lau Khung đang mở ở Phòng Cói hiện giao Hà Khuê. History đề xuất Mộc An không phải state thực tế; target giữ đúng nhiệm vụ chỉ xem. |
| TR11_MUSIC_LOOK | pass | Hạ Khôi. | History chốt Đường Sậy của Hạ Khôi, response có đúng track. Trả lời nghệ sĩ, không phát hay thêm playlist. |
| TR11_ALARM_LOOK | pass | 5 giờ 45. | History chọn Gom Sợi hằng ngày; fresh alarm.list trả time=05:45. “5 giờ 45” không khẳng định enabled=true khi báo thực tế đang tắt. |
| TR11_AUTO_LOOK | pass | 22 giờ. | History chọn Phòng Vải; get_status nối phòng với w11_dev_7, list_rules nối device_id đó với time=22:00. Câu trả lời đúng giờ lịch cũ. |
| TR12_LIB_HELD | pass | Không còn sẵn. | Nét Nẹp của Vũ Trầm có available=false. Target chỉ nói không sẵn, không suy diễn lý do hay ai đang giữ sách. |
| TR12_LIB_LOOK | pass | Không sẵn. | Hai sách Nếp Khung có tác giả khác nhau; bản Đỗ Nguyên available=false, không lấy available=true của Lâm Sương. |
| TR12_BANK_LOOK | unresolved | Quỹ Ván có 900.000 đồng; An Tường, ngân hàng Mộc, số 12000003. | Số dư Quỹ Ván=900000 và An Tường/ngân hàng Mộc/tài khoản 12000003 đều đúng từ hai reads. Tuy nhiên “đồng” chỉ xuất hiện trong rubric/target riêng, không trong request/history/context, response hay schema banking.get_balance. Chưa xác minh một quy ước tiền tệ chung được render cho agent; cần xác nhận quy ước đó hoặc bỏ đơn vị khỏi target. |
| TR12_TV_LOOK | pass | 19 giờ ngày 13/6/2027. | Response có cả ngày 12 và 13 dù query truyền ngày 13; chọn Bến Nẹp/Mây 3 có start ngày 13/6 19:00, không dựa riêng vào filter argument. |
| TR12_ALERT_LOOK | pass | Chưa xác nhận. | Motion alert Sân Nẹp ngày 12/6 lúc 08:00 acknowledged=false; không lẫn cảnh báo Lối Sậy đã xác nhận hay trạng thái arm. |
| TR13_REM_READ | pass | 10 giờ 30. | History có hai creates thành công theo thứ tự; lần sau cùng tạo rem_03. Fresh list xác nhận rem_03 lúc 10:30; không chọn rem_99 hoặc lần create đầu. |
| TR13_APP_READ | pass | Máy Giặt Sậy đang chạy chu trình eco. | History khởi động hist_washer thành công, hist_dryer trả done=false. Fresh list xác nhận Máy Giặt Sậy running/eco; target đúng máy, trạng thái và cycle. |
| TR13_BANK_FAILED | pass | Còn 350.000 đồng, chưa đủ khoản 500.000. | History khoản 500000 bị từ chối vì thiếu tiền; fresh Quỹ Ca Kẹp chỉ còn 350000. Target nêu đúng số dư và kết luận chưa đủ, không đổi sang quỹ 700000 hoặc tự retry. Đơn vị đồng đã có trong history. |
| TR13_BANK_INSPECT | pass | 100.000 cho Lê Thanh Mộc đã chuyển được; 500.000 cho Trần Yến Trúc bị thiếu tiền. | History transfer 100000 cho Lê Thanh Mộc trả transaction; lần 500000 cho Trần Yến Trúc ok=true nhưng done=false/thiếu tiền. Target phân biệt đúng hai lần; request hồi tưởng không đòi fresh read. |
| TR13_BANK_BALANCE | pass | 350.000 đồng. | History xác định quỹ hist_fund_A; fresh response balance=350000. Không dùng 450000 trước chuyển hay 700000 của quỹ còn lại; history đã nêu đồng. |
| TR14_DATE_ONLYLOOK | pass | Lịch Giữ Gỗ ngày 10/8 từ 12 đến 13 giờ. | Giữ Gỗ có start 10/8/2027 12:00 và end 13:00 cùng offset +07. Target nêu đủ khoảng thời gian; bỏ năm vẫn rõ trong context năm 2027, không gọi đây là sự kiện sắp tới. |
| TR14_PICK_SHIPONLY | pass | Đang vận chuyển. | NEP1401 có status=in_transit; “Đang vận chuyển” đúng trạng thái kiện đến, không khẳng định đã đặt lấy kiện gửi. |

## Giới hạn và trạng thái

Pass chỉ xác nhận câu trả lời cụ thể vừa đọc; 29 case vẫn cần manual grading cho câu trả lời mới/chưa biết cách diễn đạt. Không chuyển chúng thành automatic grading. Không thay gold, rubric, eligibility, 16 holds hay canonical traces. Báo cáo được phê duyệt để bổ sung vào Draft PR #5; không merge PR.
