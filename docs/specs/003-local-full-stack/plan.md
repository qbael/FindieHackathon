# Kế hoạch chạy đầy đủ tại local

## Constitution check trước nghiên cứu

Giữ React → .NET → RabbitMQ → Python; FastAPI health only. Python sở hữu findie_search, .NET sở hữu findie/R2. Raw chỉ RAM/transport tạm; chỉ output sạch duyệt được index. Không thêm public admin API, không bỏ kiểm quyền/CSRF/idempotency.

## Thiết kế

1. Sửa runner theo đường dẫn hiện tại; bổ sung bootstrap search DB/role/grant idempotent, Hub seed CLI Development và doctor.
2. Tái dùng Ollama adapter với `/api/embed` input ảnh native `{image: base64}`. Full-stack notebook chọn `embeddinggemma-2:440m`, 768 chiều, instruction rỗng; `qwen3-vl:4b` nhận diện vùng qua JSON schema `/api/generate`. Đây là lựa chọn hỗ trợ Ollama theo yêu cầu mới, thay baseline Qwen text-only khi chạy full mode. Không giả lập ảnh bằng caption, không đổi vector cũ sang không gian model mới. Giữ cấu hình text cũ tương thích; cấu hình local đồng bộ hai service và reindex có chủ đích khi đổi model.
3. Decode/EXIF/normalize trong Python, mask kín vùng nhạy cảm từ bbox được validate; encode output mới. Chỉ xử lý bytes trong bộ nhớ. Các thư viện decode ảnh là dependency cần thiết cho trust boundary.
4. Worker ghép full manifest/parts có giới hạn/deadline theo job/lease; kiểm hash/model/source; commit nhiều nguồn một transaction rồi receipt/ACK. Store thêm source_id vào khóa để chứa nhiều ảnh. Query ảnh semantic-only trong image-v1, text hybrid trong text-v1.
5. Notebook pin Ollama release/checksum, pull/check model digest và test inference; bearer proxy allowlist chỉ tags/embed/generate, giới hạn body/concurrency, không access log. Ngrok chỉ expose proxy. Secrets nhập qua Colab Secrets/getpass, không lưu cell output. Cấu hình export không chứa token; local token nhập riêng.
6. Lệnh local-run quản lý web/API/worker và dừng tiến trình đã tạo, không xóa volume. Chạy kiểm thử tích hợp và báo đúng ranh giới chưa có endpoint/cloud thật.

## Constitution check sau thiết kế

Model thay thế là công nghệ bổ trợ theo yêu cầu Ollama, không thay trách nhiệm service hay các bất biến riêng tư. Số chiều lấy từ model cấu hình và kiểm cả hai đầu, không ép 2048 vào model 768. Thay profile/model yêu cầu reindex; không so vector khác model. Colab/ngrok là phiên tương tác do người dùng chủ động vận hành, không cam kết hosting thường trực. Tài khoản cloud, GPU và credential thật là phụ thuộc ngoài repo.

## Phạm vi kiểm chứng

Unit ảnh độc hại/PII/no-PII/failure/digest, tests model request shape, tests assembly/replay/deadline; PostgreSQL/RabbitMQ thật với Ollama stub; API HTTP permissions/concurrency, build/smoke; web tests/build; notebook compile và proxy auth/allowlist/body limits. Model inference trên Colab và OAuth/R2 thật chỉ được đánh dấu verified sau khi thực sự chạy.
