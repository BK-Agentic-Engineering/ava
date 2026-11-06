> Historical/source document. Verified locally 2026-11-06; not a current compliance certification. Current status: package README.

# Giao việc MILESTONE 1

ASR model: https://huggingface.co/g-group-ai-lab/gipformer1.5-68M-rnnt
LLM: https://huggingface.co/LiquidAI/LFM3-1.7B
Github: https://huggingface.co/LiquidAI/LFM3-1.7B

## Lưu ý chung:
- Không được xài data `train` mà cuộc thi cho để train. Data đó dùng để test. Coi data public test như là holdout.
- TEMPERATURE = 0. TEMPERATURE = 0. TEMPERATURE = 0. TEMPERATURE = 0. Nhớ kỹ nha. Cái nào quan trọng nói lại nhiều lần.
- Mindset đúng là data bây giờ quá dễ, private sẽ khó hơn hẵn. Có các trường hợp fail sau đây: accent voice quá đặc khiến cho voice ko nhận dạng được, từ lóng hoặc yêu cầu mơ hồ khó hiểu -> agent gọi sai tool, yêu cầu cần nhiều bước hẵn so với public test, lỗi call tool mà ko self-heal đc, etc.
- Không xài RAG hay search để kiếm và gọi tool. Tốt nhất là tool nằm trong harness như các harness hiện đại để model tự nhớ và gọi. Lí do là model được train theo dữ liệu hiện đại là kiểu này và tối ưu KV Cache, tốc độ.
- Làm xong Pull Request lên repo, không push thẳng để người khác review. Viết code sạch, không nhảm nhí, không slop. Prompt:
```
Follow conventions, common sense, best practices with naming and directory. Keep everything concise, intuitive over pretending to be professional.
Strictly prohibit assurance theatre and ceremonial safeguards: practices or procedures that appear rigorous but add no meaningful scientific or engineering value while increasing cognitive, time, or token cost. Examples include unnecessary missingness reports, arbitrary random seeds, random gates, deterministic fallbacks, and redundant validation. Remove such measures when found and do not propagate them.
```
- Luôn luôn Literature Review trước khi làm, tìm cái mới nhất, tiên tiến nhất, không xài đồ cũ. Nếu cái nào cập nhật lần cuối trước tháng 9 thì cần kiểm tra lại xem có SOTA hay không. Ưu tiên repo Github nhiều sao hơn Arxiv 0 cite. Shortlist một số ứng viên rồi chọn ra cái nào phù hợp với dự án nhất.
- Tương tự, không tự phát minh lại từ đầu, cái nào có code production rồi thì copy về r sửa. Chỉ viết lại từ đầu nếu dễ hơn và hợp lý hơn.

## Tài: Setup workspace repo đầu cuối.
- Inference 16-bit. Không xài quantized.
- Minimal harness. Ưu tiên xài các framework phổ biến, tránh viết lại từ đầu. Nên nghiên cứu xem cái nào nhỏ gọn nhất có thể và có hiệu quả tốt nhất.
- Lưu lại traces của model cho từng kiểm tra. Tạo code đánh giá Score giống trong metric đề bài. Có thể dùng file submission public test để xem score đúng chưa (score trên train và trên public test không chênh quá nhiều). Cần làm cái này để (agent) kiểm tra local nhanh hơn thay vì phải nộp trên web mất thời gian.

Đầu ra: 1 pipeline hoàn chỉnh có thể tạo ra file submission đầu cuối có kết quả chấm local chính xác.

## Thắng: Tạo data để train model.
- Test valsea với model voice trên bench giọng vùng miền của model voice (trang chính huggingface). Có thể valsea mạnh hơn, nếu mạnh hơn thì có thể dùng để train voice model sau.
- Sử dụng model xịn như gpt-6 để tạo ra các WORLD mà trường hợp giả định fail nói trên lưu ý chung. Sau đó tạo gold state và pipeline tạo data training sau khi chốt harness.
- Dự đoán nhiều trường hợp fail hơn.

Đầu ra:
- kết quả bench giữa model và valsea
- 1 tệp WORLD mà model có khả năng cao sẽ fail.

## Tú: Nghiên cứu cách train model đạt hiểu quả cao nhất.
- Tự tạo ra môi trường để model interact với state và tools trước. Thực hiện thí nghiệm lên data train. Không chờ Tài. Khi Tài xong thì integrate chung.
- Kiếm các metric để kiểm khả năng gọi tool và đánh giá, tối ưu harness. Keyword để search: Prefix Invariance / Prefix Stability, structural variance, schema drift, Prefix Invariance / Prefix Stability, Token Logit Entropy / Decoding Uncertainty, and token noise.
- Tìm cách cải thiện model trước train như system prompt (GEPA), tool description, etc. Thông thường nên để ngắn nhất có thể nhưng vẫn chính xác về độ semantic. Cách gọi, khi nào gọi (trigger), tại sao gọi nên rõ ràng cụ thể để model hoạt động tốt hơn. System prompt cũng có thể tiếp cận như "hãy phân tích yêu cầu người dùng trước khi tiến hành" để tránh từ lóng, yêu cầu mơ hồ. Agent hoạt động tốt nhất khi có Goal rõ ràng và cụ thể nhất.
- Tìm cách train tốt nhất: DPO VS GRPO, CPT cho từ lóng và yêu cầu mơ hồ (NẾU THỰC SỰ CẦN và system prompt không thể làm), multi-stage. Trên huggingface của LFM có notebook ví dụ có thể tham khảo. Bắt buộc full-param training, không LORA, QLORA, DORA, etc.

Đầu ra:
- Hoàn thiện hoàn toàn 3 ý đầu và có sản phẩm
- Plan kỹ thuật rõ ràng cho ý cuối