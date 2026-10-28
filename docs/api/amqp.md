# Hợp đồng .NET ↔ Python qua RabbitMQ

Phiên bản schema 1, ngày 24/10/2026. Đây là hợp đồng adapter .NET đã triển khai;
worker Python/search database đã thực thi text, image.redact, native image search và full manifest/parts theo [hướng dẫn AI](../guides/ai-service.md). FastAPI chỉ health. Receipt chỉ sau kiểm full manifest và commit projection được bật; model/credential thật vẫn cần nghiệm thu.
Tài liệu nền: [kiến trúc](../architecture/system-architecture.md); API HTTP:
[nghiệp vụ](recovery.md), [ảnh/tìm kiếm](media-search.md).

## Kết nối, topology và bảo vệ dữ liệu

`RabbitMq:Uri` rỗng: adapter tắt, API cơ bản vẫn hoạt động. Có URI: một kết nối lâu dài,
heartbeat 30 giây, channel publish confirms/mandatory riêng và channel consumer riêng;
reconnect ban đầu/mất kết nối backoff 1–30 giây + jitter. Không mở connection mỗi request.
Yêu cầu AMQPS có kiểm chứng certificate ngoài loopback; AMQP chỉ được phép local loopback.
Không log URI/credential, ảnh, query, OCR, answer hoặc message body.

| Queue mặc định | Chủ provisioning và tính chất |
| --- | --- |
| `findie.ai.commands` | Ops tạo durable quorum, persistent index commands/output parts, TTL 30 giây, DLX/retention hữu hạn |
| `findie.api.results` | Ops tạo durable quorum, persistent index receipts, TTL hữu hạn và DLX; .NET kiểm queue tồn tại khi kết nối |
| `findie.ai.image` | Python tạo non-durable/exclusive/auto-delete, nonpersistent raw input/query, TTL tối đa 30 giây, trần byte/số message; **không DLX/alternate routing/tracing body** |
| `findie.ai.query` | Python tạo queue text query tạm, non-durable/exclusive/auto-delete, TTL hữu hạn |
| Reply queue do broker sinh | .NET tạo exclusive/non-durable/auto-delete cho output ảnh/query; TTL 60 giây, tối đa 64 message/32 MiB; không DLX |

Có thể đổi tên qua `RabbitMq:IndexQueue|ResultQueue|ImageQueue|QueryQueue`; chỉ server
cấu hình, không nhận route/reply_to từ HTTP client. Định nghĩa durable queues mẫu tại
[rabbitmq-definitions.json](rabbitmq-definitions.json), import bằng công cụ quản trị broker
vào vhost `/` hoặc sửa vhost theo môi trường. File không chứa user/password/permission;
ops cấp tài khoản triển khai và tài khoản API/Python tách biệt. .NET chỉ publish commands,
consume results và khai báo/consume reply queue của mình; Python làm chiều ngược lại.
Không dùng quyền admin cho runtime. Không đưa RabbitMQ ra internet.

Local có thể chạy `make rabbitmq-up` theo [hướng dẫn Docker](../guides/development.md#rabbitmq-docker):
Compose tự import topology cùng một admin và hai tài khoản runtime riêng, mật khẩu
sinh trong `.env`. Quyền configure/consume được giới hạn theo queue. Cả hai client
hiện publish qua default exchange, nên quyền write exchange này cho phép route tới
các queue trong cùng vhost; ACL local không giới hạn được từng routing key theo chiều.

Raw chỉ ở RAM ứng dụng; RabbitMQ có thể page transient message xuống đĩa. TTL/ACK không
phải cam kết xóa forensic tức thì. Phải loại raw queues khỏi log/tracing/DLQ/backup ở broker
và tắt request body buffering/logging ở reverse proxy. Durable queue chỉ chứa output sạch,
snapshot công khai và receipt metadata, không original/query image.

## Envelope AMQP

`BasicProperties`: `Type` là operation bên dưới, `CorrelationId` UUID do .NET tạo,
`ReplyTo` queue do .NET chỉ định, `ContentType`, `Persistent`, `Expiration:"30000"`.
Header `metadata` là **bytes JSON UTF-8**, tối đa 16 KiB. Body ảnh nhị phân tối đa 10 MiB;
body text/snapshot/ứng viên JSON UTF-8, không base64. Tối đa 32 waiter AI đang chờ;
deadline 30 giây, không giữ DB transaction khi gọi broker hoặc model/R2.

Metadata request chung: `schemaVersion:1`, `deadlineAt` ISO UTC, định danh model/version
và profile tùy operation. Worker kiểm deadline trước suy luận và trước commit.
Metadata response phải echo định danh/configuration của request, thêm
`kind:<operation>`, `succeeded:true|false`. .NET chỉ hoàn tất đúng correlation còn sống.
Lỗi an toàn `succeeded:false` thành HTTP 503; không trả trace/OCR/dữ liệu worker ra client.

## image.redact

Route `findie.ai.image`, nonpersistent, body raw ảnh. Metadata:
`schemaVersion,imageId,itemId,sourceVersion:1,sourceSha256,modelId,modelRevision,
processingProfile,deadlineAt`. Full mode dùng `qwen3-vl:4b`; modelId/revision phải khớp cấu hình đã ghim của hai service.

Worker luôn decode, kiểm MIME/frame/pixel, phát hiện PII, che/mờ nếu có, bỏ EXIF và encode
ảnh mới kể cả không có PII. Lỗi model không được coi là ảnh sạch. Response body là output,
metadata echo nguồn/config, thêm `kind:"image.redact",succeeded,contentType,sha256,
byteSize,width,height,sensitiveRegions:[]`. Không trả original key, OCR text riêng tư hoặc
URL bất kỳ. Python không có credential R2.

.NET kiểm hợp đồng/hash/byte và chỉ lưu output. Reply bị trùng/muộn/không còn waiter được
ACK/bỏ; lỗi cuối không đưa original vào DLQ. Crash mất raw thì HTTP client phải tải lại.

## search.hybrid và search.hybrid.image

Text: query queue, body `{text,area,from,until}` JSON. Image: image queue, body raw query
nhị phân, nonpersistent, không R2/job/outbox/vector query bền vững.

Metadata: `schemaVersion,modelId,modelRevision,processingProfile,searchProfileId,
searchProfileVersion:1,mode,area,from,until,limit,candidateLimit:200,deadlineAt`.
Processing profile `text-v1|image-v1`; cấu hình text-only giữ `qwen3-embedding:4b`/2048. Notebook full mode chọn `embeddinggemma-2:440m`/768, nhận ảnh native qua Ollama. `modelId`, digest và số chiều phải đồng bộ hai service; không dùng model text cho ảnh.
Text profile mặc định `text-description-v1`, image `image-only-v1`. Đây là baseline,
chưa có benchmark/phân loại profile theo độ đặc thù query.

Response metadata echo model/profile, thêm kind/succeeded. Body tối đa 256 KiB:

```json
{
  "candidates": [
    {
      "itemId": "<uuid>",
      "documentVersion": 5,
      "sourceId": "<itemId cho text, imageId cho image>",
      "sourceVersion": 2,
      "sourceSha256": "<64 lowercase hex>"
    }
  ]
}
```

Tối đa 200 candidate, thứ tự là rank đã tính tại Python; không trả vector cho .NET.
Python có thể thêm hạng/điểm dense/keyword/RRF để chẩn đoán, API hiện chỉ xuất rank.
.NET kiểm lại toàn bộ eligibility, document/source version/hash và bộ lọc trước DTO;
không tự nới lọc hoặc refill vô hạn. Không coi RRF/cosine là xác suất sở hữu.

## index.upsert, index.source.image và index.remove

Mọi thay đổi ảnh hưởng hiển thị/tìm kiếm ghi một outbox cùng transaction item, gồm
`itemId,documentVersion,kind,document,sources`. `document` chỉ trường công khai;
`sources` là manifest đầy đủ gồm text và ảnh ready/approved/validated, mỗi nguồn có
`kind,id,version,sha256,processingProfile`. Text hash là SHA-256 UTF-8 của
`title + "\n" + publicDescription`; image hash là output bytes. Không snapshot answer/chat.

Checksum snapshot: JSON key sắp ordinal đệ quy, array giữ thứ tự, JSON compact UTF-8 với
escaping của System.Text.Json; hash SHA-256 lowercase hex. Worker có thể xác minh trực tiếp
body bytes do .NET gửi (đã canonicalize), không cần tái tạo escaping bằng serializer Python.
.NET canonicalize lại sau PostgreSQL jsonb roundtrip để không bị lệch whitespace/thứ tự key.

Dispatcher lease một outbox đến hạn bằng `FOR UPDATE SKIP LOCKED`, tăng attempt, lease
90 giây, commit trước publish. Metadata lệnh:
`schemaVersion,jobId,leaseToken,itemId,documentVersion,snapshotSha256,modelId,
modelRevision,dimensions,deadlineAt`; số chiều lấy từ cấu hình hai service.

- `index.upsert`: persistent JSON body full snapshot. Sau manifest, .NET gửi mỗi approved
  image bằng `index.source.image`, persistent binary body chỉ output. Part metadata gồm
  cùng job/lease/snapshot/model và `sourceId,sourceVersion,sourceSha256,processingProfile`.
  Cùng correlation/reply queue; worker phải tập hợp manifest/parts theo job + lease,
  kiểm source và chỉ trả receipt sau khi các nguồn cần thiết đã commit hoặc được xác nhận
  đã có cùng version/hash. Không trả receipt riêng cho từng part.
- `index.remove`: persistent JSON tombstone, `document:null,sources:[]`; không gửi ảnh.
  Watermark/tombstone ngăn upsert cũ phục hồi dữ liệu đã gỡ.

Worker ghi search projection/vector/FTS trong transaction riêng ở `findie_search`.
Snapshot mới hơn thắng; cùng version/hash là replay hợp lệ, cùng version khác hash là
conflict. Kiểm lại watermark/source trước commit embedding lâu. ACK command/parts chỉ sau
receipt được broker confirmed và routed. Crash giữa các parts cho phép replay cùng snapshot;
payload tạm từng lease có deadline và retention, không chờ vô hạn.

Khi `AI_IMAGE_SEARCH_ENABLED=false`, worker vẫn nhận/kiểm hash, MIME và decode mọi part
ảnh trong full manifest trước receipt, nhưng chỉ ghi projection `text-v1`. Watermark và
snapshot hash giữ nguyên full snapshot; tin có ảnh vẫn tìm được bằng text. Bật tìm ảnh
rồi reindex cùng version/hash sẽ bổ sung toàn bộ vector ảnh, không cần sửa outbox payload.

Receipt: `Type` và metadata `kind` là `index.upsert|index.remove`, persistent tới durable
result queue; metadata echo toàn bộ job/lease/item/document/hash/model/dimensions và thêm
`schemaVersion:1,succeeded:true,committed:true`; không cần body ảnh. `committed:true` có
nghĩa Python **đã commit** search transaction, không đồng nghĩa .NET đã commit.

.NET khóa item rồi job, kiểm receipt và lease hiện hành, version/source current; đánh dấu
`succeeded` hoặc `obsolete` rồi commit, **sau đó ACK**. Receipt đến sau khi mất waiter hoặc
restart vẫn được xử lý từ durable queue. Lease cũ/trùng/đã hết hạn được chủ đích bỏ/ACK,
không hoàn tất lease mới. Poison/DB lỗi ở đường receipt orphan được NACK không requeue
vào DLX hữu hạn; job vẫn bền vững để lease/retry phục hồi. Không requeue nóng vô hạn.

Broker/storage lỗi thành retry với backoff `5 * 2^attempt` giây, tối đa 3 attempt;
invalid result thành failed. Lease running hết hạn được lấy lại; hết attempt thành failed.
Snapshot không còn current được obsolete. Failed job cần vận hành xử lý/reindex có chủ
đích, không tạo job mới vô hạn để né giới hạn. Không có admin/retry endpoint công khai.

## Cleanup output

Cleanup kiểm tra ngay khi API khởi động và sau đó mỗi 10 phút, mỗi lượt xử lý tối đa một
object; việc kiểm tra outbox vẫn chạy mỗi 2 giây.

Reservation chỉ được tạo sau output hợp lệ, hết hạn sau một giờ. Khi gỡ ảnh, bỏ liên kết
và đánh dấu object delete_pending cùng transaction. Cleanup chỉ claim object không được
image tham chiếu, khóa object rồi commit trước R2 delete. Attachment khóa/reload object và
từ chối reservation đã hết hạn/đang dọn. Retry delete tối đa 5 lần, đặt hạn thử lại sau 2–8 phút
và xử lý ở lượt cleanup kế tiếp; sau giới hạn giữ error metadata để vận hành xử lý.
Không dọn original vì không có original.

## Nguồn kỹ thuật và kiểm chứng

Adapter dùng [RabbitMQ .NET client API](https://www.rabbitmq.com/client-libraries/dotnet-api-guide)
và [confirms/acknowledgements](https://www.rabbitmq.com/docs/confirms).
[BrokerChecks.cs](../../apps/api/tests/integration/BrokerChecks.cs) kiểm request/reply trên broker
thật dùng một lần; [ImageSearchChecks.cs](../../apps/api/tests/integration/ImageSearchChecks.cs)
kiểm DB/outbox/output bằng adapter doubles. Worker Python được kiểm riêng với broker/PostgreSQL thật ở `make ai-integration`; model là HTTP stub. ACL/TLS môi trường triển khai, R2 thật và benchmark mô hình chưa được nghiệm thu qua các test này.
