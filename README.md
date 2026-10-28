# Findie

Findie là nền tảng tìm và trao trả đồ thất lạc, gồm giao diện React, API .NET, PostgreSQL và dịch vụ Python tìm kiếm bằng AI. README này hướng dẫn cài đặt và chạy **môi trường phát triển local từ đầu**.

Luồng cơ bản dùng PostgreSQL và Google OAuth để đăng nhập, đăng tin, tìm đồ, gửi yêu cầu nhận đồ và trao đổi tin nhắn. Docker Compose cung cấp PostgreSQL và RabbitMQ; worker Python hỗ trợ text, che ảnh và tìm ảnh bằng embedding đa phương thức. Model có thể chạy trên Ollama từ xa qua HTTPS có token.

## Chạy đầy đủ ở local với model Colab/ngrok

1. Cài các công cụ ở mục 1, giữ Google OAuth và R2 private trong `.env`, rồi chạy `make local-setup`. Lệnh tạo hai database/role riêng, migrate, broker và Hub demo; chạy lại giữ dữ liệu/credential.
2. Upload [notebook 04](notebooks/colab/04_full_stack_ollama_ngrok.ipynb) vào Colab GPU, chạy từng cell với token ngrok của bạn và một `FINDIE_OLLAMA_TOKEN` riêng tối thiểu 32 ký tự. Notebook kiểm text/image/vision trước khi mở gateway có Bearer token; tải `findie-colab.json` về máy.
3. Import cấu hình và chạy:

   ```sh
   python3 scripts/configure_ollama.py /duong-dan/findie-colab.json
   make local-run
   ```

   Lệnh import hỏi cùng `FINDIE_OLLAMA_TOKEN` đã nhập trên Colab; không đưa token vào chat/git. `local-run` kiểm worker/model trước khi chạy API và web. Mở **http://127.0.0.1:5173** và đăng nhập Google.
4. Trong terminal khác, cấp quyền thử luồng Hub cho tài khoản vừa đăng nhập và kiểm toàn hệ thống:

   ```sh
   make local-seed STAFF_EMAIL=dia-chi-google-cua-ban
   make local-doctor
   ```

5. Đăng ảnh → kiểm bản đã che → duyệt ảnh → công khai tin → tìm bằng mô tả/ảnh. Dùng tài khoản Google thứ hai cho luồng yêu cầu/chat/trao trả. Khi đổi model trên database có tin cũ, chạy `make local-reindex` sau khi worker ready. Đổi URL ngrok thì import lại JSON và khởi động lại `local-run`.

`Ctrl+C` dừng web/API/worker của phiên; `make local-stop` dừng database/broker, giữ volume. Google/R2 thật và phiên Colab/ngrok cần tài khoản/credential của bạn; doctor phân biệt đã cấu hình với đã kiểm chứng. Notebook không có keepalive, Colab không phải hosting thường trực. Chi tiết và giới hạn gói Colab trong [hướng dẫn AI](docs/guides/ai-service.md).

## 1. Cài công cụ cần thiết

Các lệnh bên dưới dùng shell Linux/macOS. Với Windows, chạy trong WSL2 và bật tích hợp Docker cho bản phân phối WSL đang dùng; cài các công cụ dòng lệnh trong cùng môi trường đó.

| Công cụ | Yêu cầu của project | Cài đặt |
| --- | --- | --- |
| Git | Để lấy mã nguồn | [Tải Git](https://git-scm.com/downloads/) |
| Docker và Docker Compose | Có lệnh `docker compose`; Docker daemon đang chạy | [Cài Docker](https://docs.docker.com/get-started/get-docker/) |
| Node.js và npm | **Node.js 24.x**, theo `.nvmrc` và `apps/web/package.json` | [Tải Node.js](https://nodejs.org/en/download) |
| .NET SDK | **10.0**, chọn bản SDK; `global.json` cho phép feature band mới trong dòng 10.0 | [Tải .NET 10 SDK](https://dotnet.microsoft.com/en-us/download/dotnet/10.0) |
| Python | **3.12**, theo `services/ai/.python-version`; cần có lệnh `python3` | [Tải Python](https://www.python.org/downloads/) |
| uv | Quản lý môi trường và package Python | [Cài uv](https://docs.astral.sh/uv/getting-started/installation/) |
| Make và curl | Chạy các lệnh trong `Makefile` và kiểm tra HTTP | Cài qua trình quản lý gói của hệ điều hành |

Kiểm tra trong terminal trước khi tiếp tục:

```sh
git --version
docker --version
docker compose version
docker info
node --version
npm --version
dotnet --version
python3 --version
uv --version
make --version
curl --version
```

Nếu uv chưa có Python 3.12, chạy `uv python install 3.12`. Lệnh này chuẩn bị interpreter cho dịch vụ AI; vẫn cần lệnh `python3` trên PATH để chạy các script của Makefile. Lần setup đầu cần mạng để tải dependency và Docker image. Chưa cần cài Ollama hoặc tải model để chạy luồng cơ bản.

## 2. Lấy mã nguồn và cài dependency

```sh
git clone https://github.com/qbael/FindieHackathon.git
cd FindieHackathon
```

Nếu đã có mã nguồn, mở terminal tại thư mục chứa `Makefile` và `compose.yaml`. **Tất cả lệnh bên dưới chạy từ thư mục gốc này**, kể cả khi mở terminal mới.

Nếu đã cài nvm, có thể chọn đúng Node.js bằng:

```sh
nvm install
nvm use
```

Khởi tạo project:

```sh
make setup
```

Lệnh này tạo `.env` với mật khẩu database, RabbitMQ và token nội bộ ngẫu nhiên; sinh cấu hình broker local, cài dependency Python bằng uv, restore package .NET và công cụ `dotnet-ef`, rồi cài dependency frontend bằng `npm ci`. Các package được lấy theo lockfile của project. Chỉ cần tạo cấu hình mà không cài dependency thì chạy `make env`.

Chạy lại `make setup` sẽ bổ sung biến cấu hình còn thiếu và giữ bí mật đã có. Không cần chép `.env.example` thành `.env`: file mẫu chứa placeholder, chưa phải cấu hình dùng để chạy. Giữ `.env` ở máy local; file này đã được bỏ qua bởi Git.

## 3. Cấu hình đăng nhập Google

Ứng dụng **chỉ đăng nhập bằng Google**, không có tài khoản/mật khẩu demo. Có thể mở trang chủ khi chưa cấu hình OAuth, nhưng các màn hình nghiệp vụ yêu cầu đăng nhập.

1. Tạo hoặc chọn project trong Google Cloud, cấu hình màn hình chấp thuận OAuth; thêm tài khoản dùng thử nếu ứng dụng ở chế độ Testing.
2. Tạo OAuth client loại **Web application**, theo [hướng dẫn Google](https://developers.google.com/identity/protocols/oauth2/web-server#creatingcred).
3. Thêm **Authorized redirect URI** chính xác như sau:

   ```text
   http://127.0.0.1:5173/api/auth/google/signin
   ```

4. Mở `.env`, sửa hai dòng có sẵn bằng thông tin client vừa tạo:

   ```dotenv
   Authentication__Google__ClientId='YOUR_CLIENT_ID.apps.googleusercontent.com'
   Authentication__Google__ClientSecret='YOUR_CLIENT_SECRET'
   ```

Mở ứng dụng bằng `http://127.0.0.1:5173` trong suốt quá trình đăng nhập. Nếu dùng `localhost`, phải đăng ký thêm URI tương ứng và dùng host đó nhất quán. Callback đi qua cổng **5173** của Vite; không đổi sang cổng 5080 của API cho phiên bắt đầu từ frontend.

Client secret chỉ nằm trong `.env` phía server, không đặt vào biến `VITE_*`. Sau mỗi lần sửa cấu hình OAuth, khởi động lại `make api`.

## 4. Khởi tạo database

Đảm bảo Docker đang chạy, sau đó:

```sh
make db-up
make rabbitmq-up
make db-migrate
docker compose ps
```

- `make db-up` khởi động PostgreSQL 17 có pgvector và chờ database sẵn sàng; mặc định dùng cổng `127.0.0.1:5432`.
- `make db-migrate` áp dụng EF migrations cho database nghiệp vụ `findie`, tạo 22 bảng ứng dụng, bảng lịch sử migration và role runtime `findie_app`. API không tự chạy migration khi khởi động.
- `make rabbitmq-up` sinh cấu hình và chạy RabbitMQ 4.3.2 với volume bền vững, healthcheck và các queue chỉ mục/kết quả được nạp sẵn. AMQP mặc định ở `127.0.0.1:5672`; giao diện quản trị tại [http://127.0.0.1:15672](http://127.0.0.1:15672), đăng nhập bằng `RABBITMQ_ADMIN_USER` và `RABBITMQ_ADMIN_PASSWORD` trong `.env`.
- Compose chạy PostgreSQL và RabbitMQ. API, frontend và dịch vụ Python chạy bằng các lệnh ở bước tiếp theo.

Database mới chưa có bài đăng hoặc tài khoản mẫu. `make local-setup` tạo Hub demo; sau khi đăng nhập Google lần đầu, dùng `make local-seed STAFF_EMAIL=...` để cấp quyền tại Hub demo. CLI chỉ chạy trong Development, không có public admin API.

Với database bootstrap cũ, migration chỉ tự chuyển khi cả 16 bảng cũ đều rỗng. Nếu đã có dữ liệu, script dừng để giữ nguyên dữ liệu; cần kế hoạch chuyển đổi riêng. Không nhập `docs/database/database-schema.sql` để thay thế EF migrations vì đó là snapshot cũ.

## 5. Chạy các dịch vụ

Mở **ba terminal** tại thư mục gốc project và giữ chúng chạy:

**Terminal 1 — dịch vụ Python:**

```sh
make ai
```

**Terminal 2 — API .NET:**

```sh
make api
```

**Terminal 3 — giao diện React:**

```sh
make web
```

| Thành phần | Địa chỉ mặc định |
| --- | --- |
| Giao diện | [http://127.0.0.1:5173](http://127.0.0.1:5173) |
| Đăng nhập | [http://127.0.0.1:5173/signin](http://127.0.0.1:5173/signin) |
| API .NET | `http://127.0.0.1:5080` |
| FastAPI nội bộ | `http://127.0.0.1:8000` |
| PostgreSQL | `127.0.0.1:5432` |
| RabbitMQ AMQP | `127.0.0.1:5672` |
| RabbitMQ Management | [http://127.0.0.1:15672](http://127.0.0.1:15672) |

Vite chuyển các request `/api` sang .NET. Trình duyệt không gọi PostgreSQL hoặc Python trực tiếp. Các lệnh `make api` và `make ai` tự nạp `.env`; không cần kích hoạt virtualenv thủ công.

Để thử luồng cơ bản, đăng nhập Google, vào **Đăng tin nhặt được**, tạo tin văn bản không đính kèm ảnh và chọn tự giữ đồ. Lưu rồi bấm **Công khai tin** ở màn hình tiếp theo để người khác thấy bài đăng. Dùng tài khoản Google thứ hai trong cửa sổ ẩn danh hoặc profile trình duyệt khác để gửi yêu cầu nhận đồ; quay lại tài khoản người giữ, chấp nhận yêu cầu rồi thử nhắn tin. Luồng Hub cần dữ liệu điểm tiếp nhận và quyền nhân viên được cấu hình thêm.

### Kiểm tra đã chạy thành công

Trong một terminal khác:

```sh
curl -i http://127.0.0.1:5080/health/live
curl -i http://127.0.0.1:5080/health/ready
curl -i http://127.0.0.1:8000/health/live
curl -sS http://127.0.0.1:5173/api/system/status
```

Ba lệnh đầu cần trả HTTP 200 khi tiến trình và kết nối database đã hoạt động. `/health/ready` của .NET chỉ kiểm kết nối database, không xác nhận đã migrate đủ bảng. Lệnh cuối kiểm tra cả đường proxy frontend → API; với OAuth đã cấu hình và chưa bật AI/R2, kết quả có dạng:

```json
{
  "name": "Findie API",
  "stage": "scaffold",
  "database": "ready",
  "ai": "unavailable",
  "features": {
    "business": true,
    "authentication": true,
    "storage": false
  }
}
```

`ai: "unavailable"` là trạng thái dự kiến khi chưa cấu hình worker. FastAPI chạy được không đồng nghĩa model đã sẵn sàng. `authentication: true` chỉ xác nhận đã điền cấu hình OAuth; vẫn phải thử đăng nhập để xác nhận client hợp lệ. Endpoint `/api/system/status` trả HTTP 200 cả khi phụ thuộc lỗi, nên cần đọc các trường trạng thái.

## 6. Bật tìm kiếm AI và cấu hình ảnh (tùy chọn)

Để bật gợi ý theo mô tả, thực hiện lần lượt theo [hướng dẫn AI service](docs/guides/ai-service.md#khởi-tạo-kho-tìm-kiếm-và-chạy-local):

1. Tạo database `findie_search` và role `findie_search_app` riêng trong PostgreSQL, đặt mật khẩu theo `SEARCH_POSTGRES_PASSWORD` của `.env`.
2. Điền `AI_SEARCH_MIGRATION_DSN` bằng tài khoản migration, chạy `make ai-migrate`, cấp quyền DML cho role runtime và điền `AI_SEARCH_DSN` bằng role đó. `make db-migrate` không tạo kho tìm kiếm này.
3. Chạy `make rabbitmq-up` nếu broker chưa chạy. Cấu hình local tự nạp [định nghĩa queue](docs/api/rabbitmq-definitions.json), tạo tài khoản quản trị và hai tài khoản runtime riêng cho .NET/Python. Python đã có `AI_RABBITMQ_URL` local; giữ `RabbitMq__Uri` trống cho đến khi worker sẵn sàng để job chỉ mục chưa bị retry khi thiếu AI. URI tùy chỉnh vẫn được giữ. Xem [cấu hình RabbitMQ](docs/guides/development.md#rabbitmq-docker).
4. Khởi chạy Ollama, tải model được chọn trong `AI_EMBEDDING_MODEL` (mặc định `qwen3-embedding:4b`), lấy digest đầy đủ từ `/api/tags` và điền `AI_EMBEDDING_REVISION`. `OLLAMA_BASE_URL` mặc định là `http://127.0.0.1:11434`.
5. Giữ model, revision, số chiều và search profile khớp giữa `AI_*` của Python và `Ai__*` của .NET. `.env` mới đã có các dòng nội suy; `.env` cũ cần kiểm tra vì setup không ghi đè giá trị đã tồn tại.
6. Khởi động lại `make ai`. Chỉ chạy một tiến trình Python; kiểm tra readiness bên dưới trước khi bật kết nối broker của API.

```sh
set -a
. ./.env
set +a
curl -i -H "X-Service-Token: ${AI_SERVICE_TOKEN}" http://127.0.0.1:8000/health/ready
```

HTTP 200 nghĩa là worker kiểm tra được broker, kho tìm kiếm và Ollama. HTTP 503 với `configuration_required` nghĩa là thiếu cấu hình bật worker; `dependency_unavailable` nghĩa là phụ thuộc chưa sẵn sàng. Chỉ source `.env` do bạn kiểm soát.

Sau khi readiness trả HTTP 200, sửa dòng `RabbitMq__Uri` trong `.env` như sau, đặt sau các biến `RABBITMQ_*`, rồi khởi động lại `make api`:

```dotenv
RabbitMq__Uri=amqp://${RABBITMQ_API_USER}:${RABBITMQ_API_PASSWORD}@127.0.0.1:${RABBITMQ_PORT}/%2F
```

Cloudflare R2 dùng các biến `Storage__Endpoint`, `Storage__Bucket`, `Storage__AccessKeyId`, `Storage__SecretAccessKey` để lưu ảnh đầu ra đã xử lý trong bucket riêng tư. Upload ảnh cần thêm model vision/revision; tìm ảnh cần model embedding có vision capability và `AI_IMAGE_SEARCH_ENABLED=true`. Notebook 04 và lệnh import cấu hình đồng bộ hai service. Chỉ output được duyệt mới công khai/lập chỉ mục; ảnh gốc chỉ giữ tạm trong RAM/transport. Xem [API ảnh và tìm kiếm](docs/api/media-search.md).

Notebook 01–03 là thử nghiệm độc lập; notebook 04 chuẩn bị model remote cho phiên chạy đầy đủ local. Xem [hướng dẫn Colab](docs/guides/colab.md).

## 7. Dừng, chạy lại và kiểm thử

Dừng ba tiến trình bằng `Ctrl+C` trong từng terminal, rồi dừng database:

```sh
make db-down
```

Lệnh này dừng cả PostgreSQL và RabbitMQ, giữ các volume dữ liệu. Chỉ dừng broker thì chạy `make rabbitmq-down`. **Không thêm `-v` vào `docker compose down` nếu muốn giữ dữ liệu.** Đổi mật khẩu quản trị trong `.env` cũng không tự đổi mật khẩu của database đã tồn tại.

Những lần chạy sau:

```sh
make db-up
make rabbitmq-up
make db-migrate
```

Sau đó mở lại ba terminal chạy `make ai`, `make api`, `make web`. Chạy lại `make setup` khi dependency hoặc các biến môi trường mẫu thay đổi.

Các lệnh kiểm thử sẵn có, chạy sau `make setup`:

| Lệnh | Phạm vi |
| --- | --- |
| `make check` | Test bootstrap/notebook, Python, build/smoke API, test và build frontend; không cần model AI thật |
| `make api-integration` hoặc `make db-check` | Kiểm migration và API với PostgreSQL/RabbitMQ tạm; cần Docker |
| `make ai-integration` | Kiểm worker và kho tìm kiếm với PostgreSQL/RabbitMQ tạm; Ollama được giả lập; cần Docker |

Hai bộ test tích hợp tự tạo và dọn container, không ghi vào database local của project. Chúng không thay thế kiểm tra Google OAuth, Ollama hoặc R2 thật. Một số test kho tìm kiếm trong `make check` được bỏ qua nếu thiếu database test; dùng `make ai-integration` để chạy nhóm này.

## 8. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `make`, `uv`, `dotnet`, `python3` hoặc `npm`: command not found | Cài công cụ ở bước 1, kiểm tra PATH và mở lại terminal. Trên WSL, kiểm tra công cụ có trong môi trường WSL đang dùng. |
| npm báo sai phiên bản Node hoặc không tìm thấy .NET SDK | Dùng Node 24.x và .NET SDK 10.0; kiểm tra lại `.nvmrc` và `global.json`. |
| Không kết nối được Docker | Mở Docker Desktop/daemon, kiểm tra `docker info`; trên WSL kiểm tra Docker integration. |
| Cổng 5432 bị chiếm | Đổi `POSTGRES_PORT` trong `.env` (ví dụ `5433`), chạy lại `make db-up` và khởi động lại API; DSN tìm kiếm tự điền cũng phải dùng cổng mới. |
| Cổng 5080, 5173 hoặc 8000 bị chiếm | Dừng tiến trình cũ đang dùng cổng rồi chạy lại. Vite dùng `strictPort`, không tự chuyển sang cổng khác. |
| Cổng 5672 hoặc 15672 bị chiếm | Đổi `RABBITMQ_PORT` hoặc `RABBITMQ_MANAGEMENT_PORT` trong `.env`, chạy lại `make rabbitmq-up` và khởi động lại API/Python. |
| Compose báo thiếu `.cache/rabbitmq/definitions.json` | Chạy `make env` trước `docker compose up`; `make rabbitmq-up` tự làm bước này. |
| API báo thiếu connection string/token hoặc DB chưa có bảng | Chạy `make setup`, `make db-up`, `make db-migrate`, rồi khởi động bằng `make api` để nạp `.env`. |
| Database báo sai mật khẩu dù đã sửa `.env` | Kiểm tra credential của volume hiện có; sửa file env không đổi mật khẩu PostgreSQL đã khởi tạo. Không xóa volume để thử nếu có dữ liệu cần giữ. |
| Đăng nhập Google bị vô hiệu hóa | Điền đủ hai biến OAuth và khởi động lại API. |
| Google báo `redirect_uri_mismatch` | Kiểm tra đúng scheme, host, port và path callback ở bước 3; không trộn `localhost` với `127.0.0.1`. |
| API nghiệp vụ trả 401 | Đăng nhập từ giao diện cổng 5173; request curl riêng không tự có cookie của trình duyệt. |
| AI báo unavailable/503 hoặc readiness trả 401 | Hoàn tất bước 6; readiness Python cần header `X-Service-Token`. Có thể tiếp tục dùng bộ lọc database khi AI chưa sẵn sàng. |
| Danh sách bài đăng hoặc Hub trống | Database mới không có dữ liệu seed. Tạo bài đăng bằng tài khoản Google; Hub cần dữ liệu và quyền nhân viên riêng. |

Xem log trực tiếp trong terminal API/Python/web; với PostgreSQL dùng `docker compose logs --tail=100 db`.

## Cấu trúc và tài liệu

```text
apps/
  web/src/                  React + TypeScript + Vite + Tailwind
    App.tsx, main.tsx        Điểm vào ứng dụng và điều hướng
    pages/                  Các màn hình nghiệp vụ
    components/             Thành phần giao diện dùng chung
    hooks/                  React hooks dùng chung
    lib/                    API, xác thực, xử lý dữ liệu và test tương ứng
    styles/                 CSS toàn cục
    assets/                 Font và hình ảnh
  api/                      .NET 10 + EF Core + Identity
    Controllers/, Services/, Repositories/, Models/, Contracts/
    Data/, Infrastructure/, Security/
    tests/integration/      Bộ kiểm thử tích hợp API
services/ai/                FastAPI và worker tìm kiếm văn bản qua Ollama
scripts/                    Khởi tạo .env, migration database và công cụ tài liệu
tests/                      Kiểm thử bootstrap và notebook
notebooks/colab/            Ba notebook thử nghiệm AI độc lập
docs/
  product/, architecture/   Đặc tả sản phẩm và kiến trúc hệ thống
  database/, api/           Thiết kế dữ liệu, SQL, ERD và hợp đồng API
  guides/                   Hướng dẫn phát triển, AI service và Colab
  design/, specs/           Thiết kế giao diện và hồ sơ triển khai
  assets/, demo/            Hình minh họa và tư liệu demo
compose.yaml                PostgreSQL 17 + pgvector và RabbitMQ
Makefile                    Các lệnh setup, chạy dịch vụ và kiểm thử
Findie.sln                  Solution API .NET và kiểm thử tích hợp
```

- [Mục lục tài liệu](docs/README.md) và [hướng dẫn phát triển chi tiết](docs/guides/development.md).
- [API .NET](docs/api/README.md) và [kiểm thử API](docs/api/testing.md).
- [AI service với Ollama](docs/guides/ai-service.md) và [notebook Colab](docs/guides/colab.md).
- [Kiến trúc hệ thống](docs/architecture/system-architecture.md) và [thiết kế database](docs/database/database-design.md).
- [Đặc tả sản phẩm](docs/product/DAC_TA_FINDIE.md) và [thiết kế giao diện Stitch](docs/design/stitch/README.md).
