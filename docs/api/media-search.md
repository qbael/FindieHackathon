# API ảnh và tìm kiếm

Quy ước cookie, CSRF, lỗi và idempotency tại [API nghiệp vụ](recovery.md#quy-ước-chung).
Ảnh/tìm kiếm có giới hạn 20 request nặng/phút/tài khoản, vượt trả **429**.
Upload và truy vấn ảnh nhận **body nhị phân**, không `multipart/form-data`, base64,
URL ảnh hoặc đường dẫn file từ client. .NET đọc trực tiếp stream vào RAM tối đa **10 MiB**,
không dùng `IFormFile` hoặc ghi tệp tạm. Python chịu trách nhiệm giải mã/kiểm ảnh thực.

Phần .NET có adapter AMQP/R2; worker Python hỗ trợ text, che/chuẩn hóa ảnh và tìm ảnh native qua Ollama theo [hướng dẫn](../guides/ai-service.md). Cần cấu hình broker, private bucket và model/revision có capability phù hợp. Chưa có worker trả kết quả thì báo **503**,
không giả lập kết quả hoặc lưu original. Xem [cấu hình local](../guides/development.md).

## GET /api/items/{itemId}/images — trạng thái ảnh dành cho quản lý

Quyền: người quản lý nơi giữ hiện tại (person holder, external author, point canReceive).
Response **200** mảng `ImageResponse`, có cả ảnh đã gỡ để đối chiếu:

```json
{
  "id": "<uuid>",
  "itemId": "<uuid>",
  "position": 1,
  "contentVersion": 1,
  "processingState": "needs_review",
  "reviewState": "pending",
  "failureCode": null,
  "previewUrl": "/api/items/<itemId>/images/<id>/content"
}
```

`previewUrl` chỉ trỏ output đã lưu hợp lệ; null khi gỡ/không có output. Không trả
bucket/object key, original, OCR hoặc credential. Không có item **404**, thiếu quyền **403**.
Người xem thông thường lấy ảnh được duyệt từ `GET /api/items/{id}`.

## POST /api/items/{itemId}/images?position=1 — xử lý và tải output

Quyền quản lý như trên, item còn active. Header:
`Content-Type: image/jpeg|image/png|image/webp`, `X-CSRF-TOKEN`, `Idempotency-Key`.
Query `position=1..5`, mặc định 1; mỗi vị trí có tối đa một ảnh chưa gỡ.

```sh
curl -b cookies.txt -H 'X-CSRF-TOKEN: <token>' -H 'Idempotency-Key: <uuid>' \
  -H 'Content-Type: image/jpeg' --data-binary @wallet.jpg \
  'http://127.0.0.1:5080/api/items/<itemId>/images?position=1'
```

Response **201** `ImageResponse`, `Location` trỏ content. Các bước:

1. Kiểm quyền/byte, hash input trong RAM và gửi `image.redact` tạm qua AMQP.
2. Kiểm schema, source ID/version/hash, model/revision/profile, MIME signature, số byte,
   hash output, dimensions (tối đa 10000 mỗi chiều và 40 triệu pixel). .NET không decode ảnh.
3. Chỉ sau output hợp lệ mới ghi reservation loại `processed`, upload output vào R2
   ngoài transaction, rồi khóa item/object và gắn output thành `needs_review`.
4. Nếu item/quyền đã thay đổi trong khi xử lý, không gắn output cũ. Reservation hết hạn
   sau một giờ để cleanup. Dữ liệu gốc bị bỏ khi hoàn tất/lỗi/hủy.

Sai MIME **415**, body rỗng **400**, quá 10 MiB **413**, vị trí/version đã đổi hoặc đã trả
**409**, sai quyền **403**, output sai hợp đồng **502**, AI/broker/R2 chưa sẵn sàng **503**.
Không có output hợp lệ thì không tạo object/reservation. Lỗi upload R2 có thể để lại
reservation output để dọn; không để lại image đã gắn hoặc báo đăng ảnh thành công.
Gửi lại đúng khóa/input trả cùng ảnh, không chạy AI/upload thêm. Cùng khóa ảnh khác **409**.

## POST /api/items/{itemId}/images/{imageId}/review — duyệt hoặc từ chối

Body `{"contentVersion":1,"decision":"approved"}` hoặc `decision:"rejected"`.
Yêu cầu CSRF và idempotency; quyền quản lý hiện tại. Response **200** `ImageResponse`.
Chỉ review output validated ở `needs_review|ready`, đúng version và item active.
Approved → `ready`; rejected → `rejected`. Có thể từ chối output từng được duyệt để
thu hồi công khai. Từ chối rồi muốn dùng ảnh khác thì gỡ ảnh và upload lại.
Ghi reviewer/time phía server, tăng row/document version và snapshot/tombstone nguyên tử.
Sai quyền **403**, ảnh không thuộc món **404**, version cũ/đã gỡ/trạng thái sai **409**.

## POST /api/items/{itemId}/images/{imageId}/retire — gỡ output

Body `{"contentVersion":1}`, CSRF và idempotency. Response **200** `ImageResponse`.
Quyền quản lý hiện tại. Ghi retiredAt, tăng source version, bỏ liên kết object, đánh dấu
output `delete_pending`, cập nhật outbox cùng transaction. Không xóa lịch sử món đồ.
Version sai/đã gỡ **409**, sai quyền **403**, ảnh không thuộc món **404**.
Cleanup xóa R2 sau commit; lỗi được retry tối đa 5 lần, sau đó cần vận hành xử lý.

## GET /api/items/{itemId}/images/{imageId}/content — đọc output

Response **200** bytes với MIME đã kiểm, `Cache-Control:no-store`,
`X-Content-Type-Options:nosniff`. Người xem thông thường chỉ đọc khi item published/active
và output ready/approved/validated/chưa gỡ. Quản lý hiện tại được xem trước output
validated chưa duyệt. Kiểm lại quyền/source sau khi đọc R2 để không trả ảnh vừa bị thu hồi.
Không đủ điều kiện/đã gỡ/ảnh thuộc món khác **404**; R2 lỗi/hash lệch **503**.
Không cung cấp endpoint original, download URL original hoặc presigned upload cho trình duyệt.

## POST /api/search — tìm bằng mô tả tiếng Việt

Cookie + CSRF; không yêu cầu Idempotency-Key vì không lưu query/job nghiệp vụ.

```json
{
  "text": "Ví đen, khóa kéo vàng, không có dây đeo",
  "area": "Công viên Bờ Sông",
  "from": "2026-10-01",
  "until": "2026-10-24",
  "limit": 10
}
```

`text` 1–2000 sau trim, bắt buộc; `area` tùy chọn tối đa 200;
`from/until` tùy chọn, ngày bao gồm hai đầu; `limit=1..10`, mặc định 10.
Không bắt ảnh. Gửi JSON tới Python qua AMQP `search.hybrid`; Python chọn thuật toán
ngữ nghĩa/từ khóa theo profile cấu hình. .NET không đọc vector/search database.

Response **200**:

```json
{
  "items": [{"rank":1,"item":"<ItemResponse như API món đồ>"}],
  "mode": "text",
  "searchProfileId": "text-description-v1",
  "searchProfileVersion": 1,
  "partial": false,
  "filtersRelaxed": false,
  "fallbackUrl": "/api/items"
}
```

`rank` là vị trí gợi ý sau kiểm tra nghiệp vụ, không phải xác suất sở hữu. Response
thực tế `item` là object ItemResponse. .NET kiểm lại published/active, document/source
version/hash, model/profile và bộ lọc hiện tại, bỏ ứng viên cũ/trùng, giữ thứ tự còn lại.
Tối đa 200 ứng viên, không refill tự động; `partial:true` khi bỏ ứng viên khiến kết quả
chưa đủ limit. Không tự nới bộ lọc. Kết quả hợp lệ rỗng là **200** với `items:[]`.

Input rỗng/khoảng ngày sai (kể cả from=0001-01-01 hoặc until=9999-12-31) **400**; response AI sai schema/model **502**;
broker/model/search store thiếu hoặc timeout 30 giây **503**. Lúc lỗi dùng
`GET /api/items?area=...&from=...&until=...` để lọc cơ bản; không đổi lỗi thành rỗng.
Tên profile là hợp đồng cấu hình, chưa phải chứng nhận đạt chất lượng tìm kiếm.

## POST /api/search/image — tìm bằng ảnh

Cookie + CSRF, body ảnh JPEG/PNG/WebP nhị phân tối đa 10 MiB. Query `area`, `from`,
`until`, `limit` như tìm text. Response **200** cùng SearchResponse, `mode:"image"`,
profile mặc định `image-only-v1`. Gửi AMQP `search.hybrid.image` nonpersistent/TTL;
chỉ dùng nguồn ảnh sạch đã duyệt khi kiểm tra ứng viên. Không bịa OCR/nhánh keyword.

```sh
curl -b cookies.txt -H 'X-CSRF-TOKEN: <token>' -H 'Content-Type: image/png' \
  --data-binary @query.png 'http://127.0.0.1:5080/api/search/image?limit=10'
```

Sai MIME **415**, quá byte **413**, body rỗng/bộ lọc sai **400**, dịch vụ **502/503** như
tìm text. Ảnh query không lưu DB/R2/outbox hoặc lịch sử; input bị bỏ sau request.
Không kết hợp text và image scores trong cùng truy vấn; client chọn một endpoint.

## Cấu hình cần thiết

```dotenv
RabbitMq__Uri=amqps://<user>:<password>@<private-host>/<vhost>
Ai__RedactionRevision=<immutable-model-revision>
Ai__EmbeddingRevision=<immutable-model-revision>
Storage__Endpoint=https://<account-id>.r2.cloudflarestorage.com
Storage__Bucket=<private-output-bucket>
Storage__AccessKeyId=<server-only>
Storage__SecretAccessKey=<server-only>
```

Giữ bucket private, tắt public domain/r2.dev, credential chỉ cho bucket output.
Model ID/profile mặc định trong `apps/api/appsettings.json`, được cấu hình Ollama văn bản trong `.env.example` ghi đè. Revision rỗng/main/latest
bị từ chối; phải ghim revision đã triển khai trong Python. Không gửi các biến này vào React.
Adapter R2 dùng [SDK AWS .NET theo hướng dẫn Cloudflare](https://developers.cloudflare.com/r2/examples/aws/aws-sdk-net/).
Chưa kiểm chứng Cloudflare R2 thật hoặc độ chính xác mô hình; xem [kiểm thử](testing.md).
