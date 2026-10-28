import { write } from './api.ts';

export type UserProfile = { id: string; email: string | null; displayName: string; createdAt: string };

export function updateProfile(displayName: string): Promise<UserProfile> {
  const name = displayName.trim();
  if (!name || name.length > 120) throw new Error('Tên hiển thị cần có từ 1 đến 120 ký tự.');
  return write<UserProfile>('/api/users/me', { displayName: name }, 'PUT');
}

export async function loadUser(signal: AbortSignal): Promise<UserProfile | null> {
  const response = await fetch('/api/users/me', { signal, credentials: 'same-origin' });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error('Chưa đọc được hồ sơ đăng nhập.');
  const value: unknown = await response.json();
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Hồ sơ đăng nhập không hợp lệ.');
  }
  const profile = value as Partial<UserProfile>;
  if (typeof profile.id !== 'string' || typeof profile.displayName !== 'string'
    || typeof profile.createdAt !== 'string' || (profile.email !== null && typeof profile.email !== 'string')) {
    throw new Error('Hồ sơ đăng nhập không hợp lệ.');
  }
  return profile as UserProfile;
}

export async function logout(signal: AbortSignal): Promise<void> {
  const csrf = await fetch('/api/auth/csrf', { signal, credentials: 'same-origin' });
  if (csrf.status === 401) return;
  if (!csrf.ok) throw new Error('Chưa lấy được mã xác nhận đăng xuất.');
  const value: unknown = await csrf.json();
  if (!value || typeof value !== 'object' || !('token' in value)
    || typeof value.token !== 'string' || !value.token.trim()) {
    throw new Error('Mã xác nhận đăng xuất không hợp lệ.');
  }
  const response = await fetch('/api/auth/logout', {
    method: 'POST', signal, credentials: 'same-origin', headers: { 'X-CSRF-TOKEN': value.token },
  });
  if (!response.ok && response.status !== 401) throw new Error('Đăng xuất chưa hoàn tất. Hãy thử lại.');
}
