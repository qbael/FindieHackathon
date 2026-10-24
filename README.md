# Findie

Nền tảng tìm và trao trả đồ thất lạc. Dự án hiện có bộ khung React, .NET, FastAPI và hai notebook thử nghiệm AI.

API .NET có Entity Framework Core/PostgreSQL, ASP.NET Core Identity và cấu trúc controller → service → repository. React đã có đăng nhập **chỉ bằng Google**, hồ sơ phiên và đăng xuất; cần điền OAuth client server theo [hướng dẫn](docs/development.md#đăng-nhập-google). Luồng mẫu API: hồ sơ người dùng và tra cứu điểm tiếp nhận.

Chạy `make setup`, `make db-up`, `make db-migrate` trước khi dùng; xem [API](docs/api.md). Migration tạo 22 bảng ứng dụng, lịch sử EF, outbox snapshot/tombstone và database tìm kiếm với role riêng. Bootstrap cũ chỉ được chuyển tự động khi cả 16 bảng đều rỗng; lệnh từ chối nếu đã có dữ liệu.

Kiến trúc đích v1.4.0 ngày 23/10/2026: .NET xử lý nghiệp vụ, R2, job/outbox, quyền hiện tại và DTO cuối; Python xử lý AI/ảnh, lưu embedding và hybrid search với profile cấu hình theo từng trường hợp. Hai dịch vụ giao tiếp qua RabbitMQ/AMQP lâu dài. Một PostgreSQL instance chứa hai database logic: `findie` chỉ .NET truy cập, `findie_search` dùng pgvector/FTS và bản chiếu tìm kiếm công khai chỉ Python truy cập. Đã có schema hai database; RabbitMQ, consumer, lập chỉ mục và hybrid search chưa triển khai. Xem [kiến trúc hệ thống](docs/system-architecture.md).

Ảnh gốc chỉ được giữ tạm trong RAM .NET/Python để xử lý, không lưu R2. Python phát hiện thông tin cá nhân (PII) thì che/mờ; không phát hiện PII vẫn chuẩn hóa và mã hóa lại ảnh sạch. .NET chỉ lưu ảnh đầu ra vào R2 riêng tư, con người duyệt trước công khai. Bỏ dữ liệu gốc khi hoàn tất/lỗi/hết hạn; nếu mất payload phải tải lại. Outbox bền vững chỉ giữ metadata/chỉ mục, không giữ bytes gốc; payload ảnh qua broker có TTL và quy trình dọn riêng.

Toàn bộ tài liệu ứng dụng nằm trong [docs](docs/README.md), gồm [hướng dẫn chạy local](docs/development.md), [đặc tả](docs/DAC_TA_FINDIE.md) và [hướng dẫn Colab](docs/colab.md).
