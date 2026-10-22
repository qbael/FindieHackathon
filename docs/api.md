# Findie API

Khung ASP.NET Core .NET 10 LTS. Chỉ triển khai kiểm tra kết nối; chưa có đăng nhập,
nghiệp vụ, upload R2 hoặc gọi suy luận. DDL gốc nằm ở [database-schema.sql](database-schema.sql),
được Docker PostgreSQL khởi tạo; API không tự sửa lược đồ.

Từ thư mục gốc, nạp biến môi trường theo [hướng dẫn phát triển](development.md), khởi động PostgreSQL rồi chạy:

```sh
dotnet restore apps/api --locked-mode
dotnet run --project apps/api
```

Mặc định profile phát triển nghe `http://127.0.0.1:5080`.
`ConnectionStrings__Database` và `Ai__ServiceToken` bắt buộc có giá trị;
`Ai__BaseUrl` mặc định `http://127.0.0.1:8000`, `Ai__TimeoutSeconds` mặc định 5.
Token được gửi trong header `X-Service-Token` khi kiểm tra AI.
Các giá trị `Storage__Endpoint`, `Storage__Bucket`, `Storage__AccessKeyId`,
`Storage__SecretAccessKey` chỉ chuẩn bị tên cấu hình R2, chưa kích hoạt lưu trữ.
Giữ credential ở môi trường máy chủ, không đưa vào cấu hình React.

| Endpoint | Ý nghĩa |
| --- | --- |
| `GET /health/live` | Tiến trình đang chạy; 200, không kiểm tra phụ thuộc. |
| `GET /health/ready` | Thực thi `SELECT 1`; 200 khi PostgreSQL sẵn sàng, 503 khi lỗi. Không xác nhận DDL đã được nạp. |
| `GET /api/system/status` | JSON trạng thái DB và AI, luôn giữ các cờ nghiệp vụ/xác thực/lưu trữ là `false`. AI chỉ `ready` khi `/health/ready` của FastAPI trả 2xx. |

Readiness của API kiểm tra PostgreSQL, không buộc AI hoạt động. FastAPI ở giai đoạn
Colab trả 503 cho readiness, vì chưa cung cấp inference cho ứng dụng.
Các endpoint trạng thái dành cho phát triển trên loopback; dùng HTTPS và chính sách
truy cập phù hợp trước triển khai. Vite proxy `/api` đến backend nên chưa cần CORS.

Kiểm tra nhỏ bằng Python chuẩn, không cần thư viện ngoài (chạy sau build):

```sh
dotnet build apps/api --no-restore
python3 apps/api/tests/smoke.py
```

Kiểm tra này chạy API với DB cố ý không truy cập được và AI giả lập để kiểm tra
liveness, lỗi phụ thuộc, header token và JSON trạng thái. Kiểm tra Docker/DDL thật
được thực hiện riêng theo [hướng dẫn phát triển](development.md).
