# Dữ liệu mẫu có nguồn thực tế

Thu thập ngày **02/11/2026** từ nhóm Cộng đồng Sinh viên SGU trên Facebook và các website tìm đồ công khai đã được cho phép: `timdothatlac.vn`, `timdo24h.vn`, `timdo24h.com`.

Mỗi thư mục con là một bài nguồn riêng biệt:

- `source.json`: liên kết nguồn, nội dung trích hoặc diễn đạt trung thực, loại bài gốc (`lost`/`found`), địa điểm được nêu, thời điểm thu thập và danh sách ảnh.
- `photo-*`: ảnh đồ vật lấy từ chính bài nguồn. Không dùng ảnh sinh bằng AI hoặc ảnh minh họa thay thế. Nếu cần bỏ metadata vị trí hoặc tách khung ảnh chính của tệp MPO thành JPEG tĩnh, giữ nguyên dữ liệu điểm ảnh và hướng hiển thị; kiểm tra hai điều này bằng SHA-256 của điểm ảnh đã giải mã. Trường `photoNormalization` ghi lại bước chuẩn hóa; tệp MPO không có GPS được giữ thêm dưới tên `original-*`.
- `local-import-state.json`: mã bài trong Findie và danh sách ảnh đã qua luồng xử lý ảnh thật của ứng dụng.
- `processed-*`: ảnh đầu ra thực tế để kiểm tra trước khi duyệt.
- `reviewed.json`, nếu có: ảnh đầu ra cụ thể đã được kiểm tra, xác định bằng mã ảnh, phiên bản và SHA-256.

Tên món đồ nhập vào Findie dùng tên từ nguồn, không thêm tiền tố **[Mẫu]**. Phần mô tả giữ liên kết nguồn và thông báo ứng dụng không giữ món đồ. Bài gốc báo mất được ghi rõ là chuyển thể để thử nghiệm luồng nhặt đồ; địa điểm vẫn là khu vực báo mất, chưa xác nhận có người nhặt được. Không suy diễn ngày nhặt từ ngày đăng. Việc thu thập không xác nhận món đồ hiện vẫn thất lạc hoặc chưa được trả lại.

Ảnh giấy tờ định danh, ảnh người, áp phích có thông tin liên hệ và ảnh sản phẩm dựng sẵn đã được loại khỏi bộ mẫu. Thông tin liên hệ và tên cá nhân không cần thiết được bỏ khỏi phần mô tả. Nhóm SGU là nhóm riêng tư; trường `sourceVisibility` của mẫu SGU lưu đúng tính chất này.

Kiểm tra bộ dữ liệu và chuẩn bị đầu vào cho lệnh nhập local:

```sh
python3 scripts/import_facebook_samples.py --validate
python3 scripts/import_facebook_samples.py --prepare-json /tmp/findie-public-samples.json
```

Lệnh nhập chỉ chạy trong môi trường Development, dùng tài khoản Google đã đăng nhập và gọi các service nghiệp vụ/xử lý ảnh hiện có. Nhập bản nháp không tự duyệt hoặc công khai ảnh. Không nhập trực tiếp các bản ghi nghiệp vụ vào database.

Sau khi nạp cấu hình API hiện có từ `.env` và đặt `ASPNETCORE_ENVIRONMENT=Development`, dùng:

```sh
dotnet run --project apps/api --no-build --no-launch-profile -- \
  --import-public-samples /tmp/findie-public-samples.json \
  --actor-email baohoo1002@gmail.com
```

Thêm `--drafts-only` để lưu nội dung bản nháp khi Colab chưa sẵn sàng; ảnh nguồn vẫn ở local. Chạy lại lệnh thường sau khi AI hoạt động sẽ tải các ảnh còn thiếu vào đúng bản nháp, dùng lại ảnh đã hoàn tất. Chạy một tiến trình nhập tại một thời điểm và giữ nguyên bộ nguồn trong lúc nhập.

`--sync-titles` đồng bộ riêng tên các bản nháp cũ để bỏ tiền tố `[Mẫu]`, giữ nội dung hiện tại và đối chiếu fingerprint cũ trước khi chuyển trạng thái nhập. `--review-only` duyệt ảnh đã kiểm tra trực tiếp theo `reviewed.json` (đúng mã, phiên bản và SHA-256), để ảnh xuất hiện trên bản nháp.

Một số ảnh cần che bổ sung chi tiết mà AI bỏ sót. `masked-correction.json` ghi ảnh xử lý cũ, các vùng che, bản PNG che bổ sung và hash; ảnh nguồn vẫn giữ nguyên. Bản che chỉ dùng các hình chữ nhật đen của bộ xử lý hiện có và được kiểm tra pixel ngoài vùng che không đổi. `--replace-masked` thay ảnh qua service nghiệp vụ, lưu journal để tiếp tục khi gián đoạn và giữ lịch sử trong state; ảnh đầu ra mới vẫn cần kiểm tra trực tiếp trước `--review-only`. Các chế độ này không tự công khai bài.
