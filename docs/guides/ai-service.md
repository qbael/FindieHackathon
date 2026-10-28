# AI service: văn bản, xử lý ảnh và tìm ảnh qua gateway Colab

Cập nhật 28/10/2026. Python nhận lệnh qua RabbitMQ, gọi gateway tương thích API Ollama, sở hữu database `findie_search` và trả ứng viên để .NET kiểm lại quyền/nguồn/phiên bản. FastAPI chỉ phục vụ health/status nội bộ. Web, API, worker, PostgreSQL và broker ở local; chỉ model inference chạy từ xa.

## Khởi tạo kho tìm kiếm và chạy local

```sh
make local-setup
```

Lệnh cài dependency theo lock, khởi động PostgreSQL/RabbitMQ loopback, migrate database nghiệp vụ, tạo database/role tìm kiếm riêng, migrate schema và cấp DML cho role runtime. Chạy lại giữ dữ liệu và credential; nếu bootstrap cũ có dữ liệu, migration dừng thay vì xóa. Không tự di trú DSN trỏ host/database/role tùy chỉnh. Hub demo được tạo nhưng không tạo tài khoản giả.

Điền Google OAuth/R2 private trong `.env` như README. OAuth redirect: `http://127.0.0.1:5173/api/auth/google/signin`.

## Model trên Colab qua ngrok

Upload [notebook 04](../../notebooks/colab/04_full_stack_ollama_ngrok.ipynb) vào [Colab](https://colab.research.google.com/), chọn GPU và chạy các cell từ trên xuống. Notebook cần `NGROK_AUTHTOKEN` của tài khoản ngrok và `FINDIE_OLLAMA_TOKEN` do bạn chọn (ASCII ngẫu nhiên tối thiểu 32 ký tự). Dùng Colab Secrets hoặc ô nhập ẩn; giữ token thứ hai để nhập lại trên local, không ghi vào cell/chat/git.

Notebook tải model embedding qua Transformers và cài Ollama release/checksum đã ghim cho model nhận diện vùng:

| Model | Vai trò | Cấu hình full mode |
| --- | --- | --- |
| `Qwen/Qwen3-VL-Embedding-2B` | Embedding văn bản và ảnh native qua Transformers | 2048 chiều, FP16, SDPA, L2; instruction truy vấn rỗng |
| `qwen3-vl:4b` | Gợi ý vùng nhạy cảm | JSON schema, temperature 0 |

Model/processor Qwen và mã inference official được ghim tại commit `9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda`, cùng cách lấy token cuối không padding đã kiểm SHA-256 trong notebook 01. Gateway xử lý `/api/embed` bằng Transformers, nhận văn bản hoặc `{image: base64}` và giữ hợp đồng Ollama hiện có; `/api/generate` chuyển tới Ollama cho redaction. System instruction Qwen giống nhau cho hai loại input; `AI_EMBEDDING_QUERY_INSTRUCTION` để rỗng để local không thêm instruction khác. Xem [model card Qwen](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B/tree/9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda).

`AI_EMBEDDING_REVISION` là SHA-256 của manifest JSON chuẩn hóa gồm commit model/processor, hash mã inference đã kiểm, profile và phiên bản gói đã ghim. Đây là fingerprint cấu hình Qwen, không phải digest manifest Ollama. Gateway công bố cùng giá trị qua `/api/tags` để importer và hai service kiểm identity. `AI_REDACTION_REVISION` vẫn là digest manifest Ollama. Cấu hình cũ `qwen3-embedding:4b`/2048 vẫn chạy văn bản; không bật tìm ảnh cho model text-only, không dùng caption/OCR thay embedding ảnh.

Với `AI_IMAGE_SEARCH_ENABLED=false`, vẫn có thể xử lý/duyệt ảnh nếu đã cấu hình model redaction. Worker kiểm đầy đủ manifest và mọi part ảnh, nhưng chỉ ghi vector text cùng watermark/hash gốc; tin có ảnh vẫn tìm được bằng mô tả. Khi bật tìm ảnh, chạy `make local-reindex` để bổ sung vector ảnh từ cùng snapshot.

Trước khi mở tunnel, notebook kiểm model digest, capabilities, embedding text/ảnh và JSON vision trên ảnh tổng hợp, warm cả hai model. Gateway chỉ mở `/api/tags`, `/api/show`, `/api/embed`, `/api/generate` cho model được chọn, bắt buộc Bearer token, giới hạn body/concurrency và tắt access log/traffic inspection. Không expose trực tiếp Ollama, FastAPI, DB hay broker. [Ngrok có hướng dẫn Bearer authentication cho Ollama](https://ngrok.com/docs/gateway/examples/ollama).

Tải `findie-colab.json` ở cell export; file chỉ chứa URL và cấu hình model, **không chứa token**:

```sh
python3 scripts/configure_ollama.py /duong-dan/findie-colab.json
make local-run
```

Lệnh import hỏi cùng `FINDIE_OLLAMA_TOKEN`, kiểm endpoint/token/digest rồi cập nhật `.env` atomically với quyền 0600, đồng bộ model/revision/chiều/profile của .NET/Python. Không thay credential Google/R2/database. URL đổi thì tải/import JSON mới, `Ctrl+C` và chạy lại `make local-run`.

`local-run` đợi worker/model ready trước khi chạy API/web, báo URL `http://127.0.0.1:5173`. `Ctrl+C` dừng đúng web/API/worker của phiên; `make local-stop` dừng DB/broker và giữ volume.

Colab có quota/thời lượng và hạn chế proxy/web services, nhất là tài nguyên miễn phí; đọc [FAQ](https://research.google.com/colaboratory/faq.html) và dùng gói/môi trường cho phép. Notebook phục vụ phiên tương tác do bạn chủ động vận hành, không có keepalive hay cơ chế né giới hạn. Nếu Colab không cho phép mục đích sử dụng này, chạy cùng notebook trên Jupyter GPU bạn kiểm soát. Không cam kết Colab/ngrok luôn sẵn sàng.

## Cấu hình và readiness

| Biến | Ý nghĩa |
| --- | --- |
| `AI_SERVICE_TOKEN` / `Ai__ServiceToken` | Token riêng local .NET↔FastAPI, không gửi lên Colab |
| `AI_SEARCH_DSN` | Role runtime `findie_search_app`, không có quyền DB nghiệp vụ |
| `AI_SEARCH_MIGRATION_DSN` | Role migration riêng cho bước DDL; không dùng cho worker |
| `AI_RABBITMQ_URL` / `RabbitMq__Uri` | Hai tài khoản runtime broker tách biệt |
| `OLLAMA_BASE_URL` / `OLLAMA_API_KEY` | HTTPS gateway ngrok và token riêng của phiên |
| `AI_EMBEDDING_MODEL`, `AI_EMBEDDING_REVISION`, `AI_EMBEDDING_DIMENSIONS` | Model, SHA-256 fingerprint cấu hình Qwen (hoặc manifest Ollama với model cũ) và số chiều; import đồng bộ sang .NET |
| `AI_EMBEDDING_QUERY_INSTRUCTION` | Instruction truy vấn; full notebook để rỗng |
| `AI_REDACTION_MODEL`, `AI_REDACTION_REVISION` | Model vision và digest; đồng bộ `Ai__RedactionModelId`/`Ai__RedactionRevision` |
| `AI_IMAGE_SEARCH_ENABLED` | Bật sau khi xác nhận model embedding nhận ảnh |
| `AI_TEXT_SEARCH_PROFILE`, `AI_IMAGE_SEARCH_PROFILE` | `text-description-v1`, `image-only-v1`, khớp .NET |

Chỉ một Python process, không dùng nhiều Uvicorn workers với queue exclusive. Ngoài loopback cần HTTPS/token cho Ollama và AMQPS cho broker. Token Colab không phải token ngrok hay AI_SERVICE_TOKEN.

```sh
make local-doctor
```

Doctor kiểm schema hai DB, Hub/staff, các queue có consumer, identity model đang chạy, capability AI và API dependency status. Liveness HTTP 200 không đồng nghĩa model/schema đã sẵn sàng. Google/R2 được ghi rõ chỉ configured; cần flow thật dưới đây để xác minh credential/ACL.

## Luồng ảnh và tìm kiếm

1. .NET kiểm quyền/byte và chuyển raw qua AMQP tạm, nonpersistent, có TTL, không DLQ raw.
2. Python kiểm JPEG/PNG/WebP, MIME thật, tối đa 10 MiB, 40 triệu pixel/cạnh 10000, từ chối animation. Áp dụng EXIF orientation, giảm cạnh tối đa 1600px, bỏ EXIF/GPS, flatten alpha và encode PNG mới.
3. Vision model trả bbox/nhãn theo schema, không OCR text; Python validate tọa độ hữu hạn 0..1000/thứ tự/nhãn/số vùng rồi OpenCV che kín với khoảng đệm. Model/JSON lỗi làm cả request thất bại; không dùng raw làm output. Không PII vẫn re-encode.
4. .NET chỉ lưu output hợp lệ lên R2 private. Người có quyền xem và duyệt bản sạch; ảnh chưa duyệt không công khai/index. Nội dung tin được giữ khi xử lý ảnh lỗi.
5. Worker ghép và kiểm manifest text + tối đa 5 output ảnh đã duyệt theo job/lease, hash và deadline; giới hạn pending metadata/bytes. Ghi các vector được bật và watermark/hash của full snapshot trong một transaction, receipt sau commit, ACK sau broker confirm/route. Snapshot cũ sau tombstone không phục hồi dữ liệu.
6. Text dùng semantic + PostgreSQL FTS + tín hiệu vị trí. Ảnh dùng native image vectors semantic-only trong `image-v1`, không tự sinh OCR/keyword. Bộ lọc chạy trước limit; nhiều ảnh cùng món được dedupe. .NET kiểm lại nguồn hiện hành trước DTO.

Ảnh query chỉ tồn tại trong RAM/transport tạm, không R2/search DB. Broker có thể page message xuống đĩa; TTL/ACK không phải bảo đảm xóa forensic. Chỉ model inference ra khỏi máy local; ảnh gửi model đi qua gateway ngrok/Colab của bạn. 1600px và model có thể bỏ sót vùng nhạy cảm nhỏ: phải kiểm output trước duyệt; chưa có cam kết PII recall.

## Hub và nghiệm thu thủ công

Sau lần đăng nhập Google đầu tiên:

```sh
make local-seed STAFF_EMAIL=dia-chi-google-cua-ban
```

CLI Development cấp quyền nhận/trả tại Hub demo cho tài khoản Google đã tồn tại, không đổi hồ sơ hoặc tạo auth bypass. Dùng Google thứ hai để thử claim → duyệt → chat → trao trả; thử riêng intake pending → nhân viên nhận thực tế → trao trả. Dashboard admin đầy đủ và SignalR ngoài phạm vi MVP này.

Để kiểm nhánh ảnh thật: đăng tin có ảnh, kiểm bản che và duyệt, công khai, tìm bằng cả mô tả và ảnh với bộ lọc, rồi gỡ ảnh/ẩn tin và xác nhận kết quả cũ không xuất hiện. Kiểm bucket chỉ có output private, không có original. Đây cũng là bước kiểm credential Google/R2 và model thật.

## Đổi model và lập lại chỉ mục

Không trộn vector khác model/digest/chiều/profile. Khi đổi model: dừng `local-run`, import JSON mới, chạy lại, rồi:

```sh
make local-reindex
```

Việc chuyển từ `embeddinggemma-2:440m`/768 sang Qwen/2048 cần chạy lại notebook 04 từ đầu và tải/import JSON mới, không chỉ sửa tên model trong `.env`. Số chiều trùng với model text-only cũ cũng không làm vector tương thích.

Lệnh kiểm worker identity và chỉ phát lại outbox snapshot/tombstone hiện hành, giữ active leases và dữ liệu người dùng; không xóa watermark. Theo dõi trạng thái lập chỉ mục trước dùng kết quả. Nếu job đang có lease, chờ kết thúc/hết hạn rồi chạy lại khi cần. Baseline có cửa sổ bảo trì, không có chuyển model không gián đoạn.

## Kiểm chứng

```sh
make check
make api-integration
make ai-integration
```

Test ảnh dùng bytes thật để kiểm mask, metadata/EXIF, MIME, pixel, animation, model failure và digest; DB/broker tích hợp dùng container tạm, không DB local. Model trong integration là HTTP stub; Google và R2 dùng test double. Notebook được compile/self-check gateway nhưng Colab GPU/ngrok thật cần người sở hữu chạy. Chưa có benchmark chất lượng/VRAM/độ trễ thực tế. Tập dữ liệu có nhãn và `python -m findie_ai.evaluate` vẫn cần trước mọi tuyên bố độ chính xác.
