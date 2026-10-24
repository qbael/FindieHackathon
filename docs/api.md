# Findie API

ASP.NET Core .NET 10, Entity Framework Core/Npgsql và ASP.NET Core Identity.
Đã có model nghiệp vụ, migration khởi tạo, xác thực và hai luồng mẫu theo kiến trúc
`Controller → Service → Repository → FindieDbContext → PostgreSQL`.
Đăng tin, xét duyệt claim, bàn giao, chat, upload R2 và worker AI chưa triển khai.

## Cấu trúc và khởi chạy

```text
apps/api/
  Models/          ApplicationUser : IdentityUser<Guid> và 15 model nghiệp vụ
  Data/            FindieDbContext : IdentityDbContext; cấu hình quan hệ/ràng buộc
    Migrations/    Migration khởi tạo và snapshot EF Core
  Contracts/       Request/response DTO, không trả entity Identity trực tiếp
  Repositories/    Truy cập EF Core; interface và implementation riêng
  Services/        Kiểm tra đầu vào và tạo DTO
  Controllers/     API hồ sơ và điểm tiếp nhận, bắt buộc xác thực
  Security/        Google OAuth và chặn truy cập của tài khoản DisabledAt
  tests/           Smoke và kiểm thử tích hợp PostgreSQL dùng một lần
```

Từ thư mục gốc, theo [hướng dẫn phát triển](development.md):

```sh
make setup
make db-up
make db-migrate
make api
```

`make db-migrate` dùng `scripts/db/migrate.py` để áp dụng EF migrations. Database bootstrap
cũ chỉ được chuyển đổi tự động khi toàn bộ 16 bảng đều rỗng; script từ chối nếu có dữ liệu.
Với dữ liệu cũ thực tế, cần migration chuyển đổi riêng; không xóa volume để chữa lỗi.
API không tự `Migrate`, `EnsureCreated`, tạo bảng hoặc xóa dữ liệu khi khởi động.
EF migrations là nguồn lược đồ runtime .NET; provisioning riêng tạo database tìm kiếm Python.

`ConnectionStrings__Database` và `Ai__ServiceToken` bắt buộc có giá trị.
`Ai__BaseUrl` mặc định `http://127.0.0.1:8000`; timeout mặc định 5 giây.
Các cấu hình `Storage__*` mới là tên cấu hình dự phòng, chưa kích hoạt R2.

## Xác thực và hồ sơ

**Tạm thời chỉ cho đăng nhập bằng Google.** ASP.NET Core Google OAuth xử lý chuyển hướng,
state/correlation và trao đổi mã ở máy chủ; Identity lưu tài khoản và external login.
`ApplicationUser` dùng khóa `Guid`, có tên hiển thị, ngày tạo và `DisabledAt`.
Role được hỗ trợ bởi Identity; cấp quyền nhân viên tại điểm chưa có API.

| Endpoint | Nội dung |
| --- | --- |
| `GET /api/auth/google?returnUrl=/` | Bắt đầu đăng nhập Google; chỉ nhận đường dẫn quay về nội bộ. Trả 503 nếu chưa cấu hình OAuth. |
| `GET /api/auth/google/signin` | Callback OAuth do middleware Google xử lý; đăng ký URI này tại Google Cloud. |
| `GET /api/auth/google/callback` | Hoàn tất liên kết tài khoản, cấp cookie rồi quay về ứng dụng. |
| `GET /api/users/me` | Hồ sơ chính chủ: `id`, `email`, `displayName`, `createdAt`. |
| `PUT /api/users/me` | `{ "displayName": "…" }`; bỏ khoảng trắng hai đầu, từ chối rỗng hoặc quá 120 ký tự. |
| `GET /api/reception-points` | Tối đa 100 điểm đang hoạt động, sắp theo tên và ID. |
| `GET /api/reception-points/{id}` | Chỉ trả điểm đang hoạt động; 404 nếu không có hoặc đã ngừng hoạt động. |
| `GET /api/auth/csrf` | Người dùng đã đăng nhập lấy `{ "token": "…" }` và cookie chống giả mạo. |
| `POST /api/auth/logout` | Gửi `X-CSRF-TOKEN`; kết thúc cookie, trả 204. |

Các API hồ sơ/điểm tiếp nhận dùng cookie phiên của ứng dụng, không nhận bearer token.
Mỗi lượt truy cập được bảo vệ đều kiểm tra tài khoản vẫn tồn tại và chưa bị vô hiệu hóa.
Không có API liệt kê người dùng, tự cấp role hoặc cấp quyền tại điểm.

Cookie `HttpOnly`, `SameSite=Lax`; ngoài Development luôn yêu cầu `Secure`/HTTPS.
HTTP loopback chỉ được phép trong Development. Mọi request thay đổi dữ liệu đã đăng nhập
cần token từ `/api/auth/csrf` trong header `X-CSRF-TOKEN`. React có nút Google, tên/email
hồ sơ và đăng xuất; giữ phiên bằng cookie, không lưu token trong localStorage.
`GET /api/users/me` trả 401 khi chưa đăng nhập là trạng thái bình thường.

Không ánh xạ đăng ký, email/password, refresh, quên mật khẩu, email confirmation hoặc 2FA.
Trước triển khai cần HTTPS và lưu Data Protection keys bền vững; khi chạy nhiều instance
cần dùng chung key ring. Cấu hình Google và URI local nằm trong [hướng dẫn phát triển](development.md#đăng-nhập-google).

## Model và database

Các model gồm tài khoản, điểm tiếp nhận, nhân viên điểm, món đồ, metadata object,
ảnh đã xử lý, câu hỏi xác minh, claim/câu trả lời, hội thoại/tin nhắn, yêu cầu tiếp nhận,
lịch sử nơi giữ, job AI, khóa idempotency và outbox chỉ mục. Schema runtime có 22 bảng
(7 bảng Identity, bao gồm `app_users`, và 15 bảng nghiệp vụ), ngoài bảng lịch sử migration.

EF giữ khóa ngoại hạn chế xóa, câu hỏi tối đa ba slot, một nơi giữ, các phiên bản dương,
hội thoại chỉ gắn claim đã duyệt, khóa gửi lại tin nhắn và tối đa một lần trao trả.
`Item.RowVersion` là concurrency token; dịch vụ cập nhật món sau này phải tăng phiên bản.
`Claim.Status` tham gia alternate key để bảo đảm hội thoại thuộc claim approved; luồng
quyết định sau này cần cập nhật bằng `ExecuteUpdate` rồi nạp lại entity.
Các ràng buộc này chưa thay thế kiểm quyền/giao dịch trong nghiệp vụ chưa được xây dựng.

Ảnh chỉ có `ProcessedObjectId`; object kind chỉ là `processed`.
Không có tham chiếu ảnh gốc, raw bytes hoặc `ItemEmbedding` trong EF .NET.
`AiJob` là metadata cho embed text/image. `IndexOutbox` giữ snapshot/tombstone, phiên bản,
checksum, trạng thái retry và lease; chưa có dispatcher/worker RabbitMQ hoạt động.
`Item.DocumentVersion` là phiên bản tài liệu. Database `findie_search` có `search_documents`
(projection/watermark/tombstone), `search_sources` (embedding) và lịch sử schema riêng;
luồng lập chỉ mục và hybrid search chưa triển khai.
Xem [kiến trúc đích](system-architecture.md).

## Trạng thái và kiểm thử

| Endpoint | Ý nghĩa |
| --- | --- |
| `GET /health/live` | Tiến trình đang chạy, không kiểm phụ thuộc. |
| `GET /health/ready` | `SELECT 1` thành công; không xác nhận đã chạy migration. |
| `GET /api/system/status` | Trạng thái DB/AI; `authentication` chỉ true khi đã điền đủ cấu hình Google; `business: false`, `storage: false`. |

`stage` vẫn là `scaffold` vì nghiệp vụ sản phẩm chưa hoàn thiện.
HTTP tới FastAPI chỉ là health probe; lệnh/kết quả suy luận đích dùng RabbitMQ.
Readiness không buộc AI sẵn sàng. API local nghe `http://127.0.0.1:5080`, Vite proxy `/api`.

```sh
dotnet build apps/api --no-restore
python3 apps/api/tests/smoke.py
make api-integration
```

Smoke không cần DB. Integration cần Docker và image PostgreSQL theo script;
tự tạo container/database tạm, chạy migration, kiểm tra Google callback bằng provider giả lập,
cookie/CSRF, DTO/validation/quyền và ràng buộc SQL rồi dọn container. `make db-check` còn kiểm
schema/role tìm kiếm. Các bộ tích hợp không ghi database đang dùng của bạn; chưa chứng thực
đăng nhập qua Google thật khi thiếu OAuth credentials.
