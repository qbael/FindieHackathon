# Kế hoạch khởi tạo

## Đối chiếu hiến chương trước thiết kế

- Giữ React → .NET → PostgreSQL; FastAPI không có quyền truy cập DB/R2.
- Chưa xây luồng bảo vệ khi nhà cung cấp danh tính và quy tắc nhận đồ chưa chốt.
- Database chỉ bind loopback, dữ liệu có volume; không thêm lệnh tự động xóa volume.
- Model chạy thử Colab riêng; không mở tunnel công khai hay coi Colab là host API.
- Vector 2048 chiều, cùng model/revision/profile; ảnh phải được người thử kiểm tra.

## Cấu trúc và lựa chọn

- `apps/web`: React/TypeScript/Vite, trang trạng thái và proxy API local.
- `apps/api`: .NET 10 LTS, Npgsql 10; probe DB, API trạng thái, cấu hình AI/R2.
- `services/ai`: Python 3.12/FastAPI, liveness và trạng thái nội bộ có shared token.
- `notebooks/colab`: hai notebook độc lập, khóa revision, giảm VRAM, export kết quả.
- Root: Compose PostgreSQL 17/pgvector 0.8.2; schema tham chiếu trực tiếp từ docs.

Không tạo bộ entity/EF migration song song với SQL ở giai đoạn này; khi có nghiệp vụ,
chốt cách quản lý migration và runtime DB role giới hạn quyền trước dùng dữ liệu thật.
R2 có cấu hình server, chưa kết nối tài khoản. Không cần thêm Redis/queue/vector DB.

## Kiểm chứng và đối chiếu sau thiết kế

Build frontend/API; thử trạng thái khi dependency lỗi và xác thực nội bộ; chạy SQL check
trên DB Docker thực; kiểm tra notebook JSON/cell Python và validation không cần GPU.
Không tuyên bố đã benchmark hay chạy inference trên GPU Colab nếu chưa có phiên thực tế.
Thiết kế giữ nguyên ranh giới, không triển khai thay đổi quyền/custody/chat trong lần khởi tạo.
