import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { type Page } from '@playwright/test';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const mockItemsData = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../fixtures/mock-items.json'), 'utf-8')
);

export type MockUser = {
  id: string;
  email: string | null;
  displayName: string;
  createdAt: string;
};

export const defaultMockUser: MockUser = {
  id: 'u-finder-test-01',
  email: 'tester@findie.vn',
  displayName: 'Nguyễn Văn Test',
  createdAt: '2026-11-01T00:00:00Z',
};

export type MockScenarioOptions = {
  user?: MockUser | null;
  items?: any[];
  aiServiceAvailable?: boolean;       // false: Giả lập AI Service 503 Service Unavailable
  authStatus?: 'authenticated' | 'unauthorized' | 'token-expired';
  searchDelayMs?: number;            // Giả lập độ trễ mạng để test loading spinner
};

export async function setupDefaultApiMocks(
  page: Page,
  options?: MockScenarioOptions
) {
  const authStatus = options?.authStatus ?? (options?.user === null ? 'unauthorized' : 'authenticated');
  const user = authStatus === 'authenticated'
    ? (options?.user !== undefined ? options.user : defaultMockUser)
    : null;
  const items = options?.items ?? mockItemsData;
  const aiServiceAvailable = options?.aiServiceAvailable !== false;
  const searchDelayMs = options?.searchDelayMs ?? 0;

  // 1. Auth & Session
  await page.route('**/api/users/me', async (route) => {
    if (authStatus === 'unauthorized' || user === null) {
      await route.fulfill({ status: 401, json: { message: 'Unauthorized' } });
    } else {
      await route.fulfill({ status: 200, json: user });
    }
  });

  await page.route('**/api/auth/csrf', async (route) => {
    if (authStatus === 'token-expired') {
      await route.fulfill({ status: 401, json: { message: 'Token expired' } });
    } else {
      await route.fulfill({
        status: 200,
        json: { token: 'mock-csrf-token-xyz-123' },
      });
    }
  });

  // 2. Search & Items List (Basic Search GET)
  await page.route('**/api/items?*', async (route) => {
    const url = new URL(route.request().url());
    const q = url.searchParams.get('q')?.toLowerCase() ?? '';
    const area = url.searchParams.get('area')?.toLowerCase() ?? '';

    let filtered = items;
    if (q) {
      filtered = filtered.filter(
        (it: any) =>
          it.title.toLowerCase().includes(q) ||
          it.publicDescription.toLowerCase().includes(q)
      );
    }
    if (area) {
      filtered = filtered.filter((it: any) =>
        it.foundArea.toLowerCase().includes(area)
      );
    }

    await route.fulfill({
      status: 200,
      json: {
        items: filtered,
        page: 1,
        pageSize: 12,
        hasMore: false,
      },
    });
  });

  // 3. Smart Search (POST /api/search)
  await page.route('**/api/search', async (route) => {
    if (route.request().method() !== 'POST') {
      return route.continue();
    }
    if (!aiServiceAvailable) {
      await route.fulfill({
        status: 503,
        json: { message: 'Dịch vụ tìm kiếm AI tạm thời chưa sẵn sàng.' },
      });
      return;
    }
    if (searchDelayMs > 0) {
      await new Promise((res) => setTimeout(res, searchDelayMs));
    }

    const postData = route.request().postDataJSON();
    const text = (postData?.text ?? '').toLowerCase();
    const area = (postData?.area ?? '').toLowerCase();

    let matched = items;
    if (text) {
      matched = matched.filter(
        (it: any) =>
          it.title.toLowerCase().includes(text) ||
          it.publicDescription.toLowerCase().includes(text)
      );
    }

    await route.fulfill({
      status: 200,
      json: {
        items: matched.map((item: any, idx: number) => ({ rank: idx + 1, item })),
        mode: 'text',
        searchProfileId: 'mock-prof-1',
        searchProfileVersion: 1,
        partial: false,
        filtersRelaxed: Boolean(area && matched.some((item: any) => !item.foundArea.toLowerCase().includes(area))),
        fallbackUrl: `/search?mode=basic&q=${encodeURIComponent(postData?.text ?? '')}`,
      },
    });
  });

  // 3b. Multimodal Image Search (POST /api/search/images* and /api/search/image*)
  await page.route(/.*\/api\/search\/images?(\?.*)?$/i, async (route) => {
    if (route.request().method() !== 'POST') {
      return route.continue();
    }
    if (!aiServiceAvailable) {
      await route.fulfill({
        status: 503,
        json: { message: 'Dịch vụ phân tích ảnh AI tạm thời chưa sẵn sàng.' },
      });
      return;
    }
    if (searchDelayMs > 0) {
      await new Promise((res) => setTimeout(res, searchDelayMs));
    }

    const area = new URL(route.request().url()).searchParams.get('area')?.toLowerCase() ?? '';
    await route.fulfill({
      status: 200,
      json: {
        items: items.map((item: any, idx: number) => ({ rank: idx + 1, item })),
        mode: 'image',
        searchProfileId: 'mock-prof-img',
        searchProfileVersion: 1,
        partial: false,
        filtersRelaxed: Boolean(area && items.some((item: any) => !item.foundArea.toLowerCase().includes(area))),
        fallbackUrl: '/search?mode=basic',
      },
    });
  });

  // 4. Item Detail & Verification Questions
  await page.route(/\/api\/items\/([\da-f-]+)$/i, async (route) => {
    const method = route.request().method();
    const match = route.request().url().match(/\/api\/items\/([\da-f-]+)$/i);
    const id = match ? match[1] : '';

    if (method === 'GET') {
      const found = items.find((it: any) => it.id === id) ?? items[0];
      await route.fulfill({ status: 200, json: { ...found, id } });
    } else if (method === 'PUT') {
      const data = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        json: { ...items[0], id, ...data?.content, rowVersion: 2 },
      });
    } else {
      await route.continue();
    }
  });

  await page.route(/\/api\/items\/([\da-f-]+)\/verification-questions$/i, async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        contentVersion: 1,
        questions: [
          {
            slot: 1,
            questionText: 'Móc khóa có hình nhân vật hoạt hình nào?',
          },
        ],
      },
    });
  });

  // 5. Post Item Creation
  await page.route('**/api/items', async (route) => {
    if (route.request().method() === 'POST') {
      const postData = route.request().postDataJSON();
      const newItemId = 'e4b2d380-6bc7-4d98-b80c-e2f4a56c9999';
      await route.fulfill({
        status: 201,
        json: {
          id: newItemId,
          title: postData?.content?.title ?? 'Món đồ mới đăng',
          publicDescription: postData?.content?.description ?? 'Mô tả chi tiết',
          foundArea: postData?.content?.area ?? 'Cơ sở 1',
          foundTimePrecision: postData?.content?.precision ?? 'unknown',
          foundOn: null,
          foundFrom: null,
          foundUntil: null,
          foundTimezone: 'Asia/Ho_Chi_Minh',
          custody: postData?.custody ?? { kind: 'person', displayName: user?.displayName ?? 'Tôi' },
          lifecycle: 'active',
          publicationState: 'published',
          canClaim: true,
          canDelete: true,
          rowVersion: 1,
          createdAt: new Date().toISOString(),
          images: [],
        },
      });
    } else {
      await route.continue();
    }
  });

  // 6. Image Upload
  await page.route(/\/api\/items\/([\da-f-]+)\/images\?position=(\d+)$/i, async (route) => {
    const match = route.request().url().match(/\/api\/items\/([\da-f-]+)\/images\?position=(\d+)$/i);
    const itemId = match ? match[1] : '';
    const position = match ? Number(match[2]) : 1;

    await route.fulfill({
      status: 201,
      json: {
        id: `img-${itemId}-${position}`,
        itemId,
        position,
        contentVersion: 1,
        processingState: 'completed',
        reviewState: 'approved',
        failureCode: null,
        previewUrl: '/assets/sample-item.jpg',
      },
    });
  });

  // 7. Reception Points
  await page.route('**/api/reception-points', async (route) => {
    await route.fulfill({
      status: 200,
      json: [
        {
          id: 'point-hub-01',
          name: 'Findie Hub Sài Gòn A',
          publicAddress: '273 An Dương Vương, Phường 3, Quận 5',
          directions: 'Quầy tiếp nhận tại sảnh A',
        },
      ],
    });
  });

  // 8. Claims (Claim submission & Claim detail)
  await page.route(/\/api\/items\/([\da-f-]+)\/claims$/i, async (route) => {
    const match = route.request().url().match(/\/api\/items\/([\da-f-]+)\/claims$/i);
    const itemId = match ? match[1] : '';
    const postData = route.request().postDataJSON();

    await route.fulfill({
      status: 201,
      json: {
        id: 'c1a2b3c4-d5e6-4a7b-8c9d-0e1f2a3b4c5d',
        itemId,
        claimantUserId: user?.id ?? 'u-claimer-01',
        reviewerUserId: 'u-finder-01',
        status: 'pending',
        stale: false,
        createdAt: new Date().toISOString(),
        decidedAt: null,
        decisionNote: null,
        conversationId: null,
        answers: postData?.answers ?? [],
      },
    });
  });

  await page.route(/\/api\/claims\/([\da-f-]+)$/i, async (route) => {
    const match = route.request().url().match(/\/api\/claims\/([\da-f-]+)$/i);
    const claimId = match ? match[1] : '';

    await route.fulfill({
      status: 200,
      json: {
        id: claimId,
        itemId: items[0].id,
        claimantUserId: user?.id ?? 'u-claimer-01',
        reviewerUserId: 'u-finder-other-02',
        status: 'pending',
        stale: false,
        createdAt: '2026-11-04T09:00:00Z',
        decidedAt: null,
        decisionNote: null,
        conversationId: null,
        answers: [
          {
            slot: 1,
            questionText: 'Móc khóa có hình nhân vật hoạt hình nào?',
            answerText: 'Doraemon đeo chuông vàng',
          },
        ],
      },
    });
  });
}
