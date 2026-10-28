import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import { loadUser, logout, updateProfile } from './auth.ts';

afterEach(() => mock.restoreAll());

test('profile changes validate and send only the trimmed display name with CSRF', async () => {
  assert.throws(() => updateProfile('   '));
  assert.throws(() => updateProfile('x'.repeat(121)));
  const calls: Array<[unknown, RequestInit | undefined]> = [];
  const profile = { id: 'user', email: null, displayName: 'Tên mới', createdAt: '2026-10-24' };
  mock.method(globalThis, 'fetch', async (url: unknown, options?: RequestInit) => {
    calls.push([url, options]);
    return Response.json(url === '/api/auth/csrf' ? { token: 'csrf-profile' } : profile);
  });
  assert.deepEqual(await updateProfile('  Tên mới  '), profile);
  assert.equal(calls[1][0], '/api/users/me');
  assert.equal(calls[1][1]?.method, 'PUT');
  assert.deepEqual(JSON.parse(calls[1][1]!.body as string), { displayName: 'Tên mới' });
  assert.equal((calls[1][1]!.headers as Record<string, string>)['X-CSRF-TOKEN'], 'csrf-profile');
});

test('anonymous sessions return null and authenticated sessions read a safe profile', async () => {
  const signal = new AbortController().signal;
  const profile = { id: 'user-id', email: 'user@example.test', displayName: 'Findie', createdAt: '2026-10-24T00:00:00Z' };
  mock.method(globalThis, 'fetch', async () => new Response(null, { status: 401 }));
  assert.equal(await loadUser(signal), null);
  mock.restoreAll();
  mock.method(globalThis, 'fetch', async () => Response.json(profile));
  assert.deepEqual(await loadUser(signal), profile);
});

test('invalid profiles and server failures remain visible', async () => {
  const signal = new AbortController().signal;
  for (const response of [Response.json({ id: 'missing-fields' }), new Response(null, { status: 500 })]) {
    mock.restoreAll();
    mock.method(globalThis, 'fetch', async () => response);
    await assert.rejects(loadUser(signal));
  }
});

test('logout sends the server CSRF token and carries cancellation', async () => {
  const signal = new AbortController().signal;
  const calls: Array<[unknown, RequestInit | undefined]> = [];
  mock.method(globalThis, 'fetch', async (url: unknown, options?: RequestInit) => {
    calls.push([url, options]);
    return url === '/api/auth/csrf' ? Response.json({ token: 'csrf-value' }) : new Response(null, { status: 204 });
  });
  await logout(signal);
  assert.deepEqual(calls, [
    ['/api/auth/csrf', { signal, credentials: 'same-origin' }],
    ['/api/auth/logout', { method: 'POST', signal, credentials: 'same-origin', headers: { 'X-CSRF-TOKEN': 'csrf-value' } }],
  ]);
});

test('logout rejects invalid CSRF and failed writes', async () => {
  const signal = new AbortController().signal;
  mock.method(globalThis, 'fetch', async () => Response.json({ token: '' }));
  await assert.rejects(logout(signal));
  mock.restoreAll();
  mock.method(globalThis, 'fetch', async (url: unknown) =>
    url === '/api/auth/csrf' ? Response.json({ token: 'csrf-value' }) : new Response(null, { status: 500 }));
  await assert.rejects(logout(signal));
});
