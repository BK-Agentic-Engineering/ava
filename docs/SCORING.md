# Chấm LifeMate local

Nguồn: ảnh công thức BTC người dùng cung cấp và README/catalog/SDK bộ LifeMate.
Implementation local chưa được đối chiếu mã evaluator BTC.

## Công thức

G là danh sách gold, S là toàn bộ call đã gửi, M là số call khớp một-một.

- Gold rỗng: điểm 1 khi S rỗng, ngược lại 0.
- Gold không rỗng: 0 nếu hash state khác gold hoặc M = 0.
- Còn lại: P = M/|S|, R = M/|G|, điểm = 2PR/(P+R) = 2M/(|S|+|G|).
- Điểm cuối = 100 × tổng điểm / N. Lượt thử dùng N = số mẫu subset đã chạy;
  chạy đủ split mới dùng N = số mẫu split.

Ví dụ gold 2 call, dự đoán 3 call, khớp 2 và đúng hash → 0,8.
Cùng các call đó nhưng sai hash → 0. Gold 1 call, dự đoán lặp 2 lần,
chỉ khớp 1 → 2/3 nếu hash vẫn đúng.

## Matching

Tên tool bằng nhau, arguments đối chiếu schema catalog đúng split:

- Không fuzzy: bằng chính xác. Hiện yêu cầu cùng bộ key, array giữ thứ tự;
  boolean không coi như số 0/1.
- `x-match: fuzzy`: lowercase + Unicode NFC; tách theo khoảng trắng,
  đếm multiset giữ số lần lặp; token-F1 **> 0,6**, không phải ≥.
  Không bỏ dấu hoặc dấu câu. Hai chuỗi rỗng coi khớp.
- Maximum bipartite matching: mỗi call chỉ ghép một call phía kia.
  Không greedy vì fuzzy có thể tạo nhiều cạnh giao nhau.
- Call bị SDK từ chối vì schema không thể ghép, vẫn nằm trong |S|, tức U.
- `sys.ask_missing_info` chấm như tool khác.

Thứ tự không ảnh hưởng matching; vẫn ảnh hưởng state khi thực thi.

## Hash và replay

Submission lấy log và hash trực tiếp từ SDK; không tự băm hoặc đọc state.
Sau inference, verifier replay gold bằng ToolEnv mới để lấy hash gold, replay call
dự đoán theo thứ tự bằng phiên khác để đối chiếu hash đã gửi.
Ghi riêng `hash_reproduced`, metric dùng hash đã gửi và metric dùng hash SDK replay.
Không thêm một lần phạt ngoài công thức. Khi hai hash khác nhau, hai metric có thể
khác nhau; không xem điểm dựa trên hash khai báo là kết quả BTC đã xác nhận.
BTC có quyền lấy kết quả replay của họ làm cuối. Không sửa dữ liệu gốc.

History đã áp dụng lúc tạo ToolEnv, không replay history. Không tự ép điểm 0
theo timeout/runner_error ngoài công thức: partial calls và hash thực vẫn được chấm;
vấn đề runtime báo riêng.

## Chưa xác minh với BTC

Ảnh chưa định nghĩa tokenizer, dấu câu/chuỗi rỗng, optional arguments vắng so với
mặc định và các kiểu số tương đương. Các lựa chọn local được ghi rõ trên đây,
chưa khẳng định parity tuyệt đối. Dùng đúng SDK cho hash/validate, nhưng gói SDK
chưa chứa evaluator matching đầy đủ.

Chỉ train có gold để chấm local. Public/private chỉ xuất submission/trace,
không suy diễn nhãn. Điểm train không phải điểm public.
