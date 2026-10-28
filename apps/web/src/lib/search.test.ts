import assert from "node:assert/strict";
import { afterEach, mock, test } from "node:test";
import { ApiError } from "./api.ts";
import { basicSearchUrl, searchImage, searchImages, searchText, validateSearchImages } from "./search.ts";

afterEach(() => mock.restoreAll());

const response = {
  items: [],
  mode: "text",
  searchProfileId: "text-description-v1",
  searchProfileVersion: 1,
  partial: true,
  filtersRelaxed: false,
  fallbackUrl: "/api/items",
};

test("text search sends the cookie/CSRF JSON contract and preserves metadata", async () => {
  const requests: { path: string; init?: RequestInit }[] = [];
  mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    requests.push({ path, init });
    return Response.json(path === "/api/auth/csrf" ? { token: "csrf-search" } : response);
  });
  assert.deepEqual(await searchText("  ví đen  ", {
    area: "Quận 1", from: "2026-10-01", until: "2026-10-24",
  }), response);
  assert.deepEqual(requests.map((request) => request.path), ["/api/auth/csrf", "/api/search"]);
  const init = requests[1].init!;
  assert.equal(init.method, "POST");
  assert.equal(init.credentials, "same-origin");
  assert.deepEqual(init.headers, { "X-CSRF-TOKEN": "csrf-search", "Content-Type": "application/json" });
  assert.deepEqual(JSON.parse(String(init.body)), {
    text: "ví đen", area: "Quận 1", from: "2026-10-01", until: "2026-10-24", limit: 10,
  });
});

test("image search sends raw bytes, MIME, CSRF and filters without mixing text", async () => {
  const file = new File([new Uint8Array([137, 80, 78, 71])], "query.png", { type: "image/png" });
  const requests: { path: string; init?: RequestInit }[] = [];
  mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    requests.push({ path, init });
    return Response.json(path === "/api/auth/csrf" ? { token: "csrf-image" } : { ...response, mode: "image" });
  });
  const result = await searchImage(file, { area: " Quận 1 ", from: "2026-10-01", until: "2026-10-24" });
  assert.equal(result.mode, "image");
  const request = requests[1];
  const url = new URL(request.path, "https://findie.test");
  assert.equal(url.pathname, "/api/search/image");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    limit: "10", area: "Quận 1", from: "2026-10-01", until: "2026-10-24",
  });
  assert.equal(request.init!.body, file);
  assert.equal(request.init!.method, "POST");
  assert.equal(request.init!.credentials, "same-origin");
  assert.deepEqual(request.init!.headers, { "X-CSRF-TOKEN": "csrf-image", "Content-Type": "image/png" });
});

test("multiple-image search sends three images, description, CSRF, filters and cancellation", async () => {
  const files = [
    new File(["jpeg"], "front.jpg", { type: "image/jpeg" }),
    new File(["png"], "back.png", { type: "image/png" }),
    new File(["webp"], "detail.webp", { type: "image/webp" }),
  ];
  const signal = new AbortController().signal;
  const requests: { path: string; init?: RequestInit }[] = [];
  mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    requests.push({ path, init });
    return Response.json(path === "/api/auth/csrf" ? { token: "csrf-images" } : { ...response, mode: "combined" });
  });
  const result = await searchImages(files, "  ví đen  ", {
    area: " Quận 1 ", from: "2026-10-01", until: "2026-10-24",
  }, signal);
  assert.equal(result.mode, "combined");
  assert.equal(requests.length, 2);
  assert.equal(requests[0].path, "/api/auth/csrf");
  const { path, init } = requests[1];
  const url = new URL(path, "https://findie.test");
  assert.equal(url.pathname, "/api/search/images");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    limit: "10", area: "Quận 1", from: "2026-10-01", until: "2026-10-24",
  });
  assert.equal(init!.method, "POST");
  assert.equal(init!.credentials, "same-origin");
  assert.equal(init!.signal, signal);
  assert.deepEqual(init!.headers, { "X-CSRF-TOKEN": "csrf-images" });
  assert.ok(init!.body instanceof FormData);
  assert.deepEqual(init!.body.getAll("images"), files);
  assert.equal(init!.body.get("text"), "ví đen");
});

test("multiple-image search accepts an image without a description", async () => {
  const file = new File(["png"], "query.png", { type: "image/png" });
  let body: FormData | undefined;
  mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    if (path === "/api/auth/csrf") return Response.json({ token: "csrf-images-only" });
    assert.ok(init!.body instanceof FormData);
    body = init!.body;
    return Response.json({ ...response, mode: "image" });
  });
  assert.equal((await searchImages([file], "  ", {})).mode, "image");
  assert.deepEqual(body!.getAll("images"), [file]);
  assert.equal(body!.has("text"), false);
});

test("multiple-image search rejects invalid counts, text, MIME and size before network access", async () => {
  const file = new File(["png"], "query.png", { type: "image/png" });
  let calls = 0;
  mock.method(globalThis, "fetch", async () => {
    calls++;
    throw new Error("must not send invalid input");
  });
  assert.doesNotThrow(() => validateSearchImages([]));
  assert.doesNotThrow(() => validateSearchImages([file, file, file]));
  assert.throws(() => validateSearchImages([file, file, file, file]), /tối đa 3 ảnh/);
  await assert.rejects(searchImages([], "ví đen", {}), /ít nhất 1 ảnh/);
  await assert.rejects(searchImages([file, file, file, file], "", {}), /tối đa 3 ảnh/);
  await assert.rejects(searchImages([file], "x".repeat(2001), {}), /2000 ký tự/);
  for (const invalid of [
    new File(["<svg/>"], "unsafe.svg", { type: "image/svg+xml" }),
    new File([], "empty.png", { type: "image/png" }),
    new File([new Uint8Array(10 * 1024 * 1024 + 1)], "big.jpg", { type: "image/jpeg" }),
  ]) await assert.rejects(searchImages([file, invalid], "", {}));
  assert.equal(calls, 0);
});

test("multiple-image search preserves API failures", async () => {
  mock.method(globalThis, "fetch", async (path: string) =>
    path === "/api/auth/csrf"
      ? Response.json({ token: "csrf-images-unavailable" })
      : new Response(null, { status: 503 }),
  );
  const file = new File(["png"], "query.png", { type: "image/png" });
  await assert.rejects(searchImages([file], "ví đen", {}), (error) => error instanceof ApiError && error.status === 503);
});

test("invalid text and private image input are rejected before network access", async () => {
  let calls = 0;
  mock.method(globalThis, "fetch", async () => {
    calls++;
    throw new Error("must not send invalid input");
  });
  for (const text of ["   ", "x".repeat(2001)])
    await assert.rejects(searchText(text, {}), /1 đến 2000/);
  for (const file of [
    new File(["<svg/>"], "unsafe.svg", { type: "image/svg+xml" }),
    new File([], "empty.png", { type: "image/png" }),
    new File([new Uint8Array(10 * 1024 * 1024 + 1)], "big.jpg", { type: "image/jpeg" }),
  ]) await assert.rejects(searchImage(file, {}));
  assert.equal(calls, 0);
});

test("unavailable search stays an error and fallback preserves only basic filters", async () => {
  mock.method(globalThis, "fetch", async (path: string) =>
    path === "/api/auth/csrf"
      ? Response.json({ token: "csrf-search-unavailable" })
      : new Response(null, { status: 503 }),
  );
  await assert.rejects(searchText("ví đen", {}), (error) => error instanceof ApiError && error.status === 503);
  const fallback = new URL(basicSearchUrl({ area: " Bờ Sông ", from: "2026-10-01", until: "" }), "https://findie.test");
  assert.equal(fallback.pathname, "/search");
  assert.deepEqual(Object.fromEntries(fallback.searchParams), {
    mode: "basic", area: "Bờ Sông", from: "2026-10-01",
  });
});
