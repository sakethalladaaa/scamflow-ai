import { afterEach, expect, it, vi } from 'vitest'
import { ApiError, api } from './api'

afterEach(() => vi.unstubAllGlobals())

it('accepts an empty 204 delete response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
  await expect(api.deleteCase('case-1')).resolves.toBeUndefined()
})

it('reports a safe fallback for a non-JSON failure', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('gateway error', { status: 502 })))
  await expect(api.getCase('case-1')).rejects.toBeInstanceOf(ApiError)
  await api.getCase('case-1').catch((error: ApiError) => {
    expect(error.status).toBe(502)
    expect(error.code).toBe('request_failed')
  })
})
