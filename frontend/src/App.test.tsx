import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import App, { EvidenceText } from './App'

afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState({}, '', '/') })

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
})

it('requires consent and does not submit invalid intake', async () => {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ expires_at: '2030-01-01T00:00:00Z' }))
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  await screen.findByText('Local session ready')
  await userEvent.type(screen.getByLabelText('Message or transcript'), 'hello')
  await userEvent.type(screen.getByLabelText('Stated payment purpose'), 'refund')
  await userEvent.click(screen.getByRole('button', { name: 'Create case' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Consent is required')
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('prevents a duplicate create mutation while the first is pending', async () => {
  let resolveCreate!: (value: Response) => void
  const fetchMock = vi.fn((path: string) => {
    if (path === '/session') return Promise.resolve(jsonResponse({ expires_at: '2030-01-01T00:00:00Z' }))
    if (path === '/cases') return new Promise<Response>((resolve) => { resolveCreate = resolve })
    return Promise.resolve(jsonResponse({ detail: { code: 'not_found', message: 'not found' } }, 404))
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  await screen.findByText('Local session ready')
  await userEvent.type(screen.getByLabelText('Message or transcript'), 'hello')
  await userEvent.type(screen.getByLabelText('Stated payment purpose'), 'refund')
  await userEvent.click(screen.getByLabelText(/I consent/))
  const submit = screen.getByRole('button', { name: 'Create case' })
  fireEvent.click(submit); fireEvent.click(submit)
  expect(fetchMock.mock.calls.filter(([path]) => path === '/cases')).toHaveLength(1)
  resolveCreate(jsonResponse({ case_id: 'case-1', result_revision: 1 }, 201))
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
})

it('renders HTML-like evidence as text, never executable markup', () => {
  const { container } = render(<p><EvidenceText text={'<script>window.bad=true</script>'} /></p>)
  expect(screen.getByText('<script>window.bad=true</script>')).toBeInTheDocument()
  expect(container.querySelector('script')).toBeNull()
})
