import { api, validateImages, writeHeaders, type Item } from "./api.ts";

export type SearchFilters = { area?: string; from?: string; until?: string };
export type SearchResponse = {
  items: { rank: number; item: Item }[];
  mode: "text" | "image" | "combined";
  searchProfileId: string;
  searchProfileVersion: number;
  partial: boolean;
  filtersRelaxed: boolean;
  fallbackUrl: string;
};

export async function searchText(
  text: string,
  filters: SearchFilters,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  text = text.trim();
  if (!text || text.length > 2000)
    throw new Error("Mô tả tìm kiếm cần có từ 1 đến 2000 ký tự.");
  return api<SearchResponse>("/api/search", {
    method: "POST",
    signal,
    headers: {
      ...(await writeHeaders()),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text, ...filters, limit: 10 }),
  });
}

export async function searchImage(
  file: File,
  filters: SearchFilters,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  validateImages([file]);
  const query = new URLSearchParams({ limit: "10" });
  for (const [key, value] of Object.entries(filters))
    if (value?.trim()) query.set(key, value.trim());
  return api<SearchResponse>(`/api/search/image?${query}`, {
    method: "POST",
    signal,
    body: file,
    headers: {
      ...(await writeHeaders()),
      "Content-Type": file.type,
    },
  });
}

export function validateSearchImages(files: readonly Pick<File, "type" | "size">[]) {
  if (files.length > 3) throw new Error("Mỗi lần tìm kiếm có tối đa 3 ảnh.");
  validateImages(files);
}

export async function searchImages(
  files: readonly File[],
  text: string,
  filters: SearchFilters,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  validateSearchImages(files);
  if (!files.length) throw new Error("Cần chọn ít nhất 1 ảnh để tìm kiếm.");
  text = text.trim();
  if (text.length > 2000)
    throw new Error("Mô tả tìm kiếm có tối đa 2000 ký tự.");
  const body = new FormData();
  for (const file of files) body.append("images", file);
  if (text) body.append("text", text);
  const query = new URLSearchParams({ limit: "10" });
  for (const [key, value] of Object.entries(filters))
    if (value?.trim()) query.set(key, value.trim());
  return api<SearchResponse>(`/api/search/images?${query}`, {
    method: "POST",
    signal,
    body,
    headers: await writeHeaders(),
  });
}

export function basicSearchUrl(filters: SearchFilters): string {
  const query = new URLSearchParams({ mode: "basic" });
  for (const [key, value] of Object.entries(filters))
    if (value?.trim()) query.set(key, value.trim());
  return `/search?${query}`;
}
