# Findie

Nền tảng tìm và trao trả đồ thất lạc. Đã khởi tạo môi trường phát triển dựa trên
[đặc tả](DAC_TA_FINDIE.md), [kiến trúc](system-architecture.md) và
[hiến chương](../.specify/memory/constitution.md). Đây là bộ khung có thể chạy;
nghiệp vụ đăng tin, tìm kiếm, nhận đồ, đăng nhập, chat, worker và upload R2 chưa được xây.

## Cấu trúc

```text
apps/
  web/                 React + TypeScript + Vite; trang trạng thái, proxy /api
  api/                 ASP.NET Core .NET 10 + Npgsql; health và trạng thái dịch vụ
services/
  ai/                  FastAPI nội bộ; xác thực shared token, chưa nạp model local
notebooks/
  colab/               Hai notebook standalone: Qwen Embedding và Instruct/OpenCV
docs/                  Toàn bộ tài liệu, hồ sơ triển khai và tư liệu demo
  specs/001-project-bootstrap/  Phạm vi, kế hoạch và nhiệm vụ lần khởi tạo
scripts/init_env.py     Tạo .env riêng, không ghi đè cấu hình đã có
tests/                 Kiểm tra bootstrap và notebook
compose.yaml           PostgreSQL 17 + pgvector; volume dữ liệu, chỉ bind loopback
Makefile               Lệnh cài đặt, chạy và kiểm tra
```

## Chạy local

Cần Docker Engine + Compose, Node.js 24 (`nvm use`), .NET SDK 10, Python 3.12,
[uv](https://docs.astral.sh/uv/getting-started/installation/) và Make.
Các lệnh trong tài liệu chạy từ thư mục gốc dự án. `uv` dùng Python 3.12 cho dịch vụ AI; nếu thiếu, dùng
`uv python install 3.12` trước khi setup.

```sh
make setup
make db-up
make db-check
```

`make setup` sinh mật khẩu DB và token nội bộ ngẫu nhiên trong `.env` (quyền `0600`),
cài gói theo lockfile. Chạy lại sẽ giữ nguyên `.env`. Không đưa tệp này vào Git.
Hai biến `AI_SERVICE_TOKEN` và `Ai__ServiceToken` dùng chung một giá trị qua nội suy;
chỉ cần đổi `AI_SERVICE_TOKEN`. Không dùng biến `VITE_*` cho bí mật.

Mở ba terminal tại thư mục gốc:

```sh
make ai       # Terminal 1: http://127.0.0.1:8000
make api      # Terminal 2: http://127.0.0.1:5080
make web      # Terminal 3: http://127.0.0.1:5173
```

Mở [giao diện local](http://127.0.0.1:5173). React gọi `/api` qua proxy Vite tới .NET;
trình duyệt không gọi FastAPI hay DB trực tiếp. API/FastAPI bind loopback cho local;
chưa cấu hình triển khai internet/HTTPS.

| Endpoint | Ý nghĩa |
| --- | --- |
| `.NET GET /health/live` | Tiến trình API đang chạy |
| `.NET GET /health/ready` | `SELECT 1` DB thành công; lỗi trả 503 |
| `.NET GET /api/system/status` | Trạng thái DB/AI thật và các cờ tính năng chưa triển khai |
| `FastAPI GET /health/live` | Tiến trình Python đang chạy |
| `FastAPI GET /health/ready` | Cần `X-Service-Token`; hiện trả 503 vì model chỉ chạy Colab |
| `FastAPI GET /v1/status` | Cần token; model ID, số chiều và `inferenceReady: false` |

AI hiện **chưa sẵn sàng suy luận** trên trang trạng thái là đúng. Không có endpoint trả
vector giả hoặc tự động duyệt ảnh. Hai notebook chạy riêng, chưa nối Colab với local API.

Không dùng Make thì chạy từng lệnh tương ứng trong `Makefile`. Trước chạy API/AI,
nạp cấu hình vào shell: `set -a; . ./.env; set +a`. Chỉ source `.env` do mình kiểm soát.

## Database Docker

Compose dùng project `hackathon-findie` và volume `hackathon-findie_postgres_data`,
tách với volume Findie PostgreSQL 16 có sẵn trên máy. Dùng DDL hiện có ở
[database-schema.sql](database-schema.sql) làm nguồn duy nhất cho lần khởi tạo,
gồm 16 bảng và `vector(2048)`; không tạo HNSW cho vector 2048 chiều.

```sh
docker compose ps
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
make db-check
make db-down
```

`db-check` dùng [database-check.sql](database-check.sql); dữ liệu kiểm tra được rollback.
`db-down` giữ volume. SQL init chỉ chạy khi volume rỗng; sửa DDL hoặc mật khẩu trong
`.env` không tự cập nhật DB đã có. Với dữ liệu đã tồn tại, tạo migration/đổi mật khẩu có
chủ đích và sao lưu trước; bộ khung không tự xóa volume hay áp lại DDL.

DB role hiện là role bootstrap của môi trường local; trước dùng dữ liệu thật cần role
runtime giới hạn quyền và quy trình migration, backup/restore. FastAPI không nhận credential DB.
Hành vi init và lưu volume theo [tài liệu Docker PostgreSQL](https://docs.docker.com/guides/postgresql/);
image từ [pgvector chính thức](https://github.com/pgvector/pgvector).

## Thử model trên Google Colab Free

Xem [hướng dẫn notebook](colab.md). Mở từng `.ipynb` bằng
Colab → **Upload notebook**, chọn GPU và chạy cell theo thứ tự:

1. [Qwen Embedding 2B](../notebooks/colab/01_qwen_embedding.ipynb): mô tả tiếng Việt,
   ảnh, vector 2048 chiều chuẩn hóa và thử xếp hạng cosine trong từng chế độ.
2. [Qwen Instruct 4B + OpenCV](../notebooks/colab/02_qwen_redaction.ipynb): nạp 4-bit,
   gợi ý vùng nhạy cảm, kiểm tra tọa độ và tạo bản che/mờ để con người duyệt.

Chạy một model mỗi lần, giải phóng/xóa runtime trước đổi notebook. GPU và thời gian chạy
miễn phí không được đảm bảo; xem [Colab FAQ](https://research.google.com/colaboratory/faq.html).
Chỉ dùng ảnh tổng hợp hoặc dữ liệu được phép thử. Không tải credential DB/R2 vào Colab,
không mở API/tunnel công khai. Kết quả là thử nghiệm, chưa xác nhận chất lượng trên dữ liệu Findie.

## Cấu hình và kiểm tra

`.env.example` có DB, AI endpoint/token và cấu hình R2 server. Khi chọn tài khoản R2,
điền `Storage__Endpoint`, `Storage__Bucket`, `Storage__AccessKeyId`, `Storage__SecretAccessKey`;
các giá trị này mới là cấu hình dự phòng, chưa có chức năng upload. Nhà cung cấp OIDC chưa chọn.
Các dependency được ghi trong `package-lock.json`, `packages.lock.json`, `uv.lock`;
revision/model inference và gói Colab nằm trong notebook.

```sh
make check       # Bootstrap, notebook, API build/smoke, AI tests, web tests/build
make db-check    # Kiểm tra SQL trên DB Docker đang chạy
```

Kiểm tra notebook local chỉ xác nhận cấu trúc/cú pháp và logic không cần model. Chạy cell
cài gói, tải trọng số, GPU inference và benchmark Colab cần phiên GPU thực tế.

Tài liệu và tư liệu demo được tập trung tại [mục lục tài liệu](README.md). Trạng thái triển khai
nằm trong tài liệu này và [hồ sơ bootstrap](specs/001-project-bootstrap/spec.md); không coi
toàn bộ bản thiết kế là đã hoàn thành.

Đã kiểm chứng local ngày 2026-10-22: `make setup`, kiểm tra bootstrap/notebook,
2 kiểm thử FastAPI, build .NET (0 warning/error), smoke dependency lỗi/token,
2 kiểm thử web và production build đều qua. DB Docker khởi tạo đủ 16 bảng, UTC,
pgvector 0.8.2; SQL check qua dữ liệu hợp lệ và 15 trường hợp sai. Luồng web → .NET → DB
đã trả trạng thái sẵn sàng; AI trả chưa sẵn sàng đúng cấu hình Colab. Bốn kiểm thử CPU
notebook qua schema/cú pháp, vector, EXIF/GPS, JSON/tọa độ và pixel che/mờ.
Chưa chạy tải trọng số hoặc inference trên GPU Colab thực tế.
