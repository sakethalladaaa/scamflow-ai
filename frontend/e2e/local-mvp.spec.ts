import { expect, test } from '@playwright/test'

test('session, replay, highlight, append, reload, isolation, CSRF, and delete', async ({ browser }) => {
  const first = await browser.newContext()
  const page = await first.newPage()
  await page.goto('/')
  await expect(page.getByText('Local session ready')).toBeVisible()

  await page.getByRole('button', { name: 'Start demo' }).click()
  await expect(page.getByRole('heading', { name: 'Needs clarification or review' })).toBeVisible()
  const caseId = new URL(page.url()).searchParams.get('case')!

  await page.getByRole('button', { name: /Highlight quote/ }).first().click()
  await expect(page.getByTestId('selected-highlight')).toBeVisible()

  await page.getByRole('button', { name: 'Reveal next & reassess' }).click()
  await expect(page.getByRole('heading', { name: 'High-risk indicators' })).toBeVisible()

  await page.getByPlaceholder('Add the exact next message or clarification').fill('Reference number SAFE-1.')
  await page.getByRole('button', { name: 'Append evidence' }).click()
  await expect(page.getByText(/Historical result/)).toBeVisible()
  await page.getByRole('button', { name: 'Reassess current revision' }).click()
  await expect(page.getByText(/unchanged warning suppressed/i)).toHaveCount(0)

  await page.reload()
  await expect(page.getByText('Revision 3').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'High-risk indicators' })).toBeVisible()

  const second = await browser.newContext()
  const secondPage = await second.newPage()
  await secondPage.goto('/')
  const inaccessible = await secondPage.evaluate(async (id) => (await fetch(`/cases/${id}`)).status, caseId)
  expect(inaccessible).toBe(404)
  await second.close()

  const csrfStatus = await page.evaluate(async () => (await fetch('/cases', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'missing-csrf' },
    body: JSON.stringify({ consent: true, payment_context: { stated_purpose: 'x' }, events: [{ event_id: 'x', channel: 'sms', text: 'x', source_order: 1 }] }),
  })).status)
  expect(csrfStatus).toBe(403)

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Delete case' }).click()
  await expect(page.getByRole('heading', { name: 'Check an interaction' })).toBeVisible()
  await first.close()
})

test('unsupported demo visibly ends unable to assess', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Scenario').selectOption('unsupported')
  await page.getByRole('button', { name: 'Start demo' }).click()
  await expect(page.getByRole('heading', { name: 'Unable to assess' })).toBeVisible()
  await expect(page.getByText('Development mock — not real AI inference.').first()).toBeVisible()
})
