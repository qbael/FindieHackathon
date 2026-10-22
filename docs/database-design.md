# Thiết kế cơ sở dữ liệu Findie

**Phiên bản:** 1.0.1 · **Ngày:** 2026-10-22 · **Trạng thái:** thiết kế MVP đề xuất, chưa triển khai ứng dụng.

Thiết kế dựa trên [đặc tả](DAC_TA_FINDIE.md), [kiến trúc](system-architecture.md) và
[hiến chương](../.specify/memory/constitution.md). Dữ liệu nghiệp vụ lưu trong PostgreSQL;
ảnh lưu ở **Cloudflare R2 riêng tư**, PostgreSQL chỉ giữ thông tin tệp, khóa đối tượng và trạng thái.
Các yêu cầu đã chốt không bị thay thế bởi các giả định triển khai trong tài liệu này.

Tệp đi kèm:

- [ERD chỉnh sửa bằng draw.io](findie-erd.drawio).
- [DDL PostgreSQL](database-schema.sql): tạo mới 16 bảng và các chỉ mục/ràng buộc trong một giao dịch.
- [Mô tả các cột](database-column-dictionary.md): kiểu dữ liệu, NULL, ý nghĩa và ràng buộc của đủ 164 cột trong 16 bảng.
- [Tự kiểm ràng buộc SQL](database-check.sql): dữ liệu thử được rollback sau khi kiểm tra.

Mở `findie-erd.drawio` bằng **File → Open from → Device** trong [draw.io](https://app.diagrams.net/).
Sơ đồ có 5 trang: tổng quan; tài khoản và món đồ; yêu cầu nhận và chat; tiếp nhận và trao trả;
R2 và xử lý AI. Ngay trang tổng quan đã có đủ 16 bảng, 164 cột, kiểu dữ liệu, NULL, PK/FK và
các ràng buộc duy nhất; phóng to để đọc từng bảng. Các trang chi tiết tách theo nhóm nghiệp
vụ; FK người thực hiện được ghi trong bảng để tránh đường nối chồng chéo.
DDL là nguồn đối chiếu khi thay đổi lược đồ; các điều kiện phân quyền/giao dịch vẫn cần .NET
thực thi theo các mục dưới đây.

## 1. Phạm vi và các lựa chọn thiết kế

Một cơ sở dữ liệu phục vụ API nghiệp vụ .NET, hội thoại bền vững và tác vụ nền. Không thêm Redis,
message broker, cơ sở dữ liệu tìm kiếm riêng, lịch hẹn, thanh toán hay vận chuyển.
FastAPI nhận dữ liệu đã được .NET cho phép xử lý; không có tài khoản truy cập DB nghiệp vụ.

| Lựa chọn | Cách áp dụng |
| --- | --- |
| PostgreSQL + pgvector | `vector(2048)` cho Qwen/Qwen3-VL-Embedding-2B; tìm cosine chính xác trước |
| Khóa chính | UUID do .NET sinh; UUID không phải bằng chứng có quyền truy cập |
| Xác thực đề xuất | OpenID Connect, Authorization Code + PKCE qua .NET; phiên cookie `HttpOnly`, `Secure`, chính sách `SameSite` phù hợp và chống CSRF |
| Tài khoản | Ánh xạ duy nhất `(auth_issuer, auth_subject)`; không dùng email làm khóa định danh; không lưu mật khẩu/token đăng nhập trong các bảng này |
| Quyền tại điểm | Cặp `(point_id, user_id)` cùng `can_receive`, `can_return`, `revoked_at`; vai trò không lấy từ request của React |
| Thời gian sự kiện | `timestamptz`, phiên DB dùng UTC; giao diện dùng `Asia/Ho_Chi_Minh` |
| Thời điểm nhặt | Ngày địa phương hoặc khoảng thời gian, có độ chính xác riêng; không đổi ngày không biết giờ thành 00:00 giả |
| Ảnh | Một bản gốc riêng tư; các bản xử lý được lưu thành đối tượng riêng; chỉ bản đã kiểm tra và phê duyệt được hiển thị |
| Xóa dữ liệu | Mặc định `ON DELETE RESTRICT`; gỡ hiển thị/vô hiệu hóa trước, xóa theo quy trình có chủ đích sau khi chốt thời hạn lưu |

OIDC và cookie là **phương án đề xuất**, chưa chốt nhà cung cấp, cách đăng nhập, thời hạn phiên
hoặc quyền đọc khi chưa đăng nhập. DDL độc lập với bảng của nhà cung cấp danh tính. Các giới hạn
độ dài chuỗi trong DDL là giá trị cơ sở đề xuất để triển khai, không phải quyết định sản phẩm đã nghiệm thu.

## 2. Danh mục 16 bảng và quan hệ

Ký hiệu: PK là khóa chính, FK là khóa ngoại, UQ là duy nhất. DDL là danh sách cột, kiểu dữ liệu,
NULL và ràng buộc đầy đủ; bảng dưới giải thích ý nghĩa nghiệp vụ.

| Bảng | Khóa và dữ liệu chính | Quan hệ / trách nhiệm |
| --- | --- | --- |
| `app_users` | PK `id`; UQ `auth_issuer, auth_subject`; tên hiển thị, `disabled_at` | Một người có thể vừa nhặt vừa tìm; không tách thành hai loại tài khoản |
| `reception_points` | PK `id`; tên, địa chỉ công khai, chỉ dẫn, `active` | Điểm được hệ thống quản lý; nơi ngoài hệ thống không tạo bản ghi điểm giả |
| `point_staff` | PK/FK `point_id, user_id`; quyền nhận/trả, mốc phân công/thu hồi | Người dùng và điểm quan hệ N–N; mỗi quyền chỉ có hiệu lực tại điểm đó |
| `items` | PK `id`; FK người đăng/người giữ/điểm giữ; mô tả công khai, nơi/thời gian nhặt, trạng thái, các phiên bản | Trung tâm nghiệp vụ, đúng một nhánh nơi giữ tại một thời điểm |
| `stored_objects` | PK `id`; UQ `bucket, object_key`; loại, trạng thái, SHA-256, MIME thực, kích thước, hạn dọn | Theo dõi mọi đối tượng R2 kể cả tải dở, kết quả AI thua tranh chấp và ảnh đã thay thế |
| `item_images` | PK `id`; FK `item_id`, `original_object_id`, `sanitized_object_id`, người duyệt; vị trí, phiên bản, kết quả xử lý | Một món có nhiều ảnh; mỗi ảnh tham chiếu tối đa một bản gốc và một bản xử lý hiện được chọn |
| `verification_questions` | PK `item_id, slot`; `slot` từ 1 đến 3; nội dung câu hỏi hiện tại | Không có hàng nào tương ứng 0 câu hỏi; không cần câu hỏi giả |
| `claims` | PK `id`; FK món/người yêu cầu/người duyệt; phiên bản nơi giữ lúc gửi, trạng thái/quyết định | Người duyệt là bản chụp người giữ tại lúc tạo yêu cầu, không tự đổi theo nơi giữ sau này |
| `claim_answers` | PK `claim_id, slot`; nội dung câu hỏi chụp lúc gửi, câu trả lời | Tối đa 3 hàng; không FK tới câu hỏi hiện tại để chỉnh câu hỏi không làm biến đổi bằng chứng đã gửi |
| `conversations` | PK/FK `claim_id`; FK có điều kiện trạng thái `approved` | Một yêu cầu có 0 hoặc 1 hội thoại; hai bên lấy từ claimant/reviewer bất biến của yêu cầu |
| `messages` | PK `id`; FK hội thoại/người gửi; mã gửi lại, thứ tự, nội dung, mốc lưu | UQ `conversation_id, sender_user_id, client_message_id`; hỗ trợ tải lại lịch sử |
| `intake_requests` | PK `id`; FK món/người gửi/điểm đích/người quyết định; phiên bản nơi giữ nguồn | `pending` là chờ nhận thực tế; `received` chỉ khi nhân viên xác nhận đã cầm món đồ |
| `custody_events` | PK `id`; FK món/người thao tác/yêu cầu tiếp nhận/yêu cầu nhận/người nhận nếu có; bản chụp trước/sau | Lịch sử đăng ký nơi giữ, nhận thực tế và trao trả; tối đa một sự kiện `returned` cho mỗi món |
| `ai_jobs` | PK `id`; FK món/ảnh; loại việc, nguồn/phiên bản/hash, mô hình/profile, retry, lease | Hàng đợi bền vững cho phát hiện/làm mờ và tạo vector; không phải hàng đợi trong RAM |
| `item_embeddings` | PK `id`; FK món/ảnh; modality, nguồn/phiên bản/hash, mô hình/profile, vector | Vector văn bản và ảnh được phân biệt; chỉ lấy phiên bản nguồn còn hiện hành |
| `idempotency_keys` | PK `actor_user_id, idempotency_key`; thao tác, hash request, tài nguyên kết quả | Chống lặp tác động khi client thử lại các thao tác nghiệp vụ; không lưu bản sao câu trả lời/chat |

`idempotency_keys.resource_id` là tham chiếu đa loại có chủ đích, không phải FK. .NET kiểm tra
`resource_type`, tài nguyên tồn tại, quyền truy cập và lưu kết quả cùng giao dịch nghiệp vụ.
Các FK ghép `(image_id, item_id)`, `(claim_id, item_id)`, `(intake_request_id, item_id)` ngăn
liên kết một ảnh/yêu cầu thuộc món khác.

## 3. Nơi giữ, thời gian và phiên bản

### Ba nhánh nơi giữ

`items.custody_kind` quyết định bộ cột được phép có giá trị:

| Loại | Bắt buộc | Phải NULL |
| --- | --- | --- |
| `person` | `holder_user_id` | `holder_point_id` và các trường `external_*` |
| `point` | `holder_point_id` | `holder_user_id` và các trường `external_*` |
| `external` | `external_name`, `external_public_address` | Hai FK người/điểm; `external_instructions` tùy chọn |

`CHECK` kiểm tra cả trường bắt buộc khác NULL lẫn các trường loại trừ. Không lưu địa chỉ nhà
riêng trong nơi nhặt, bản chụp lịch sử hoặc thông tin nơi giữ công khai. Trao trả hoàn tất đặt
`lifecycle = 'returned'`; giữ bộ cột nơi giữ như **nơi giữ cuối cùng trước khi trả**, không có nghĩa
nơi đó vẫn đang giữ món đồ. Không hiển thị món đã trả trong danh sách có thể nhận. Người nhận
được ghi ở sự kiện trả, không bị biến thành người giữ mới của một món đang có thể nhận.

`custody_events.from_custody/to_custody` là JSON chụp loại nơi giữ, ID, tên điểm/nơi và địa chỉ
công khai tại thời điểm thao tác. Bản chụp tránh mất lịch sử khi điểm đổi tên. JSON không thay
FK của nơi giữ hiện tại; .NET phải kiểm tra cấu trúc và đối chiếu với hàng `items` bị khóa.

### Thời điểm nhặt

- `unknown`: không biết ngày/giờ; các cột ngày và khoảng thời gian NULL.
- `date`: `found_on` là ngày địa phương; không tạo thời điểm chính xác thay thế.
- `exact`: `found_from` là thời điểm đã biết, `found_until` NULL.
- `range`: `found_from <= found_until`; giữ nguyên khoảng ước lượng, kể cả qua nửa đêm.

`found_timezone` giữ ngữ cảnh ngày/giờ nhập; .NET kiểm tra tên múi giờ IANA và không cho ngày
nhặt tương lai theo chính sách đã chốt. Đặc tả đang **đề xuất** bắt buộc ngày; schema giữ khả năng
biểu diễn `unknown` trung thực. Nếu chốt bắt buộc ngày khi đăng, API từ chối `unknown` ở thao tác
đó, không tự điền một ngày giả. Các bộ lọc phải xử lý độ chính xác và thông báo khi nới điều kiện.

### Ba phiên bản riêng

| Trường | Tăng khi nào | Dùng để |
| --- | --- | --- |
| `items.row_version` | Mọi cập nhật món đồ | Phát hiện biểu mẫu cũ / cập nhật đồng thời bằng điều kiện phiên bản |
| `items.content_version` | Mô tả công khai dùng tạo vector thay đổi | Vô hiệu hóa vector văn bản và tác vụ nguồn cũ |
| `items.custody_version` | Đăng ký/chuyển nơi giữ/trao trả thực tế | Ngăn duyệt/tiếp nhận theo nơi giữ cũ, kể cả khi nơi giữ đổi rồi quay về cùng người |
| `item_images.content_version` | Thay nguồn, yêu cầu xử lý lại hoặc sửa vùng che ảnh | Vô hiệu hóa kết quả xử lý/vector ảnh và phê duyệt cho phiên bản cũ |

.NET tăng phiên bản; không có trigger tự tăng trong DDL. Sửa câu hỏi và chụp bộ câu hỏi khi gửi
yêu cầu đều khóa hàng món đồ để tránh chụp nửa bộ câu hỏi cũ, nửa bộ mới.

## 4. Lưu ảnh R2, Qwen Vision và OpenCV

### Hai lớp dữ liệu

`stored_objects` mô tả một đối tượng bất biến: bucket, khóa do máy chủ tạo, loại `original` hoặc
`sanitized`, SHA-256 tính trên nội dung, MIME đã giải mã, dung lượng và kích thước. Không lưu
URL có chữ ký vào DB vì URL hết hạn; không dùng tên tệp gốc làm khóa truy cập.
`item_images` mô tả một ảnh nghiệp vụ, vị trí hiển thị, các đối tượng được chọn và phê duyệt.

Ảnh gốc và bản xử lý đều nằm trong bucket riêng tư, không bật `r2.dev`/truy cập công khai.
Backend chỉ cấp dữ liệu/URL đọc ngắn hạn cho bản xử lý đủ điều kiện hiển thị. Ảnh gốc chỉ được
đọc trong luồng xử lý hoặc kiểm tra có quyền. R2 dùng khóa truy cập phía máy chủ với phạm vi
bucket tối thiểu; trình duyệt, FastAPI và log không nhận khóa tài khoản R2.

### Luồng ghi không đòi hỏi giao dịch phân tán

1. .NET tạo `stored_objects` ở trạng thái `reserved`, đặt `expires_at` và khóa ngẫu nhiên trước
   khi ghi R2. Kiểm tra quyền, giới hạn dung lượng và số pixel, định dạng thực tế; tính SHA-256
   trên byte nhận được. Chỉ khi upload và kiểm tra thành công mới đặt `validated`.
2. Giao dịch tạo món đồ khóa và gắn đối tượng gốc hợp lệ vào `item_images`, bỏ hạn dọn đối tượng
   đang dùng, tạo `ai_jobs.redact_image`, rồi commit. Thử lại tạo món dùng cùng khóa idempotency.
3. Worker lấy nội dung gốc có quyền qua .NET và gọi FastAPI. Qwen/Qwen3-VL-4B-Instruct đề xuất
   vùng nhạy cảm; .NET/FastAPI kiểm tra schema, loại vùng, tọa độ trong giới hạn. OpenCV thực
   hiện làm mờ vùng đã xác thực và xuất một ảnh mới; loại bỏ metadata nhận diện như EXIF.
4. Trước mỗi lần ghi kết quả R2, dự trữ một `stored_objects` mới loại `sanitized`. Không ghi đè
   đối tượng đã có: mỗi lần thử có khóa riêng. Lưu kết quả, kiểm tra ảnh xuất và hash. Chỉ kết
   quả thắng kiểm tra lease/phiên bản mới được gắn vào `item_images` ở `needs_review`.
5. `sensitive_regions` chỉ lưu loại vùng và tọa độ chuẩn hóa, không lưu toàn bộ OCR/số giấy tờ.
   `redaction_model_id`, revision bất biến và `redaction_profile` ghi nhận prompt/schema,
   cấu hình OpenCV và quy tắc xử lý. Nội dung này là riêng tư, không đưa vào vector công khai.
6. Người được cấp quyền xem bản xử lý và xác nhận cho **đúng phiên bản**; đặt `review_state =
   'approved'`, `reviewed_by`, `reviewed_at`, `processing_state = 'ready'`. AI không tự phê
   duyệt. Khi vùng bị che chưa đủ, chỉnh vùng và tạo bản xử lý mới, reset phê duyệt.
7. Sau phê duyệt, tạo tác vụ vector ảnh từ **bản đã che**. Không dùng bản gốc để tạo chỉ mục tìm
   kiếm công khai. Nếu AI lỗi, giữ bài đăng và trạng thái lỗi; ảnh chưa an toàn không được
   công khai, giao diện dùng thông báo/ảnh giữ chỗ và danh sách/lọc cơ bản.

Ai có quyền duyệt bản che ảnh, có được duyệt ảnh do mình tải lên hay không và bộ vùng nhạy cảm
bắt buộc là chính sách cần chốt. DDL lưu provenance để thực thi, không tự tạo vai trò quản trị
hay trao quyền duyệt cho mọi người đăng. Khi chưa có người duyệt có quyền, ảnh giữ `needs_review`.
Làm mờ có thể bỏ sót hoặc chưa đủ che; bắt buộc kiểm tra ảnh xuất thực tế, không suy ra an toàn
chỉ từ việc Qwen trả JSON hợp lệ hoặc OpenCV chạy thành công.

### Điều kiện đọc và dọn ảnh

API chỉ lấy `sanitized_object_id` khi đồng thời: bài đăng được phép xem, ảnh chưa retired,
`processing_state = 'ready'`, review approved, đối tượng đúng loại `sanitized` và `validated`.
Không trả khóa/URL gốc trong DTO công khai. Kiểm tra lại điều kiện ở endpoint trả ảnh.
`CHECK` trong SQL chỉ kiểm tra hình dạng hàng; kiểu đối tượng, trạng thái đối tượng, người duyệt
và phiên bản phê duyệt cần .NET kiểm tra trong giao dịch có khóa.

Khi thay ảnh, giữ hàng đối tượng cũ và đặt hạn dọn theo chính sách; không làm mất khóa R2.
Worker dọn lấy hàng đối tượng, khóa, kiểm tra không còn ảnh tham chiếu và đã hết hạn, chuyển
`delete_pending`, commit, rồi mới xóa R2 bên ngoài giao dịch. API không được gắn đối tượng ở
`delete_pending/deleted` hoặc đã hết hạn. Xóa thành công mới đặt `deleted_at`; lỗi giữ khóa,
lưu `cleanup_attempts`, `cleanup_next_at`, mã lỗi an toàn để retry có giới hạn và báo vận hành.
Lệnh xóa R2 lặp lại phải xử lý như thành công khi đối tượng đã không còn.

Điều kiện không còn tham chiếu được kiểm tra cùng khóa đối tượng, và mọi thao tác gắn ảnh cũng
lấy khóa đó, tránh xóa song song với gắn ảnh. Cả upload bỏ dở và kết quả worker lỗi thời đều
được dọn; đối tượng đang được tham chiếu không bị xóa chỉ vì cấu hình lifecycle chung.
Nếu gỡ ảnh, đánh dấu `retired_at`, xóa vector liên quan và ngừng cấp URL mới ngay; URL đã cấp
có thể còn đọc được đến lúc hết hạn. Không hứa thu hồi tức thì bằng việc chỉ đổi cột DB.

Để dọn ảnh đã gỡ sau thời hạn lưu, .NET khóa món/ảnh và các đối tượng liên quan, vô hiệu hóa
lease của job ảnh, xóa `item_embeddings` và `ai_jobs` của ảnh rồi xóa hàng `item_images` đã
retired trong cùng giao dịch. Lưu hạn dọn ở các hàng `stored_objects` trước khi commit; không
xóa những hàng này khi còn phải xóa R2. Bước này giải phóng cả FK gốc bắt buộc và FK bản sạch
để worker dọn có thể xử lý. Kết quả từ worker cũ phải bị bỏ vì ảnh/job hoặc lease không còn;
object đầu ra đã dự trữ vẫn được theo dõi để dọn. Chỉ purge metadata ảnh khi chính sách lưu
giữ cho phép; retired đơn thuần chưa có nghĩa object đã được xóa.

## 5. Yêu cầu nhận đồ, câu trả lời và hội thoại

### Yêu cầu và bằng chứng

.NET chỉ tạo claim khi món còn có thể nhận, do cá nhân giữ và người gọi được phép yêu cầu.
Trong giao dịch khóa món, ghi claimant từ phiên máy chủ; ghi reviewer từ người giữ thực tế và
`source_custody_version`; chụp toàn bộ 0–3 câu hỏi vào `claim_answers`, kể cả câu chưa được trả
lời. Không có câu hỏi thì không tạo dòng answer, claim vẫn hợp lệ. Quy tắc bắt buộc trả lời
câu đã tạo là quyết định sản phẩm còn mở; SQL cho phép `answer_text` NULL.

`claimant_user_id`, `reviewer_user_id`, phiên bản nơi giữ và câu trả lời chụp lúc gửi là bất biến
đối với các endpoint MVP. Chỉ claimant và reviewer còn có quyền tại thời điểm truy cập được
đọc bằng chứng; không tự cấp cho người giữ mới hoặc toàn bộ nhân viên của điểm mới. Khi duyệt,
kiểm tra reviewer vẫn là người giữ, món active và phiên bản nơi giữ còn khớp. Yêu cầu lỗi thời
không được duyệt; không tự hủy hay tự chuyển người duyệt khi chưa có chính sách tương ứng.

### Hội thoại đúng hai bên

`conversations.claim_id` vừa là PK vừa tham chiếu claim; không có bảng thành viên mở rộng.
Hai người được phép tham gia lấy từ claimant/reviewer bất biến. FK ghép với `approval_status =
'approved'` khiến DB từ chối tạo hội thoại cho claim pending/rejected; mỗi claim tối đa một chat.
Không tạo chat mặc định cho đồ tại điểm hoặc nơi ngoài hệ thống.

Mọi lần đọc lịch sử, kết nối SignalR, tham gia nhóm, gửi tin và kết nối lại đều kiểm tra danh tính,
claim approved và chính sách vòng đời hiện tại tại .NET. Không tin sender hoặc group ID do
client tự khai. DB có FK sender tồn tại nhưng không tự kiểm tra sender là một trong hai bên.

Lưu tin theo thứ tự sau:

1. Khóa hàng `conversations` bằng `SELECT ... FOR UPDATE` **trước khi INSERT tin nhắn**; kiểm
   tra lại quyền và trạng thái. Tất cả đường ghi tin phải dùng cùng thứ tự khóa này.
2. Tra khóa `(conversation_id, sender_user_id, client_message_id)`. Nếu đã có cùng nội dung,
   trả lại tin cũ; cùng mã nhưng khác nội dung trả lỗi xung đột.
3. INSERT tin và commit, sau đó mới xác nhận/phát SignalR. Client loại sự kiện trùng bằng ID.
4. Đọc bù dùng `message_sequence > last_seen ORDER BY message_sequence`, phân trang có giới hạn.

Khóa theo hội thoại ở bước 1 là bắt buộc: sequence IDENTITY được cấp trước commit; nếu chỉ
INSERT song song, tin số 102 có thể commit trước 101 khiến con trỏ 102 bỏ lỡ tin 101. Khóa này
bảo đảm thứ tự commit của các tin trong cùng hội thoại. Khoảng trống do rollback là hợp lệ.
Không giữ khóa trong lúc phát SignalR; sự kiện có thể mất nhưng dữ liệu đã commit có thể đọc lại.

Thu hồi phê duyệt/rút yêu cầu chưa được mô hình hóa thành trạng thái triển khai. FK sẽ chặn
đổi claim approved đã có chat sang rejected; việc thêm thu hồi cần quyết định vòng đời chat và
migration tương ứng. Quyền đọc/gửi sau đổi nơi giữ hoặc trả đồ cũng chưa chốt; phương án đề xuất
là dừng gửi khi điều kiện hiện hành không còn đúng và chỉ giữ lịch sử cho các bên theo chính
sách lưu giữ được duyệt. Đây chưa phải hành vi sản phẩm được thông qua.

## 6. Giao dịch tiếp nhận, trao trả và gửi lại

Mọi thay đổi nghiệp vụ dùng giao dịch ngắn với thứ tự khóa nhất quán: món đồ, yêu cầu liên quan,
đối tượng hoặc hội thoại nếu có. Không gọi R2, AI hay SignalR trong giao dịch đang giữ khóa.

| Thao tác | Các bước nguyên tử trong PostgreSQL |
| --- | --- |
| Đăng món | Lưu item + nơi giữ thực tế; gắn ảnh đã kiểm tra; ghi sự kiện `registered` phiên bản 1; tạo tác vụ; lưu khóa idempotency |
| Gửi tiếp nhận | Tạo request pending với `source_custody_version`; không sửa nơi giữ |
| Từ chối tiếp nhận | Kiểm tra nhân viên điểm đích; cập nhật request/reason; không sửa nơi giữ |
| Xác nhận đã nhận | Khóa item/request; kiểm tra active, pending, phiên bản nguồn, điểm active và `can_receive` chưa thu hồi; cập nhật request received + nơi giữ point + phiên bản; ghi sự kiện received |
| Duyệt claim | Khóa item/claim; kiểm tra người giữ hiện tại và phiên bản nguồn; cập nhật approved và tạo chat trong cùng giao dịch |
| Trao trả cá nhân | Kiểm tra người giữ thực tế, claim approved đúng món/phiên bản và người nhận; ghi một event returned + lifecycle returned + tăng phiên bản |
| Trao trả tại điểm | Nhân viên hiện được phân công, `can_return`, đã xác minh trực tiếp; event returned + lifecycle returned + tăng phiên bản; không bắt buộc có claim/chat |

`custody_events` là nhật ký chỉ thêm, không phải bảng được cập nhật/xóa qua API thông thường.
`occurred_at` là thời điểm bàn giao thực tế, `recorded_at` là lúc ghi nhận. Hai mốc có thể khác;
API xác thực mốc thực tế theo quy trình, không tin thời gian tùy ý từ client. Với nhận tại điểm,
`recipient_user_id` có thể NULL nếu người nhận trực tiếp không có tài khoản; `verification_note`
là ghi chú tối thiểu riêng tư, không mặc định thu ảnh giấy tờ/số định danh. Bộ bằng chứng cần lưu
phải được chốt trước dữ liệu thật.

Chỉ mục duy nhất có điều kiện trên `custody_events(item_id) WHERE event_kind = 'returned'`
chặn lần trả thứ hai ngay cả khi ứng dụng sai. Khóa hàng item và kiểm tra lifecycle ngăn đồng
thời nhận vào điểm và trao trả. SQL không tự tạo sự kiện hoặc đồng bộ lifecycle: .NET phải thực
hiện tất cả ghi trong một giao dịch, rollback toàn bộ nếu một phần thất bại.

`idempotency_keys` có hiệu lực cho tạo/sửa món, xử lý ảnh, gửi/xét claim, gửi/xét intake và trả đồ:

- Máy chủ tính hash canonical gồm loại thao tác, tài nguyên và payload; lấy actor từ phiên.
- Chèn khóa cùng giao dịch nghiệp vụ, với ID kết quả được biết trước. Khóa trùng chờ giao dịch
  trước kết thúc; cùng hash/operation trả kết quả cũ, khác payload trả xung đột.
- Lỗi/rollback không để lại kết quả thành công giả. Khi đọc kết quả cũ vẫn kiểm tra quyền hiện tại.
- Chưa tự hết hạn khóa nghiệp vụ khi chưa chốt chính sách retry/retention; xóa khóa quá sớm có
  thể cho phép tác động lặp. Tin nhắn dùng khóa duy nhất riêng trong bảng `messages`.

Schema không đặt UNIQUE một claim approved trên mỗi món và không tự hủy các request pending
khác khi trả/chuyển nơi giữ. Duyệt nhiều người, rút/thu hồi, stale request hiển thị ra sao và quyền
cập nhật trả ở nơi ngoài hệ thống là quyết định sản phẩm. Trước khi triển khai endpoint chịu
ảnh hưởng, chốt chính sách và kiểm tra trong transaction; không suy diễn từ việc schema lưu
được nhiều dòng. Mở chỉ đường không thay đổi DB và không ghi nhận trao trả.

## 7. Tác vụ AI và vector không lỗi thời

Cấu hình cơ sở: Qwen/Qwen3-VL-Embedding-2B cho cả văn bản và ảnh, đầu ra 2048 chiều;
Qwen/Qwen3-VL-4B-Instruct đề xuất vùng ảnh, OpenCV tạo bản che. Số chiều được xác nhận ở
[model card Qwen3-VL-Embedding-2B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B).
Trước triển khai phải cố định revision/commit thực tế của trọng số, tokenizer/processor và
thư viện; không ghi `main`/`latest` như revision đã kiểm chứng.

`model_id + model_revision + processing_profile + dimensions` xác định cấu hình vector.
Profile là mã/hash cấu hình bất biến gồm chuẩn hóa văn bản, prompt/query instruction, tokenizer,
resize ảnh và quy trình chuẩn bị đầu vào. `source_sha256` là hash payload công khai đã chuẩn hóa
hoặc byte **ảnh đã che được duyệt**, không phải hash câu trả lời xác minh. Hàng đợi redaction
sử dụng hash gốc riêng tư; nội dung đó không đi vào bảng vector tìm kiếm.

1. Tạo job cùng giao dịch thay nội dung. Job văn bản chụp `items.content_version`; job ảnh chụp
   `item_images.content_version`. Thay mô hình/profile tạo job mới với identity mới.
2. Worker dùng `FOR UPDATE SKIP LOCKED` nhận việc đến hạn, tăng attempts, cấp lease token mới
   và `lease_until`, rồi commit trước khi gọi dịch vụ ngoài. `SKIP LOCKED` phù hợp hàng đợi như
   [tài liệu PostgreSQL](https://www.postgresql.org/docs/current/sql-select.html) mô tả.
3. Khi lưu, khóa item/ảnh/job; kiểm tra token vẫn sở hữu lease và lease chưa hết hạn. Nếu job
   đã bị xóa, token khác hoặc lease đã hết hạn, bỏ kết quả và không sửa job của worker mới.
   Chỉ worker còn giữ lease hợp lệ mới được kiểm tra nguồn hiện tại/version/hash và
   model/profile. `redact_image` chỉ cần nguồn gốc hiện hành, chưa retired và hợp lệ để lưu
   bản xử lý ở `needs_review`; riêng `embed_image` phải dùng bản sạch đã được duyệt đúng
   phiên bản. Nếu nguồn/cấu hình không còn khớp, worker đang giữ lease bỏ kết quả và đặt
   obsolete bằng cập nhật có điều kiện trên token; không ghi đè trạng thái của lease khác.
4. Kiểm tra vector đúng 2048 chiều, từng giá trị hữu hạn, vector khác không để tính cosine,
   cấu hình tương thích. Upsert vector và job succeeded trong cùng transaction.
5. Lỗi tạm thời chuyển retry, tính `next_attempt_at` với backoff; lỗi vĩnh viễn/hết giới hạn
   chuyển failed và lưu mã lỗi an toàn. Worker khởi động lại nhận cả pending/retry lẫn running
   đã hết lease; cấp token mới để kết quả worker cũ không ghi đè.

Unique index của job ngăn tạo hai việc cùng mục tiêu/phiên bản/mô hình/profile. Thử lại có kiểm
soát tái dùng hàng job và ghi attempts; không tạo vòng lặp vô hạn bằng các job mới. Giá trị
`max_attempts`, timeout và lịch backoff phải được cấu hình khi triển khai, DDL không tự đặt SLA.

Truy vấn tìm kiếm lọc bài published/active và nối nguồn hiện tại trước khi tính khoảng cách;
không chỉ lọc hàng embedding. Nhánh văn bản dùng modality text; nhánh ảnh dùng image từ ảnh ready,
review approved, chưa retired, đối tượng sanitized validated. Luôn khớp model/revision/profile
và source_version/hash. Các ảnh nhiều góc của một món được gom thành một kết quả theo điểm tốt
nhất trong nhánh tìm ảnh; cách xếp hạng cần được đo trên tập đánh giá.

MVP dùng toán tử cosine `<=>` và tìm chính xác, không tạo HNSW/IVFFlat trong DDL. `vector(2048)`
vượt giới hạn 2000 chiều của chỉ mục ANN kiểu vector được mô tả trong
[tài liệu pgvector](https://github.com/pgvector/pgvector#hnsw). Khi cần ANN phải đo và chọn rõ
halfvec hoặc đầu ra giảm chiều, rồi migration/reindex; không âm thầm cắt 48 chiều. Hai đầu vào
có thể dùng chung họ mô hình nhưng MVP vẫn chọn tìm văn bản hoặc ảnh, chưa tự trộn điểm.

## 8. Bất biến do DB và dịch vụ thực thi

[PostgreSQL không dùng CHECK để kiểm tra dữ liệu bảng khác](https://www.postgresql.org/docs/current/ddl-constraints.html).
Vì vậy DDL không được trình bày như hệ thống phân quyền hoặc luồng nghiệp vụ đã hoàn chỉnh.

| Yêu cầu | DB bảo đảm | .NET / kiểm thử tích hợp phải bảo đảm |
| --- | --- | --- |
| BR01 tìm không ảnh | Embedding text có `image_id` NULL hợp lệ | Không bắt ảnh truy vấn; không embedding bằng chứng riêng tư |
| BR02 ba nhánh giữ | CHECK exactly-one + FK người/điểm | Phản ánh người/nơi thực tế, kiểm tra quyền ghi; DTO đúng nhánh |
| BR03 từ 0 đến 3 câu | Slot 1..3 + PK theo món/claim | Chụp toàn bộ bộ câu hỏi nhất quán; không chặn claim không câu hỏi |
| BR04 approved mới chat | FK claim/status approved, chat duy nhất | Xác thực từng read/send/connect, đúng hai bên; snapshot bất biến |
| BR05 chờ không chuyển giữ | Trạng thái intake tách khỏi items | Không update nơi giữ khi pending/rejected; stale check lúc nhận |
| BR06 điểm xác minh trả | FK sự kiện/actor và một event returned | Phân công điểm còn hiệu lực, xác minh trực tiếp, ghi nguyên tử |
| Không trả hai lần | Partial unique index event returned/item | Lock item; lifecycle + event + request + idempotency chung transaction |
| Ảnh an toàn | FK đối tượng, shape trạng thái/provenance | Kiểu/state tệp, byte thực, quyền duyệt, version, điều kiện public và cleanup |
| Chat bền vững | Nội dung + unique mã gửi lại | Serialize theo chat trước cấp sequence; commit rồi publish; quyền reconnect |
| Không vector cũ | FK nguồn, 2048 chiều, identity duy nhất | So version/hash/model/profile/lease, vector hữu hạn khác không; lọc lại khi tìm |
| Phân quyền | FK xác nhận các ID tồn tại | Không đọc trực tiếp DB từ client; không dùng ID, FK hoặc ẩn nút thay quyền |

Không áp dụng RLS trong DDL nền. Vai trò DB ứng dụng chỉ cấp cho .NET ở mạng nội bộ; tài khoản
migration riêng, quyền tối thiểu, không cấp `DROP` hoặc quản lý role cho tài khoản chạy ứng dụng.
Các endpoint không cho sửa trực tiếp FK, version, trạng thái review hay actor. Phiên bị vô hiệu
hóa và quyền nhân viên phải được kiểm tra lại phía máy chủ, không chỉ đọc claim cũ từ token.

## 9. Chỉ mục, xóa và vận hành

Các chỉ mục B-tree hỗ trợ danh sách public, bài của người đăng/người giữ, hàng đợi claim/intake,
nhân viên theo tài khoản, lịch sử chat/sự kiện, việc đến hạn/lease hết hạn và scope vector.
Không tạo index cho mọi cột. Địa điểm tìm kiếm bắt đầu bằng chuỗi khu vực đã chuẩn hóa phía API;
chưa thêm PostGIS hoặc taxonomy địa giới khi sản phẩm chưa cần. Đo truy vấn thực tế trước khi
thêm chỉ mục hay bộ lọc địa lý khác.

Tất cả FK nghiệp vụ `ON DELETE RESTRICT` tránh xóa dây chuyền chat/bằng chứng/lịch sử. Vô hiệu
hóa tài khoản bằng `disabled_at`, điểm bằng `active = false`, thu hồi phân công bằng `revoked_at`,
gỡ bài bằng publication hidden, gỡ ảnh bằng retired. Đây không thay thế quyền được xóa dữ liệu:
trước dữ liệu thật phải chốt thời hạn lưu và quy trình xóa/ẩn danh đồng bộ DB, vector, R2 và backup.
Snapshot câu hỏi/bằng chứng/chat cần lịch xóa riêng; không giữ vô thời hạn chỉ vì đã dùng RESTRICT.

Backup PostgreSQL giữ metadata và nghiệp vụ; nó không tự sao lưu nội dung R2. Kế hoạch khôi phục
phải kiểm chứng cả tham chiếu khóa, đối tượng thực tế và cấu hình bí mật; phục hồi DB cũ có thể
tham chiếu đối tượng đã bị xóa. Không ghi nội dung ảnh, token, tin nhắn hay câu trả lời vào log.

Ảnh truy vấn tìm kiếm là dữ liệu tạm. Cơ sở không tạo bảng lịch sử tìm kiếm; .NET xóa tệp tạm
sau xử lý và áp dụng TTL cho upload bỏ dở. Muốn lưu truy vấn hoặc analytics theo người phải có
mục đích và thời hạn lưu riêng, không tận dụng bảng ảnh bài đăng để lưu ngầm.

## 10. DDL, kiểm chứng và việc cần chốt

`database-schema.sql` là DDL tham chiếu **cho database trống** có extension pgvector khả dụng,
không phải migration sản xuất. Chạy một lần bằng `psql -v ON_ERROR_STOP=1 -f docs/database-schema.sql`
trên database kiểm thử; không chạy lên database đang có dữ liệu. DDL không seed người dùng,
điểm hay phân quyền, không cấu hình R2, không triển khai API/worker và không chứng minh chất lượng AI.
Khi triển khai EF Core, tạo migration tương ứng và kiểm tra diff; migration thay đổi kiểu vector
hoặc auth cần kế hoạch chuyển dữ liệu riêng.

Bộ tự kiểm cần chạy trên database dùng một lần: thêm dữ liệu hợp lệ; xác nhận lỗi với hai nơi
cùng giữ, câu hỏi slot 4/trùng slot, hội thoại cho pending/rejected, ảnh ready chưa review,
vector sai chiều, liên kết ảnh/yêu cầu sai món, hai lần return và gửi lại tin cùng mã. Tình huống
0 câu hỏi/claim approved/chat hợp lệ phải thành công. Kiểm thử ứng dụng còn phải bao phủ quyền
truy cập, hai thao tác bàn giao đồng thời, thứ tự commit tin nhắn, lease bị giành lại, kết quả AI
cũ, R2 mất kết nối và race giữa dọn/gắn tệp. Kiểm tra SQL không thay thế các kiểm thử đó.

Đã thử DDL và `database-check.sql` trên PostgreSQL 17 với pgvector trong container tạm:
tạo đủ 16 bảng, chấp nhận claim không câu hỏi/chat đã duyệt/vector 2048 chiều và từ chối
15 trường hợp dữ liệu vi phạm. Chạy lại bằng `psql -v ON_ERROR_STOP=1 -f docs/database-check.sql`
sau DDL; script rollback toàn bộ dữ liệu thử. Đây là kiểm tra cấu trúc DB, chưa phải kiểm thử
phân quyền, giao dịch nghiệp vụ của .NET hoặc kết nối R2 thực tế.

Các quyết định chưa chốt, không được âm thầm coi là đã có:

1. Nhà cung cấp OIDC, quyền đọc khi chưa đăng nhập, cấp/thu hồi nhân viên và thời hạn phiên.
2. Ai tạo câu hỏi, có bắt trả lời, bằng chứng trực tiếp và ai được duyệt bản che ảnh.
3. Nhiều claim cùng approved, rút/thu hồi, request lỗi thời và quyền chat sau chuyển nơi/trả đồ.
4. Đồng ý trước khi nhận thực tế và quyền xác nhận trao trả ở nơi ngoài hệ thống.
5. Giới hạn upload/pixel, quy tắc vùng cần che, thời hạn lưu/xóa, sửa/gỡ và tranh chấp.
6. Revision mô hình/profile cụ thể, chất lượng tiếng Việt/ảnh đã che, phần cứng, tốc độ và chi phí.

Thiết kế hiện tại cho phép hoàn thiện những quyết định này bằng chính sách và migration có
chủ đích; chưa tuyên bố các chính sách đề xuất đã được nhóm sản phẩm phê duyệt.
