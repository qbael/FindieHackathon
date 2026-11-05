import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SearchPage } from '../pages/SearchPage';
import { setupDefaultApiMocks } from '../utils/mockApi';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const sampleImage = path.resolve(__dirname, '../fixtures/sample-item.jpg');

test.describe('CUJ-04: Tìm kiếm bằng hình ảnh (Image Search Flow)', () => {
  test.beforeEach(async ({ page }) => {
    await setupDefaultApiMocks(page);
  });

  test('Kịch bản 4.1: Tải ảnh tìm kiếm thành công và nhận gợi ý kết quả', async ({ page }) => {
    const searchPage = new SearchPage(page);

    // 1. Mở trang tìm kiếm
    await searchPage.goto('/search');
    await expect(searchPage.uploadZone).toBeVisible();

    // 2. Tải lên tệp ảnh mẫu
    await searchPage.uploadSearchImage(sampleImage);

    // 3. Kiểm tra ảnh preview hiển thị trong danh sách ảnh đã chọn
    await searchPage.expectImagePreviewsCount(1);
    await expect(searchPage.previewItems.first()).toContainText('sample-item.jpg');

    // 4. Nhấn nút Tìm kiếm
    await searchPage.searchButton.click();

    // 5. Kiểm tra kết quả trả về hiển thị các thẻ đồ vật có thứ tự gợi ý
    await expect(searchPage.itemCards.first()).toBeVisible();
    await expect(searchPage.resultsHeading).toContainText(/Gợi ý theo ảnh/i);
    await expect(searchPage.itemCards.first()).toContainText(/Gợi ý 1/i);
  });

  test('Kịch bản 4.2: Tải nhiều ảnh cùng lúc và xóa bớt ảnh preview', async ({ page }) => {
    const searchPage = new SearchPage(page);

    // 1. Mở trang tìm kiếm
    await searchPage.goto('/search');

    // 2. Tải lên 2 ảnh
    await searchPage.uploadSearchImage([sampleImage, sampleImage]);

    // 3. Kiểm tra hiển thị đủ 2 thumbnail ảnh xem trước
    await searchPage.expectImagePreviewsCount(2);

    // 4. Nhấn nút xóa ảnh thứ nhất
    await searchPage.removeImagePreview(0);

    // 5. Kiểm tra số lượng ảnh preview giảm xuống còn 1
    await searchPage.expectImagePreviewsCount(1);
  });
});
