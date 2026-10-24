# Tài liệu Findie

Tài liệu sản phẩm, thiết kế, hướng dẫn phát triển và tư liệu demo được tập trung trong thư mục này.

## Sản phẩm và thiết kế

- Đặc tả ứng dụng: [Markdown](DAC_TA_FINDIE.md), [Word](DAC_TA_FINDIE.docx), [PDF](DAC_TA_FINDIE.pdf).
- [Kiến trúc hệ thống](system-architecture.md): v1.4.0 ngày 23/10/2026; .NET nghiệp vụ/R2/quyền/DTO cuối ↔ RabbitMQ lâu dài ↔ Python AI/ảnh, lưu embedding và hybrid search theo profile. Đã có schema hai database logic `findie` (.NET) và `findie_search` (Python) với role riêng; chưa triển khai RabbitMQ/consumer/hybrid search. Ảnh gốc chỉ tạm để xử lý, không lưu R2; R2 chỉ giữ ảnh đầu ra đã che/mờ hoặc ảnh sạch chuẩn hóa khi không có PII, phải duyệt trước công khai.
- [Thiết kế cơ sở dữ liệu đích](database-design.md): phân quyền hai database logic cho .NET và Python. Runtime .NET có EF Core/Identity, outbox và migration có bảo vệ dữ liệu bootstrap cũ; xem [API](api.md).
- Snapshot bootstrap: [từ điển cột](database-column-dictionary.md), [DDL](database-schema.sql), [SQL kiểm tra](database-check.sql), [ERD draw.io](findie-erd.drawio), [ảnh ERD](assets/findie-erd-overview.png). Các tệp này vẫn mô tả 16 bảng/164 cột và liên kết ảnh gốc/bản xử lý cũ; chưa phải schema hybrid search hai database hoặc chính sách chỉ lưu ảnh đầu ra. Giữ nguyên để đối chiếu migration, không dùng luồng lưu ảnh gốc cũ làm kiến trúc đích.
- [Hiến chương dự án](../.specify/memory/constitution.md) được giữ tại vị trí cấu hình của Spec Kit.

## Phát triển và kiểm thử

- [Cài đặt và chạy local](development.md), gồm cấu hình OAuth Google; ứng dụng hiện chỉ hỗ trợ đăng nhập Google.
- [API .NET](api.md): Google cookie/CSRF, hồ sơ và điểm tiếp nhận.
- [Thử AI trên Google Colab](colab.md).
- Hồ sơ khởi tạo: [phạm vi](specs/001-project-bootstrap/spec.md), [kế hoạch](specs/001-project-bootstrap/plan.md), [nhiệm vụ](specs/001-project-bootstrap/tasks.md), [đánh giá sẵn sàng](specs/001-project-bootstrap/readiness-review.md).

## Tư liệu demo

- [Tóm tắt Findie](demo/findie-dang-bai/TOM_TAT_FINDIE.txt) và [video demo](demo/findie-dang-bai/findie-demo.mp4).
- Các luồng: [đăng đồ nhặt được](demo/findie-dang-bai/01-dang-do-nhat-duoc.png), [tìm đồ](demo/findie-dang-bai/02-tim-do-that-lac.png), [yêu cầu và hẹn trả](demo/findie-dang-bai/03-yeu-cau-va-hen-trao-tra.png), [nhận tại điểm tiếp nhận](demo/findie-dang-bai/04-nhan-tai-diem-tiep-nhan.png).

## Tạo lại sơ đồ

Chạy từ thư mục gốc dự án. Các script render dùng Playwright của runtime Codex và Google Chrome trên máy hiện tại.

```sh
python3 scripts/docs/erd/build_erd.py
node scripts/docs/erd/render_local.cjs
node scripts/docs/render_architecture.cjs
```

Script cập nhật sơ đồ và ảnh trong `docs/`; đầu ra kiểm tra tạm nằm trong `.cache/docs/`.
