# Đặc tả ứng dụng Findie

Chức năng luồng nghiệp vụ và công nghệ lựa chọn

Phiên bản 1.1.1 · Ngày 22 tháng 10 năm 2026

## 1 Tổng quan và phạm vi

Findie kết nối người mất đồ, người nhặt được và các điểm tiếp nhận để tìm kiếm, xác minh và trao trả đồ thất lạc. Ứng dụng tập trung thông tin đang phân tán ở nhiều nhóm cộng đồng và hỗ trợ người tìm chỉ nhớ đặc điểm món đồ, kể cả khi không có ảnh.

Tài liệu này xác định chức năng, dữ liệu đầu vào, luồng xử lý, quy tắc nghiệp vụ và tiêu chí nghiệm thu cho MVP. Đối tượng sử dụng là nhóm sản phẩm, thiết kế, phát triển và kiểm thử.

**Trạng thái sản phẩm:** demo ý tưởng với giao diện và dữ liệu minh họa. Phần 2 đến phần 7 kết hợp hành vi thể hiện trong demo với các ràng buộc MVP được đề xuất và đánh dấu riêng. React, .NET, Python với FastAPI và PostgreSQL đã được lựa chọn. Cập nhật ngày 21/10/2026 bổ sung Cloudflare R2 để lưu ảnh, họ mô hình Qwen và OpenCV làm mờ ảnh theo yêu cầu. Cập nhật ngày 22/10/2026 chọn bản Instruct 4B. Các thư viện, model embedding và lược đồ cụ thể bên dưới là thiết kế đề xuất, chưa phải triển khai đã vận hành.

### Mục tiêu

- Cho phép đăng thông tin đồ nhặt được kèm ảnh và nơi đang giữ.
- Hỗ trợ tìm bằng mô tả tiếng Việt hoặc ảnh, kết hợp khu vực và thời gian.
- Hướng dẫn nhận lại đồ theo đúng loại nơi giữ và kiểm soát việc kết nối hai bên.
- Ghi nhận tiếp nhận và bàn giao để thông tin nơi giữ phản ánh đúng thực tế.

### Tác nhân

| Tác nhân | Trách nhiệm chính | Phạm vi quyền đề xuất |
| --- | --- | --- |
| Người tìm | Tìm đồ, xem nơi giữ, gửi yêu cầu và nhận lại đồ | Xem tin công khai; quản lý yêu cầu và hội thoại của mình |
| Người nhặt hoặc người giữ | Đăng tin, cung cấp thông tin xác minh, xét yêu cầu, trao trả | Quản lý tin do mình đăng và yêu cầu liên quan |
| Nhân viên điểm tiếp nhận | Tiếp nhận đồ, xác minh trực tiếp, ghi nhận bàn giao | Chỉ thao tác đối với điểm được phân công |
| Nơi ngoài hệ thống | Là địa điểm giữ đồ được ghi trong bài đăng | Không mặc định có tài khoản hay chức năng quản trị |

Một người có thể vừa là người tìm vừa là người nhặt. Tài khoản và phân quyền là yêu cầu bổ sung cho MVP; demo chưa đặc tả màn đăng nhập. Phạm vi MVP chưa bao gồm thanh toán, phí chuộc đồ, vận chuyển hay tự động kết luận quyền sở hữu.

<!-- pagebreak -->

## 2 Danh mục chức năng

Các mã chức năng dưới đây dùng để đối chiếu giữa nghiệp vụ và tiêu chí nghiệm thu. “Theo demo” là hành vi được thể hiện bằng ảnh hoặc mô tả; không có nghĩa chức năng đã được triển khai.

| Mã | Chức năng | Căn cứ và phạm vi |
| --- | --- | --- |
| F01 | Đăng đồ nhặt được | Theo demo: tải ảnh, xem trước, mô tả, nơi và thời điểm nhặt, chọn nơi giữ |
| F02 | Tìm đồ thất lạc | Theo demo: tìm bằng mô tả hoặc ảnh, kèm khu vực và thời gian |
| F03 | Xem món đồ và cách nhận | Theo demo: thông tin món đồ, nơi giữ và bước nhận tương ứng |
| F04 | Gửi yêu cầu nhận đồ | Theo demo: áp dụng khi cá nhân giữ, có 0 đến 3 câu hỏi xác minh tùy chọn |
| F05 | Xét duyệt yêu cầu | Theo demo: người giữ xem câu trả lời rồi phê duyệt hoặc từ chối |
| F06 | Nhắn tin hẹn trao trả | Theo demo: mở chat sau phê duyệt để hai bên tự thỏa thuận |
| F07 | Chuyển vào điểm tiếp nhận | Demo nêu quy tắc chờ duyệt; các bước bàn giao chi tiết là đề xuất |
| F08 | Nhận tại điểm tiếp nhận | Theo demo: xem địa chỉ, xem đường đi, xác minh trực tiếp, ghi nhận bàn giao |
| F09 | Nhận tại nơi ngoài hệ thống | Theo demo: xem tên nơi giữ, địa chỉ và hướng dẫn đã ghi |
| F10 | Tài khoản và phân quyền | Đề xuất MVP để bảo vệ bài đăng, yêu cầu, bằng chứng và tin nhắn |
| F11 | Bảo vệ ảnh trước công khai | Yêu cầu bổ sung: lưu R2, Qwen gợi ý vùng nhạy cảm, OpenCV làm mờ/che và người dùng kiểm tra bản sạch |

### Màn hình chính

1. **Tìm kiếm:** nhập thông tin mất đồ, xem kết quả và chi tiết món đồ.
2. **Đăng tin:** nhập thông tin đồ nhặt được, nơi giữ và câu hỏi xác minh nếu có.
3. **Yêu cầu nhận đồ:** gửi yêu cầu, xem trạng thái và xét duyệt theo vai trò.
4. **Hội thoại:** nhắn tin trong các yêu cầu đã được duyệt.
5. **Tiếp nhận và bàn giao:** dành cho nhân viên điểm được phân quyền.

Demo có mục điều hướng “Hồ sơ”. Nội dung quản lý tài khoản, lịch sử bài đăng và lịch sử yêu cầu trong mục này cần được chốt riêng; không suy ra toàn bộ chức năng chỉ từ nhãn điều hướng.

### Ranh giới nghiệp vụ

Kết quả tìm kiếm chỉ gợi ý món đồ có đặc điểm tương tự. Người giữ hoặc nhân viên điểm tiếp nhận chịu trách nhiệm xác minh trước khi trao trả. Findie ghi nhận thông tin và hỗ trợ kết nối; điểm tương đồng do AI tính không thay thế bước xác minh.

<!-- pagebreak -->

## 3 Đăng tin đồ nhặt được

**Chức năng:** F01. **Tác nhân:** người nhặt hoặc người giữ. **Kết quả:** có bài đăng hiển thị thông tin món đồ và nơi giữ hiện tại.

### Luồng chính

1. Người dùng mở Đăng tin và chọn ảnh từ thiết bị.
2. Hệ thống hiển thị ảnh xem trước để người dùng kiểm tra.
3. Người dùng bổ sung mô tả, nơi nhặt, ngày và khoảng giờ nhặt.
4. Người dùng chọn Tự giữ để trả, Nơi ngoài hệ thống hoặc Điểm tiếp nhận.
5. Người dùng kiểm tra thông tin và gửi đăng tin.
6. Hệ thống kiểm tra dữ liệu, lưu bài đăng và hiển thị kết quả. Nếu gửi vào điểm tiếp nhận, xử lý theo phần 6.
7. Theo yêu cầu bổ sung cho MVP, ảnh gốc nằm riêng tư trên R2. Qwen gợi ý vùng nhạy cảm, OpenCV tạo bản che/mờ; người có quyền duyệt ảnh kiểm tra, bổ sung vùng còn sót và duyệt bản sạch trước công khai. Trong lúc chờ hoặc khi xử lý lỗi, bài đăng dùng ảnh thay thế trung tính; không công khai ảnh gốc.

### Dữ liệu đầu vào

| Trường | Nội dung | Quy tắc MVP đề xuất |
| --- | --- | --- |
| Ảnh món đồ | Ảnh chụp đồ nhặt được | Ít nhất 1 ảnh; JPEG, PNG hoặc WebP; tối đa 10 MB mỗi ảnh |
| Mô tả | Loại đồ, màu sắc, đặc điểm nhìn thấy | Bắt buộc; không công khai thông tin dùng để xác minh chủ sở hữu |
| Nơi nhặt | Khu vực hoặc địa điểm tìm thấy | Bắt buộc; tách với nơi đang giữ |
| Thời điểm nhặt | Ngày và khoảng giờ | Ngày bắt buộc; cho phép đánh dấu không nhớ giờ chính xác |
| Loại nơi giữ | Cá nhân, điểm tiếp nhận, ngoài hệ thống | Chọn 1 loại; không đổi nơi giữ chỉ vì gửi yêu cầu tiếp nhận |
| Thông tin nơi giữ | Điểm trong danh sách hoặc tên nơi, địa chỉ, hướng dẫn | Địa chỉ công khai dành cho điểm hoặc nơi ngoài hệ thống |
| Câu hỏi xác minh | Đặc điểm riêng để người nhận trả lời | Từ 0 đến 3 câu hỏi, tùy chọn; cách tạo là đề xuất MVP |

Các giới hạn dung lượng và tính bắt buộc ở bảng là cấu hình nghiệp vụ đề xuất, chưa phải ràng buộc đã được demo xác nhận.

### Ngoại lệ đề xuất cho MVP

- Tệp sai định dạng hoặc quá dung lượng: báo lỗi tại trường ảnh và giữ các dữ liệu đã nhập.
- Tải ảnh hoặc đăng tin thất bại: không báo đăng thành công; cho phép gửi lại mà không tạo bài trùng.
- Khoảng giờ không hợp lệ hoặc ngày trong tương lai: yêu cầu sửa trước khi gửi.
- Chọn nơi ngoài hệ thống nhưng thiếu địa chỉ: yêu cầu bổ sung để người tìm biết nơi đến nhận.
- Qwen/OpenCV lỗi hoặc ảnh chưa duyệt: giữ bài đăng và mô tả công khai hợp lệ, cho thử xử lý lại; ảnh gốc không hiển thị công khai hoặc được dùng tạo vector ảnh tìm kiếm.

<!-- pagebreak -->

## 4 Tìm kiếm và xem kết quả

**Chức năng:** F02 và F03. **Tác nhân:** người tìm. **Kết quả:** danh sách gợi ý kèm nơi giữ và bước nhận phù hợp.

### Luồng chính

1. Người tìm thêm ảnh nếu có hoặc nhập mô tả tiếng Việt về các đặc điểm còn nhớ.
2. Người tìm cung cấp khu vực, ngày và khoảng giờ làm mất.
3. Hệ thống tìm món đồ phù hợp. MVP đề xuất kiểm tra điều kiện đầu vào và chỉ tìm trong các bài đăng còn hiệu lực.
4. Hệ thống hiển thị các món được gợi ý với ảnh, mô tả, thông tin nhặt được và nơi đang giữ.
5. Người tìm mở chi tiết và tiếp tục theo một trong ba nhánh nhận đồ.

Ví dụ đầu vào trong demo là “Ví đen, khóa kéo vàng, không có dây đeo”, khu vực Công viên Bờ Sông, ngày 13/10/2026 và khoảng giờ 16:30 đến 17:30. Đây là dữ liệu minh họa.

### Quy tắc tìm kiếm

- Ảnh không bắt buộc. Khi không có ảnh, mô tả phải đủ để thực hiện tìm kiếm.
- MVP đề xuất yêu cầu có ít nhất một trong hai dữ liệu: ảnh hợp lệ hoặc mô tả không rỗng.
- Khi cung cấp cả ảnh và mô tả, MVP cho chọn Tìm theo ảnh hoặc Tìm theo mô tả. Việc trộn điểm giữa hai chế độ cần được đánh giá trước khi bổ sung.
- Khu vực, ngày và khoảng giờ được sử dụng để thu hẹp hoặc hỗ trợ xếp hạng. Cách mở rộng phạm vi phải hiển thị cho người dùng, không âm thầm loại toàn bộ kết quả vì thời gian chỉ là ước lượng.
- Các cách gọi như “ví” và “bóp” là tình huống cần kiểm thử; chưa coi khả năng hiểu đồng nghĩa là kết quả đã được chứng minh.

| Nơi đang giữ | Thông tin cần hiển thị | Hành động tiếp theo |
| --- | --- | --- |
| Cá nhân | Thông tin món đồ và trạng thái có thể yêu cầu | Gửi yêu cầu nhận đồ |
| Điểm tiếp nhận | Tên điểm, địa chỉ, hướng dẫn và trạng thái giữ | Xem đường đi, đến xác minh |
| Nơi ngoài hệ thống | Tên nơi, địa chỉ và hướng dẫn đã ghi | Liên hệ hoặc đến theo hướng dẫn |

### Xử lý không có kết quả đề xuất cho MVP

Hệ thống cho biết chưa tìm thấy món phù hợp và cho phép sửa mô tả, đổi ảnh hoặc mở rộng khu vực, thời gian. Không tạo kết quả giả. Nếu mô hình tìm kiếm lỗi, thông báo rõ và cho phép xem danh sách theo bộ lọc cơ bản.

<!-- pagebreak -->

## 5 Yêu cầu nhận đồ và nhắn tin

**Chức năng:** F04, F05 và F06. **Điều kiện:** món đồ hiện do cá nhân giữ và còn có thể nhận lại. Luồng này không áp dụng mặc định cho đồ đang ở điểm tiếp nhận hoặc nơi ngoài hệ thống.

### Gửi và xét duyệt yêu cầu

1. Người tìm mở chi tiết món đồ và chọn Gửi yêu cầu nhận đồ.
2. Hệ thống hiển thị câu hỏi xác minh nếu có. Demo cho phép từ 0 đến 3 câu hỏi; không có câu hỏi vẫn gửi được yêu cầu.
3. Người tìm gửi câu trả lời và yêu cầu. Hệ thống lưu trạng thái Chờ xét duyệt.
4. Người giữ xem yêu cầu và các câu trả lời đã gửi.
5. Người giữ chọn Phê duyệt hoặc Từ chối. Hệ thống lưu quyết định và cập nhật trạng thái.
6. Khi được phê duyệt, hai bên có quyền mở hội thoại để thỏa thuận thời gian, địa điểm và cách trao trả.

MVP đề xuất yêu cầu trả lời các câu hỏi đã được người giữ thiết lập. Quy tắc này cần được xác nhận vì demo chỉ xác nhận việc có câu hỏi là tùy chọn.

### Điều kiện mở chat

| Trạng thái yêu cầu | Người tìm và người giữ | Người không thuộc yêu cầu |
| --- | --- | --- |
| Chờ xét duyệt | Chưa được mở hoặc gửi tin | Không được truy cập |
| Đã phê duyệt | Được đọc và gửi tin trong hội thoại tương ứng | Không được truy cập |
| Bị từ chối | Chưa mở kết nối | Không được truy cập |

Quyền chat phải được kiểm tra tại backend khi kết nối, đọc và gửi tin nhắn. Việc ẩn nút trên giao diện không đủ để thực thi quy tắc này.

### Bàn giao và ngoại lệ

Demo minh họa việc hẹn nhận lúc 18:00 qua tin nhắn. MVP sử dụng hội thoại để thỏa thuận; chưa đặc tả lịch hẹn riêng, đính kèm hoặc chia sẻ vị trí trong chat.

Để kết thúc vòng đời món đồ, MVP đề xuất người giữ ghi nhận đã trao trả và thời điểm bàn giao. Một yêu cầu được duyệt chưa có nghĩa món đồ đã được trả. Hệ thống phải ngăn thao tác bàn giao lần thứ hai. Cách chọn giữa nhiều người cùng yêu cầu, rút yêu cầu và thu hồi phê duyệt cần được chốt trước triển khai.

<!-- pagebreak -->

## 6 Điểm tiếp nhận và nơi ngoài hệ thống

**Chức năng:** F07, F08 và F09. Hai loại nơi giữ này cung cấp hướng dẫn đến nhận trực tiếp; không mặc định mở chat giữa người tìm và người đã đăng tin.

### Chuyển đồ vào điểm tiếp nhận

Demo xác nhận quy tắc: khi còn chờ điểm duyệt tiếp nhận, nơi đang giữ chưa thay đổi. Luồng hoàn chỉnh sau đây là đề xuất MVP nhằm bảo đảm thông tin trên ứng dụng khớp với bàn giao thực tế.

1. Người giữ chọn điểm tiếp nhận và gửi yêu cầu chuyển món đồ đến điểm.
2. Hệ thống tạo yêu cầu Chờ tiếp nhận; món đồ vẫn thuộc nơi giữ hiện tại.
3. Nhân viên điểm kiểm tra yêu cầu và món đồ được bàn giao thực tế.
4. Chỉ khi nhân viên xác nhận đã tiếp nhận thực tế, hệ thống mới đổi nơi giữ sang điểm và ghi lịch sử.
5. Nếu điểm từ chối hoặc yêu cầu còn chờ, hệ thống giữ nguyên nơi giữ hiện tại.

Việc điểm đồng ý trước về mặt thủ tục không tự xác nhận đã cầm giữ đồ. Cách tổ chức bước đồng ý trước cần được nhóm dự án chốt nếu có sử dụng.

### Nhận lại đồ tại điểm

1. Người tìm xem mã món đồ, ảnh, tên điểm, địa chỉ và hướng dẫn nhận.
2. Người tìm chọn Xem đường đi; MVP đề xuất mở liên kết chỉ đường bằng địa chỉ.
3. Người tìm đến quầy và cung cấp thông tin để nhân viên xác minh trực tiếp.
4. Nếu đủ căn cứ, nhân viên trao đồ và ghi nhận đã bàn giao.
5. MVP đề xuất cập nhật trạng thái, lưu người thực hiện và thời điểm, ngừng hiển thị món đồ trong danh sách có thể nhận.

Nếu xác minh không đạt, không ghi nhận bàn giao. Bộ bằng chứng cần xuất trình và cách xử lý tranh chấp là quy trình vận hành cần xác nhận, không được suy ra từ điểm tương đồng tìm kiếm.

### Nhận lại đồ tại nơi ngoài hệ thống

Người tìm xem tên nơi giữ, địa chỉ và hướng dẫn do người đăng cung cấp, sau đó liên hệ hoặc đến nhận theo hướng dẫn. Ứng dụng không mặc định có quyền duyệt hay xác nhận thay cho nơi đó. MVP đề xuất người đăng cập nhật tình trạng sau khi có thông tin bàn giao; không tự động đánh dấu đã trả chỉ vì người tìm mở chỉ đường.

<!-- pagebreak -->

## 7 Quy tắc và trạng thái nghiệp vụ

### Sơ đồ nhận lại đồ

![Luồng nhận lại đồ theo nơi giữ](assets/luong-nhan-lai-do.png)

### Quy tắc bắt buộc theo demo

- **BR01:** người mất được tìm bằng mô tả khi không có ảnh.
- **BR02:** cách nhận tiếp theo được xác định bằng nơi đang giữ hiện tại.
- **BR03:** có từ 0 đến 3 câu hỏi xác minh tùy chọn; 0 câu hỏi vẫn gửi yêu cầu được.
- **BR04:** yêu cầu do cá nhân giữ phải được phê duyệt trước khi mở chat; từ chối chưa mở kết nối.
- **BR05:** chờ điểm duyệt tiếp nhận không làm thay đổi nơi giữ hiện tại.
- **BR06:** đồ tại điểm được xác minh và trao trả trực tiếp; điểm ghi nhận đã bàn giao.

### Mô hình trạng thái đề xuất

| Đối tượng | Trạng thái và chuyển đổi | Điều kiện chính |
| --- | --- | --- |
| Yêu cầu nhận | Chờ xét duyệt → Đã phê duyệt hoặc Bị từ chối | Người đang giữ có quyền quyết định |
| Chuyển vào điểm | Chờ tiếp nhận → Đã tiếp nhận hoặc Bị từ chối | Chỉ đổi nơi giữ khi đã nhận thực tế |
| Món đồ | Đang giữ → Đã trao trả | Phải có người có quyền xác nhận bàn giao |

Các trạng thái là mô hình đề xuất để triển khai. Trạng thái yêu cầu, trạng thái tiếp nhận và trạng thái món đồ được lưu riêng để tránh hiểu “đã duyệt” thành “đã trả”. Loại nơi giữ là một thuộc tính riêng của món đồ.

**Bất biến MVP đề xuất:** mỗi món đồ chỉ có một nơi giữ hiện tại và chỉ có một lần bàn giao hoàn tất. Các cập nhật nơi giữ, trạng thái và lịch sử liên quan phải được lưu trong cùng một giao dịch dữ liệu.

<!-- pagebreak -->

## 8 Dữ liệu và quyền truy cập

Mô hình dưới đây là thiết kế logic đề xuất cho MVP, không phải cấu trúc cơ sở dữ liệu đã có của demo.

| Thực thể | Thuộc tính chính | Quan hệ |
| --- | --- | --- |
| Tài khoản | Mã, tên hiển thị, issuer và subject của OIDC | Có nhiều bài đăng và yêu cầu; không tự lưu mật khẩu trong thiết kế đề xuất |
| Món đồ | Mã, mô tả, nơi nhặt, thời điểm, loại nơi giữ, nơi giữ hiện tại, trạng thái | Có ảnh, câu hỏi và yêu cầu |
| Đối tượng R2 | Bucket/key, chủ sở hữu, MIME, byte/pixel, SHA-256, trạng thái upload/xóa | Đăng ký bền vững trước upload; ảnh tham chiếu object gốc và bản sạch |
| Ảnh | Mã món đồ, object gốc/bản sạch, thứ tự, phiên bản, trạng thái xử lý/duyệt | Thuộc một món đồ; chỉ bản sạch được duyệt được hiển thị |
| Điểm tiếp nhận | Mã, tên, địa chỉ, hướng dẫn | Có nhân viên và đồ đang giữ |
| Phân công tại điểm | Tài khoản, điểm, quyền | Giới hạn phạm vi thao tác nhân viên |
| Câu hỏi xác minh | Mã món đồ, nội dung, thứ tự | Tối đa 3 câu mỗi món |
| Yêu cầu nhận | Món đồ, người yêu cầu, câu trả lời, trạng thái, người duyệt, thời điểm | Có tối đa một hội thoại cho một yêu cầu được duyệt |
| Hội thoại và tin nhắn | Yêu cầu, người gửi, nội dung, thời điểm | Chỉ hai bên được phép truy cập |
| Yêu cầu tiếp nhận | Món đồ, nơi giữ cũ, điểm đích, trạng thái | Không thay nơi giữ trong lúc chờ |
| Lịch sử bàn giao | Món đồ, nơi giao và nhận, người xác nhận, thời điểm | Ghi nhận thay đổi nơi giữ hoặc hoàn tất trả |
| Hồ sơ mô hình và vector | Tên/revision Qwen, profile tiền xử lý/prompt, 2048 chiều, phiên bản nguồn | Vector văn bản công khai hoặc ảnh sạch đã duyệt; giữ riêng loại nguồn |
| Tác vụ nền | Loại xử lý, đối tượng nguồn, phiên bản, trạng thái, lease và retry | Xử lý ảnh, tạo vector và dọn object R2 bền vững |

Thiết kế chi tiết gồm [từ điển dữ liệu và các ràng buộc](database-design.md), [DDL PostgreSQL](database-schema.sql) và [ERD chỉnh sửa bằng draw.io](findie-erd.drawio). Đây là thiết kế cho ứng dụng mới, chưa áp dụng lên cơ sở dữ liệu thật. DDL quy định tên bảng, khóa chính/ngoại, unique/check và chỉ mục; ERD dùng để rà soát quan hệ.

### Phân loại thông tin

Thông tin công khai gồm bản ảnh sạch đã xử lý và được duyệt, mô tả công khai, khu vực nhặt, thời điểm, trạng thái và hướng dẫn nơi nhận. Không công khai địa chỉ nhà của cá nhân, nội dung chat hoặc câu trả lời xác minh. Câu trả lời chỉ được chia sẻ với người yêu cầu và người có quyền xét duyệt; không đưa vào vector tìm kiếm công khai.

Người dùng chỉ được sửa bài đăng, đọc yêu cầu và hội thoại thuộc phạm vi quyền của mình. Nhân viên điểm chỉ được xác nhận đồ tại điểm được phân công. Quyền nhân viên phải do hệ thống cấp, không lấy từ giá trị người dùng tự gửi lên.

### Tính nhất quán

Backend kiểm tra quyền và trạng thái hiện tại trước mỗi thao tác duyệt, tiếp nhận hoặc trả đồ. Dùng giao dịch và kiểm tra phiên bản hoặc khóa bản ghi khi cần để ngăn hai thao tác đồng thời ghi nhận hai nơi giữ hay hai lần trả. Khi mô tả hoặc ảnh thay đổi, phải cập nhật hoặc vô hiệu hóa vector cũ. Thay ảnh gốc, vùng che hoặc bản sạch phải tăng phiên bản và hủy hiệu lực phê duyệt cũ; worker chỉ được ghi kết quả khớp phiên bản hiện tại. R2 và PostgreSQL không chung giao dịch: giữ công việc xóa/dọn tệp có retry, thu hồi hiển thị trước khi xóa object, không coi upload thành công là bài đăng đã lưu thành công.

<!-- pagebreak -->

## 9 Công nghệ và kiến trúc hệ thống

Bộ nền tảng đã chọn gồm React, .NET, Python/FastAPI, PostgreSQL và Cloudflare R2. Qwen và OpenCV được bổ sung theo yêu cầu. Bảng dưới là danh mục công nghệ dùng cho thiết kế MVP; các thư viện, mã mô hình và cách triển khai cụ thể vẫn cần kiểm thử tương thích và ghim phiên bản trước xây dựng. Chưa có cam kết chất lượng hoặc chi phí.

| Thành phần | Công nghệ dự kiến | Vai trò |
| --- | --- | --- |
| Giao diện | React, TypeScript, Vite, HTML/CSS | Web responsive, biểu mẫu dễ tiếp cận [T1] |
| Giao tiếp trình duyệt | Fetch API, HTTPS/JSON, @microsoft/signalr | Gọi API và nhận sự kiện chat |
| API nghiệp vụ | C#, .NET, ASP.NET Core Web API | Xác thực, quyền, bài đăng, nhận đồ, tiếp nhận và trả đồ [T2] |
| Đăng nhập | ASP.NET Core OpenID Connect và Cookie Authentication | Đề xuất OIDC với phiên cookie; DB lưu issuer/subject; nhà cung cấp còn chờ chọn |
| Dữ liệu | PostgreSQL, SQL | Lưu nghiệp vụ, lịch sử, tin nhắn, tác vụ nền và metadata ảnh |
| Truy cập dữ liệu | Entity Framework Core, Npgsql, migrations | Giao dịch, kiểm soát đồng thời và quản lý lược đồ [T4] |
| Vector | pgvector, Pgvector.EntityFrameworkCore | vector(2048), exact cosine search; chưa tạo ANN index [T5] |
| AI service | Python, FastAPI, Uvicorn, Pydantic, python-multipart | API nội bộ, kiểm tra input/output [T3] |
| Inference | PyTorch, Transformers, Accelerate, qwen-vl-utils | Nạp hai mô hình Qwen; dùng mã inference chính thức được rà soát và ghim revision |
| Tìm kiếm text/ảnh | Qwen/Qwen3-VL-Embedding-2B | Một model chung cho text và ảnh, baseline 2048 chiều [T6] |
| Gợi ý vùng nhạy cảm | Qwen/Qwen3-VL-4B-Instruct | Bản Instruct 4B đã chọn; gợi ý vùng cần che/mờ từ OCR/định vị, không tự kết luận an toàn [T7] |
| Xử lý pixel | OpenCV (opencv-python-headless), NumPy, Pillow | GaussianBlur, che vùng chữ/mã; chuẩn hóa hướng ảnh và xuất bản sạch [T9] |
| Kho ảnh | Cloudflare R2, S3 API, AWSSDK.S3 | Lưu gốc riêng tư và bản sạch; .NET kiểm soát truy cập [T10] |
| Tác vụ nền | BackgroundService, HttpClient của .NET; PostgreSQL | Xử lý ảnh, embedding và xóa tệp; retry/lease bền vững |
| Chat | ASP.NET Core SignalR | Lưu tin nhắn trước khi phát; kiểm tra quyền từng thao tác [T8] |
| Chỉ đường | Liên kết bản đồ | Mở địa chỉ có sẵn, chưa cần Maps SDK |
| Vận hành | Git, Docker, Docker Compose, HTTPS | Môi trường demo tái lập; mạng nội bộ, logging/health check sẵn có |
| Kiểm thử | xUnit, ASP.NET Core integration testing, pytest, Playwright | API/DB, xử lý ảnh/AI và hành trình web |
| Thiết kế dữ liệu | SQL, diagrams.net/draw.io | DDL và ERD chỉnh sửa được |

Hai model card Qwen công bố giấy phép Apache-2.0 [T6, T7]. Tên model không đủ để tái lập: cần ghim commit trọng số, mã inference, processor, prompt và phiên bản gói. Chưa cần Redis, Kafka, Elasticsearch, vector database riêng hoặc model reranker trong MVP.

### Kiến trúc triển khai

![Phân vai React NET FastAPI và PostgreSQL](assets/kien-truc-he-thong.png)

React gọi API .NET qua HTTPS và nhận sự kiện chat qua SignalR. .NET kiểm tra phiên, quyền và nghiệp vụ, đọc ghi PostgreSQL, lưu/lấy ảnh ở R2 và gọi FastAPI nội bộ. FastAPI chạy Qwen để tạo vector hoặc gợi ý vùng nhạy cảm, OpenCV tạo bản che/mờ; .NET kiểm soát bước duyệt và dùng pgvector tìm bài đăng hợp lệ.

MVP có một frontend, một backend .NET gồm tác vụ nền, một AI service, một PostgreSQL và Cloudflare R2. AI service không sở hữu luồng duyệt, quyền chat hay quyết định bàn giao; không có credential DB/R2. Backend chuyển dữ liệu đã kiểm tra đến AI, không cho dịch vụ tự tải URL do người dùng cung cấp. Chặn truy cập công khai tới AI service, kiểm tra yêu cầu giữa hai dịch vụ và đặt thời gian chờ. Chuỗi kết nối DB, khóa dịch vụ chỉ nằm ở phía máy chủ. Chạy một instance .NET cho demo; mở rộng nhiều instance cần thiết kế phân phối sự kiện SignalR tương ứng.

<!-- pagebreak -->

## 10 Tìm kiếm thông minh và yêu cầu chất lượng

### Lưu ảnh R2 và xử lý riêng tư

Ảnh tải lên đi qua .NET để kiểm tra quyền, nội dung thực, dung lượng và kích thước sau giải mã. R2 dùng bucket private theo môi trường, tắt public r2.dev/custom domain; prefix original, sanitized và temporary chỉ để tổ chức dữ liệu, không thay cho phân quyền. PostgreSQL giữ tham chiếu object, không giữ bytes hoặc signed URL. SDK và credential R2 chỉ ở máy chủ [T10].

.NET đăng ký key/chủ sở hữu/trạng thái trong stored_objects trước upload; tải ảnh gốc riêng tư lên R2 ngoài giao dịch, rồi hoàn tất metadata, liên kết ảnh và công việc xử lý trong giao dịch ngắn. Bản đăng ký còn dở hỗ trợ retry/dọn tệp an toàn. Sau đó gọi FastAPI ngoài giao dịch DB. Qwen3-VL-4B-Instruct gợi ý vùng khuôn mặt, giấy tờ, thẻ, điện thoại, địa chỉ hoặc QR/barcode nhạy cảm. Output phải qua kiểm tra JSON, tọa độ và kích thước/hướng ảnh. OpenCV dùng GaussianBlur cho vùng cần làm mờ; chữ, số định danh hoặc mã vẫn có thể đọc được phải che kín. Xuất lại từ pixel đã xử lý và loại EXIF/GPS, metadata không cần thiết.

Người có quyền duyệt ảnh xem trước, bổ sung vùng còn sót và duyệt đúng phiên bản bản sạch. Chính sách cấp quyền duyệt, gồm việc người đăng có được tự duyệt hay không, phải chốt trước triển khai. Chỉ bản đã duyệt được dùng công khai và tạo vector ảnh. Model không phát hiện vùng nhạy cảm vẫn cần duyệt; lỗi hoặc chưa duyệt phải giữ ảnh gốc riêng tư và dùng placeholder. Đây là thiết kế giảm lộ dữ liệu, chưa có bằng chứng đạt mức che/mờ bảo đảm; cần bộ ảnh đánh giá.

API phục vụ bản sạch sau kiểm tra trạng thái bài đăng và quyền hiện tại. Ảnh gốc chỉ qua endpoint riêng có quyền cho người đăng/người xử lý được ủy quyền; không trả khóa/URL gốc công khai và không cache response riêng tư. MVP chưa cần presigned URL; nếu bổ sung, chỉ cấp thời hạn ngắn cho bản sạch, vì người giữ URL có thể dùng đến khi hết hạn [T11]. Xóa/gỡ ảnh phải thu hồi hiển thị và vector trước, retry xóa R2 sau; có tác vụ dọn object mồ côi với khoảng chờ để tránh xóa nhầm upload chưa hoàn tất.

### Xử lý tìm kiếm

**Khi đăng tin:** lưu bài đăng, metadata và tác vụ bền vững. Mô tả công khai có thể tạo vector độc lập trong lúc ảnh đang xử lý; ảnh chỉ tạo vector từ bản sạch đã duyệt. Khi AI lỗi, giữ bài đăng và trạng thái chờ/lỗi rõ ràng, có retry; không công khai ảnh gốc để thay thế.

**Tìm theo mô tả:** dùng Qwen3-VL-Embedding-2B mã hóa mô tả tiếng Việt và so với vector văn bản công khai. **Tìm theo ảnh:** dùng cùng model mã hóa ảnh truy vấn tạm và so với vector ảnh sạch. Baseline giữ hai chế độ riêng; dù model hỗ trợ không gian chung, chưa tự trộn điểm hoặc bật text–image cross-search trước đánh giá [T6].

Vector chuẩn hóa L2, 2048 chiều, lưu cùng tên/revision model, profile prompt/tiền xử lý và phiên bản nguồn. Chỉ so sánh cùng profile tương thích; cùng số chiều chưa đủ. Điểm cosine là điểm tương đồng, không phải xác suất đúng chủ. Dùng exact cosine search trong pgvector sau bộ lọc; vector(2048) vượt giới hạn 2000 chiều của ANN index trên kiểu vector, nên không tạo HNSW/IVFFlat ở MVP. Nếu cần tối ưu, đo phương án halfvec hoặc MRL ít chiều hơn trước đổi và lập chỉ mục lại [T5].

.NET kiểm tra giá trị hữu hạn, vector khác không, model/profile và phiên bản nguồn trước khi lưu kết quả; không giữ giao dịch DB lúc gọi AI. Kết quả từ nội dung cũ không được ghi đè dữ liệu hiện tại. Ảnh tìm kiếm chỉ xử lý tạm trong bộ nhớ; nếu ghi R2 temporary thì xóa ngay sau xử lý/lỗi và có lifecycle dự phòng. Không lưu ảnh truy vấn vào bài đăng hoặc vector bền vững.

### Yêu cầu chất lượng đề xuất

| Mã | Yêu cầu | Cách xác nhận |
| --- | --- | --- |
| NFR01 | Giao diện dùng được trên điện thoại và bàn phím | Kiểm tra form có nhãn, focus rõ, lỗi đọc được, không dựa riêng vào màu |
| NFR02 | Bảo vệ dữ liệu riêng tư | Thử truy cập yêu cầu, ảnh riêng và chat bằng tài khoản khác; phải bị từ chối |
| NFR03 | Không mất hoặc nhân đôi thao tác nghiệp vụ | Gửi lại yêu cầu và thao tác đồng thời không tạo hai lần bàn giao |
| NFR04 | Có thông báo lỗi và giữ dữ liệu nhập | Mô phỏng lỗi mạng khi tải ảnh, gửi yêu cầu và gửi tin |
| NFR05 | Theo dõi và khôi phục dữ liệu | Có log lỗi và thay đổi trạng thái; thử khôi phục một bản sao lưu trước thử nghiệm thật |
| NFR06 | Đo hiệu năng trước cam kết | Đo độ trễ tìm kiếm và chat trên hạ tầng được chọn; chưa ấn định SLA |

### Kiểm soát ở ranh giới hệ thống

Kiểm tra nội dung tệp ngoài phần mở rộng, dung lượng, kích thước ảnh và quyền tải lên. Áp dụng giới hạn tần suất đăng tin, gửi yêu cầu và tin nhắn để tránh lạm dụng. Nhật ký không ghi mật khẩu, token hoặc toàn bộ câu trả lời xác minh. Các mốc ngày giờ hiển thị theo Asia/Ho_Chi_Minh; thời gian sự kiện hệ thống được lưu nhất quán để tránh nhầm múi giờ.

<!-- pagebreak -->

## 11 Tiêu chí nghiệm thu

Đây là các tình huống cần kiểm thử sau triển khai, không phải kết quả kiểm thử của demo. Nhóm “Demo” đối chiếu hành vi trong tư liệu; nhóm “MVP” kiểm tra các ràng buộc bổ sung được đề xuất.

| Mã | Nhóm | Tình huống | Kết quả mong đợi |
| --- | --- | --- | --- |
| AC01 | Demo | Chọn ảnh khi đăng đồ nhặt được | Có ảnh xem trước trước khi đăng |
| AC02 | Demo | Đăng với mô tả, nơi nhặt, thời điểm và nơi giữ | Bài đăng thể hiện đúng thông tin đã nhập |
| AC03 | Demo | Tìm bằng mô tả, không có ảnh | Thực hiện được tìm kiếm |
| AC04 | Demo | Tìm bằng ảnh kèm khu vực và thời gian | Có gợi ý và nơi đang giữ của từng món |
| AC05 | Demo | Mở món đồ ở từng loại nơi giữ | Có đúng nhánh yêu cầu cá nhân, nhận tại điểm hoặc hướng dẫn ngoài hệ thống |
| AC06 | Demo | Gửi yêu cầu khi có 0 câu hỏi hoặc 1 đến 3 câu hỏi | Không bị bắt buộc phải có câu hỏi để gửi |
| AC07 | Demo | Người giữ xét yêu cầu | Xem được câu trả lời, phê duyệt hoặc từ chối được |
| AC08 | Demo | Kiểm tra ba yêu cầu độc lập đang chờ, bị từ chối và đã duyệt | Chỉ yêu cầu đã duyệt có quyền chat |
| AC09 | Demo | Mở món đồ ở điểm tiếp nhận | Xem được tên điểm, địa chỉ, hướng dẫn và đường đi |
| AC10 | Demo | Yêu cầu tiếp nhận còn chờ | Nơi đang giữ không thay đổi |
| AC11 | Demo | Nhân viên xác minh và bàn giao tại điểm | Ghi nhận được việc bàn giao |
| AC12 | MVP | Tìm với cả ảnh và mô tả đều rỗng | Báo cần nhập ít nhất một dữ liệu tìm kiếm |
| AC13 | MVP | Tải tệp sai định dạng hoặc quá giới hạn | Từ chối tệp, giữ dữ liệu form |
| AC14 | MVP | Gọi API chat trực tiếp khi chưa được duyệt hoặc từ tài khoản khác | Backend từ chối dù bỏ qua giao diện |
| AC15 | MVP | Điểm từ chối tiếp nhận; sau đó điểm khác nhận thực tế | Giữ nguyên nơi cũ khi từ chối; đổi đúng nơi khi nhận thực tế |
| AC16 | MVP | Hai người cùng xác nhận trả một món | Chỉ một lần trả được ghi nhận |
| AC17 | MVP | Mạng lỗi khi gửi thao tác | Có thông báo; gửi lại không nhân đôi dữ liệu |
| AC18 | MVP | AI lỗi hoặc không có kết quả phù hợp | Báo đúng tình trạng, cho sửa điều kiện hoặc xem danh sách cơ bản |
| AC19 | MVP mới | Truy cập object ảnh gốc bằng URL công khai hoặc API không có quyền | Bị từ chối; DTO công khai không lộ key/URL gốc |
| AC20 | MVP mới | Ảnh có giấy tờ, mặt người, số hoặc mã nhạy cảm | Qwen gợi ý vùng, OpenCV che/mờ; người dùng kiểm tra rồi mới công khai bản sạch |
| AC21 | MVP mới | AI/OpenCV lỗi, JSON sai hoặc ảnh chưa duyệt | Ảnh gốc vẫn riêng tư; hiện placeholder; mô tả hợp lệ vẫn lưu và tìm được khi có vector |
| AC22 | MVP mới | Kiểm tra ảnh sạch và thay ảnh sau duyệt | Không còn EXIF/GPS; bản mới phải duyệt lại; vector/kết quả worker cũ không có hiệu lực |
| AC23 | MVP mới | Query ảnh lỗi, upload dở hoặc xóa bài lúc R2 lỗi | Dọn tệp tạm/mồ côi; thu hồi hiển thị trước, retry xóa mà không mất bản ghi công việc |
| AC24 | MVP mới | Sai model revision/profile, số chiều hoặc dùng ảnh chưa duyệt để embedding | Backend từ chối kết quả; chỉ index bản sạch đúng phiên bản và vector 2048 chiều hợp lệ |

Đánh giá AI cần bộ truy vấn tiếng Việt có nhãn và các ảnh cùng món ở góc chụp khác nhau. Bộ kiểm tra riêng tư cần vùng nhạy cảm có nhãn, đo mức bỏ sót và khả năng còn đọc được sau che/mờ; thử model không phát hiện gì, ảnh xoay và vùng nhỏ. Theo dõi khả năng tìm đúng trong nhóm kết quả đầu, đồng thời thử đồ khác nhưng cùng màu hoặc cùng kiểu. Chỉ chốt mục tiêu định lượng sau khi có dữ liệu và hạ tầng thử nghiệm.

<!-- pagebreak -->

## 12 Các quyết định cần chốt và tài liệu tham chiếu

### Quyết định sản phẩm

1. **Định danh:** cách đăng nhập, quyền xem tin khi chưa đăng nhập và cách cấp quyền nhân viên điểm.
2. **Xác minh:** ai tạo câu hỏi, có bắt buộc trả lời câu đã tạo hay không và bằng chứng cần xuất trình tại điểm.
3. **Nhiều yêu cầu:** có cho duyệt nhiều người cùng lúc, cách rút hoặc thu hồi yêu cầu, cách đóng yêu cầu sau trả.
4. **Nơi giữ:** cách xử lý điểm đồng ý trước nhưng chưa nhận thực tế; ai cập nhật khi đồ gửi ngoài hệ thống đã trả.
5. **Dữ liệu và vận hành:** thời hạn lưu ảnh gốc/bản sạch/tệp tạm, câu trả lời, chat; quyền duyệt ảnh, cách sửa/gỡ và xóa backup; đầu mối xử lý tranh chấp.
6. **Tìm kiếm:** độ rộng bộ lọc thời gian, cách dùng ảnh cùng mô tả, bộ dữ liệu đánh giá và mục tiêu chất lượng.
7. **Công nghệ:** R2 đã chốt; cần xác nhận các mã Qwen đề xuất sau benchmark, ghim revision/profile và phiên bản gói/runtime; chọn nhà cung cấp OIDC, CPU/GPU, cấu hình bucket/retention và ngân sách sau đo thử.

Các nội dung trên là điểm cần quyết định, không phải chức năng đã được xác nhận trong demo. Đăng ký điểm tiếp nhận, dashboard quản trị đầy đủ, thông báo đẩy, thanh toán, giao vận và tích hợp mạng xã hội nằm ngoài phạm vi đặc tả MVP này.

### Tư liệu sản phẩm

- **S1:** [TOM_TAT_FINDIE.txt](demo/findie-dang-bai/TOM_TAT_FINDIE.txt), mô tả vấn đề, mục tiêu, ba luồng và trạng thái demo.
- **S2:** [01-dang-do-nhat-duoc.png](demo/findie-dang-bai/01-dang-do-nhat-duoc.png), luồng đăng ảnh và ba lựa chọn nơi giữ.
- **S3:** [02-tim-do-that-lac.png](demo/findie-dang-bai/02-tim-do-that-lac.png), tìm bằng ảnh hoặc mô tả, khu vực, ngày và khoảng giờ.
- **S4:** [03-yeu-cau-va-hen-trao-tra.png](demo/findie-dang-bai/03-yeu-cau-va-hen-trao-tra.png), 0 đến 3 câu hỏi, duyệt yêu cầu và mở chat.
- **S5:** [04-nhan-tai-diem-tiep-nhan.png](demo/findie-dang-bai/04-nhan-tai-diem-tiep-nhan.png), nhận trực tiếp, trạng thái chờ tiếp nhận và hướng dẫn ngoài hệ thống.

Các tư liệu S1 đến S5 nằm trong thư mục [docs/demo/findie-dang-bai](demo/findie-dang-bai) của dự án. Chúng mô tả ý tưởng sản phẩm, không cung cấp bằng chứng về công nghệ triển khai.

### Tài liệu công nghệ chính thức

- **T1:** [React với TypeScript](https://react.dev/learn/typescript) và [Vite](https://vite.dev/guide/).
- **T2:** [ASP.NET Core Web API](https://learn.microsoft.com/en-us/aspnet/core/web-api/).
- **T3:** [FastAPI nhận tệp](https://fastapi.tiangolo.com/tutorial/request-files/).
- **T4:** [Npgsql EF Core](https://www.npgsql.org/efcore/).
- **T5:** [pgvector](https://github.com/pgvector/pgvector) và [pgvector cho .NET](https://github.com/pgvector/pgvector-dotnet).
- **T6:** [Qwen3-VL-Embedding-2B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B), model card chính thức cho embedding text/ảnh và 2048 chiều.
- **T7:** [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), model card chính thức cho OCR và định vị vùng.
- **T8:** [ASP.NET Core SignalR](https://learn.microsoft.com/en-us/aspnet/core/signalr/introduction).

- **T9:** [OpenCV Image Smoothing](https://docs.opencv.org/4.x/d4/d13/tutorial_py_filtering.html), phép GaussianBlur.
- **T10:** [R2 với AWS SDK for .NET](https://developers.cloudflare.com/r2/examples/aws/aws-sdk-net/) và [quyền công khai của bucket](https://developers.cloudflare.com/r2/buckets/public-buckets/).
- **T11:** [R2 presigned URL](https://developers.cloudflare.com/r2/api/s3/presigned-urls/) và [object lifecycle](https://developers.cloudflare.com/r2/buckets/object-lifecycles/).

Nguồn R2, Qwen Embedding, OpenCV và giới hạn pgvector được đối chiếu ngày 21/10/2026; model card Qwen3-VL-4B-Instruct được đối chiếu ngày 22/10/2026; các nguồn nền tảng còn lại từ bản đặc tả ngày 20/10/2026. Tài liệu mô tả khả năng của thành phần, không thay cho kiểm thử tích hợp, benchmark hoặc xác nhận chi phí thực tế. Chi tiết kỹ thuật nằm trong [kiến trúc hệ thống](system-architecture.md).
