# Tài liệu Findie

Tài liệu sản phẩm, thiết kế, hướng dẫn phát triển và tư liệu demo được tập trung trong thư mục này.

## Sản phẩm và thiết kế

- Đặc tả ứng dụng: [Markdown](DAC_TA_FINDIE.md), [Word](DAC_TA_FINDIE.docx), [PDF](DAC_TA_FINDIE.pdf).
- [Kiến trúc hệ thống](system-architecture.md).
- Cơ sở dữ liệu: [thiết kế](database-design.md), [từ điển cột](database-column-dictionary.md), [DDL](database-schema.sql), [SQL kiểm tra](database-check.sql).
- Sơ đồ ERD: [bản chỉnh sửa draw.io](findie-erd.drawio), [ảnh tổng quan](assets/findie-erd-overview.png).
- [Hiến chương dự án](../.specify/memory/constitution.md) được giữ tại vị trí cấu hình của Spec Kit.

## Phát triển và kiểm thử

- [Cài đặt và chạy local](development.md).
- [API .NET](api.md).
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
