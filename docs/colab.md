# Thử nghiệm AI Findie trên Google Colab Free

Hai notebook độc lập, mở bằng **File → Upload notebook** tại [Google Colab](https://colab.research.google.com/).
Không cần clone project, chạy Docker hoặc cài model lên máy phát triển.

1. Mở [01_qwen_embedding.ipynb](../notebooks/colab/01_qwen_embedding.ipynb), chọn **Runtime → Change runtime type → T4 GPU**. Chạy cell từ trên xuống: cài gói, kiểm GPU, tải model, thử mô tả tiếng Việt, thử ảnh, xuất ZIP, dọn GPU.
2. Tải kết quả bằng cách đặt `DOWNLOAD_RESULTS = True` và chạy lại cell xuất. Mặc định tệp nằm trong `/content`; xem/tải qua bảng Files của Colab cũng được.
3. **Disconnect and delete runtime**, mở [02_qwen_redaction.ipynb](../notebooks/colab/02_qwen_redaction.ipynb) trong runtime GPU sạch. Chạy lần lượt, xem vùng model gợi ý, thêm `MANUAL_REGIONS` còn thiếu rồi chạy lại cell tạo bản nháp/xuất. Notebook giữ trạng thái `requires_human_review`; không tự duyệt công khai.

Notebook 01 tạo vector L2 2048 chiều, xếp hạng cosine riêng cho **văn bản → văn bản** và **ảnh → ảnh**. Hai chế độ không cộng điểm. Ảnh đồ vật tự vẽ chỉ dùng để kiểm luồng; chưa có bộ dữ liệu có nhãn để kết luận chất lượng tiếng Việt, ngưỡng cosine hoặc độ chính xác tìm kiếm.

Notebook 02 dùng `Qwen/Qwen3-VL-4B-Instruct`, NF4 4-bit, FP16 và SDPA để giảm bộ nhớ; giới hạn một ảnh, pixel và token. Vùng là `[x1,y1,x2,y2]` tương đối **0–1000**, áp lên ảnh đã sửa hướng/chuẩn hóa. OpenCV che kín chữ/số/mã; khuôn mặt mặc định che kín, có tùy chọn GaussianBlur. Kết quả rỗng cũng cần người xem lại toàn ảnh. Blur và phát hiện tự động không bảo đảm ẩn danh.

Chỉ dùng dữ liệu giả lập hoặc không nhạy cảm. Các cell tự tạo dữ liệu demo để chạy ngay; đặt `UPLOAD_IMAGE_QUERY` hoặc `UPLOAD_SYNTHETIC_IMAGE` thành `True` nếu muốn upload một ảnh demo khác. Tệp được kiểm bytes/định dạng/kích thước trước giải mã, tối đa 10 MiB, 20 megapixel, JPEG/PNG/WebP một frame; ảnh được sửa hướng EXIF, bỏ metadata và giới hạn cạnh dài 1024 px. Không dùng URL ảnh tùy ý. Không mount Drive, mở tunnel/FastAPI, nhận credential hoặc kết nối R2/DB thật. Output notebook có thể được lưu khi chia sẻ; xóa output trước khi chia sẻ và xóa runtime sau thử nghiệm.

GPU Free, thời lượng, quota và T4 không được Google bảo đảm. Cần ít nhất 7 GiB VRAM trống và PyTorch >= 2.8 có sẵn; notebook dừng nếu thiếu GPU hoặc môi trường không phù hợp. Chưa chạy inference/đo VRAM trên GPU thật. Nếu OOM, xóa runtime rồi chạy riêng một notebook; không tự rơi về CPU. Độ phân giải thấp và 4-bit có thể bỏ sót vùng/chữ nhỏ; phải đánh giá trước khi dùng vào sản phẩm.

## Phiên bản và kết quả

Các gói chính được ghim trong cell setup: Transformers 4.57.3, Accelerate 1.12.0, qwen-vl-utils 0.0.14, Hugging Face Hub 0.36.0, NumPy 2.2.6, Pillow 11.3.0; notebook 02 thêm bitsandbytes 0.48.2 và opencv-python-headless 4.12.0.88. Setup dùng constraint giữ nguyên phiên bản `torch`/`torchvision`/`torchaudio` có sẵn, không cài FlashAttention. Nếu Colab yêu cầu restart sau cài gói, restart session rồi chạy lại từ cell đầu. Môi trường Colab thay đổi theo thời gian; manifest ghi toàn bộ phiên bản thực tế và CUDA/GPU để đối chiếu.

| Thành phần | Revision bất biến |
| --- | --- |
| Qwen3-VL-Embedding-2B, processor và script official đi kèm | `9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda` |
| SHA-256 script embedding được kiểm trước khi import | `8ffa74a1a6bb759610c57865ea416fd4daf9936cb787520e1112a3e1d547f36a` |
| Qwen3-VL-4B-Instruct và processor | `ebb281ec70b05090aa6165b016eac8ec08e71b17` |

Embedding dùng class và EOS pooling trong mã official đã ghim. Tiền xử lý chạy trực tiếp và báo lỗi: wrapper official có nhánh thay ảnh lỗi bằng `NULL`, không phù hợp khi cần phân biệt inference ảnh lỗi. Không tải mã Python theo nhánh `main` vào runtime. Instruct dùng implementation của Transformers đã ghim, `trust_remote_code=False`.

`findie-embedding-results.zip` chứa vector, cosine ranking và manifest. `findie-redaction-draft.zip` chứa PNG nháp đã mã hóa lại, vùng JSON và manifest; không xuất ảnh gốc/overlay/raw response. Manifest ghi model/processor/code revision, prompt/profile, hash profile, phiên bản/hash nội dung nguồn, kích thước ảnh, môi trường chạy và trạng thái duyệt. Những tệp này dành cho kiểm tra thủ công; chưa có đường tự nhập DB hoặc tự đánh dấu ảnh an toàn. Backend vẫn phải kiểm revision/profile, source version và điều kiện duyệt trước khi dùng vào ứng dụng.

## Tự kiểm tra cục bộ, không tải model

Các notebook có assert kiểm ảnh/EXIF, vector, JSON và bounding box. Chạy lệnh sau từ thư mục gốc để kiểm cấu trúc notebook, biên dịch mọi code cell và chạy trực tiếp các hàm xử lý trong notebook bằng CPU:

```sh
uv run --no-project --python 3.12 \
  --with numpy==2.2.6 --with pillow==11.3.0 \
  --with opencv-python-headless==4.12.0.88 --with nbformat==5.10.4 \
  python notebooks/colab/test_notebooks.py
```

Kiểm tra này không cài Torch, không tải weights và không thay thế chạy các cell inference trên Colab GPU.

## Nguồn chính thức

- [Qwen3-VL-Embedding-2B model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B) và [script theo revision đã ghim](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B/blob/9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda/scripts/qwen3_vl_embedding.py).
- [Qwen3-VL-Embedding repository](https://github.com/QwenLM/Qwen3-VL-Embedding), [dependencies official tại commit được đối chiếu](https://github.com/QwenLM/Qwen3-VL-Embedding/blob/393e2978d27852b0d0230d6994f37f9c15bed73c/pyproject.toml).
- [Qwen3-VL-4B-Instruct model card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), [Qwen cookbook 2D grounding](https://github.com/QwenLM/Qwen3-VL/blob/main/cookbooks/2d_grounding.ipynb), [Transformers Qwen3-VL](https://huggingface.co/docs/transformers/v4.57.3/en/model_doc/qwen3_vl).
- [Transformers bitsandbytes/NF4](https://huggingface.co/docs/transformers/v4.57.3/en/quantization/bitsandbytes), [Google Colab FAQ và giới hạn Free](https://research.google.com/colaboratory/faq.html).
