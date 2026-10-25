import { afterEach, expect, it, vi } from 'vitest';
import { ApiError, realApi } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it('accepts the backend empty 204 delete response', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(realApi.deleteCase('case-1')).resolves.toBeUndefined();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(init.method).toBe('DELETE');
  expect(init.credentials).toBe('include');
  expect(new Headers(init.headers).get('X-ScamFlow-CSRF')).toBe('1');
});

it('maps a non-JSON 502 response to the safe backend request_failed fallback', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('gateway error', { status: 502 })));
  await expect(realApi.getCase('case-1')).rejects.toBeInstanceOf(ApiError);
  await realApi.getCase('case-1').catch((error: ApiError) => {
    expect(error.status).toBe(502);
    expect(error.code).toBe('request_failed');
  });
});
