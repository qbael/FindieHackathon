# Findie · 300 bài mẫu về đồ thất lạc

Bộ ngày 06/11/2026 có 20 bài Facebook công khai, 260 bài TimDo24h và 20 bài Tìm Đồ Thất Lạc. Mỗi thư mục có `source.json` ghi nguồn, mô tả đã biên tập, loại bài gốc, khu vực được nhắc đến và tên ảnh lấy từ bài. Một số liên kết Facebook mở trực tiếp ảnh của bài gốc. Đường dẫn TimDo24h dùng mã bài để tránh lặp lại thông tin cá nhân có thể có trong URL cũ.

`scenario` mô tả tình huống giả định để thử Findie. Trong mỗi nhóm cá nhân giữ, hub giữ và nơi ngoài hệ thống giữ có 25 bài cho mỗi kiểu thời gian: chưa rõ, chỉ ngày, giờ cụ thể và khoảng giờ. Một số khoảng giờ qua nửa đêm. 100 bài hub chia đều cho năm điểm giả định ở Thủ Đức, Quận 5, Bình Thạnh, Tân Bình và Quận 1. Các mốc dùng giờ Việt Nam.

Ảnh nguồn và ảnh chờ duyệt được giữ tại máy. Bản nháp và ảnh qua xử lý có thể xem bằng tài khoản nhập. Các mục `photo-*`, `processed-*`, `local-import-state.json`, `reviewed.json` và `masked-correction*` được loại khỏi Git vì có thể chứa ảnh giấy tờ và trạng thái của môi trường nhập. Giữ các ảnh tại chỗ nếu cần chạy lại trình nhập.

Từ thư mục gốc dự án, kiểm tra và chuẩn bị gói nhập:

```sh
python3 scripts/import_facebook_samples.py assets/facebook-batch-300 --validate
python3 scripts/import_facebook_samples.py assets/facebook-batch-300 --prepare-json /tmp/findie-batch-300-prepared.json
```

Dùng quy trình [nhập và duyệt ảnh](../facebook/README.md) với gói JSON mới. Các bài hub yêu cầu năm hub đã được tạo và tài khoản nhập có quyền nhận đồ tại từng hub. Xác nhận đích database trước khi chạy `local-seed` hoặc lệnh nhập vì cả hai dùng `ConnectionStrings__Database`. Luồng nhập mẫu tạo vector ảnh và chạy che vùng nhạy cảm. Bản chép OCR của giấy tờ được bỏ qua. Ảnh có giấy tờ và thẻ cần kiểm tra trực tiếp sau khi che trước khi duyệt.

Khi công khai kịch bản bằng `--publish-reviewed`, Findie đối chiếu đúng mã ảnh, phiên bản và SHA-256 của bản đã kiểm tra. Liên kết gốc được giữ trong manifest để tránh dẫn trực tiếp đến ảnh giấy tờ nguồn. Các bản xem trước khảm toàn ảnh được thay bằng ảnh rõ từ nguồn, chỉ che từng vùng nhạy cảm đã kiểm tra. Lịch sử thay ảnh được giữ trong trạng thái nhập để đối chiếu. Vector tìm kiếm được tạo từ đúng ảnh nguồn, gắn SHA-256 nguồn và phiên bản mô hình; ảnh công khai dùng bản đã che cục bộ.

Khi đã có `original-embedding-1.json` đúng hash ảnh nguồn trong từng thư mục, chế độ `--embed-originals` của công cụ nhập Development đồng bộ vector vào đúng mã ảnh, phiên bản và hash ảnh xử lý hiện tại. Chế độ này không đổi nội dung bài, nơi giữ hoặc trạng thái công khai. Các cache vector và bản duyệt theo tọa độ không được đưa vào Git.

Đối chiếu khôi phục ngày 07/11/2026: đủ 300 ảnh rõ và 300 vector từ ảnh nguồn; 297 bài đã công khai, 3 bài còn nháp (`timdocom-13650`, `timdocom-13694`, `timdocom-13931`) vì ảnh chưa đủ điều kiện duyệt. Chỉ mục của 297 bài công khai khớp toàn bộ giá trị vector nguồn; 300 tác vụ lập chỉ mục đã hoàn tất. Năm phép tìm kiếm ảnh mẫu đều trả đúng bài ở vị trí đầu. Xem số liệu và phiên bản mô hình trong [restoration-report.json](restoration-report.json).
