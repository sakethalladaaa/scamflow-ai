import type { Assessment, CaseRecord, EventInput, PaymentContext } from './types'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message) }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { credentials: 'include', ...init })
  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type') ?? ''
  let body: unknown
  if (contentType.includes('application/json')) {
    try { body = await response.json() } catch { body = undefined }
  }
  if (!response.ok) {
    const detail = typeof body === 'object' && body && 'detail' in body
      ? (body as { detail?: { code?: string; message?: string } }).detail : undefined
    throw new ApiError(response.status, detail?.code ?? 'request_failed', detail?.message ?? `Request failed (${response.status}).`)
  }
  if (body === undefined) throw new ApiError(response.status, 'invalid_response', 'The server returned an invalid response.')
  return body as T
}

const mutationHeaders = (key?: string): HeadersInit => ({
  'Content-Type': 'application/json',
  'X-ScamFlow-CSRF': '1',
  ...(key ? { 'Idempotency-Key': key } : {}),
})

export const api = {
  bootstrap: () => request<{ expires_at: string }>('/session', { method: 'POST', headers: mutationHeaders() }),
  createCase: (key: string, payment_context: PaymentContext, events: EventInput[]) =>
    request<{ case_id: string; result_revision: number }>('/cases', { method: 'POST', headers: mutationHeaders(key), body: JSON.stringify({ consent: true, payment_context, events }) }),
  getCase: (id: string, signal?: AbortSignal) => request<CaseRecord>(`/cases/${id}`, { signal }),
  append: (id: string, key: string, expected_revision: number, events: EventInput[]) =>
    request<{ result_revision: number }>(`/cases/${id}/events`, { method: 'POST', headers: mutationHeaders(key), body: JSON.stringify({ expected_revision, events }) }),
  assess: (id: string, key: string, expected_revision: number, signal?: AbortSignal) =>
    request<Assessment>(`/cases/${id}/assess`, { method: 'POST', headers: mutationHeaders(key), body: JSON.stringify({ expected_revision }), signal }),
  latest: (id: string, signal?: AbortSignal) => request<Assessment>(`/cases/${id}/assessments/latest`, { signal }),
  deleteCase: (id: string) => request<void>(`/cases/${id}`, { method: 'DELETE', headers: mutationHeaders() }),
}

export const newKey = (scope: string) => `${scope}-${crypto.randomUUID()}`
