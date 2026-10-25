import { expect, test } from '@playwright/test'

test('session, highlight, append, reload, isolation, CSRF, and delete', async ({ browser }) => {
  const first = await browser.newContext()
  const page = await first.newPage()
  await page.goto('/')
  await page.getByLabel('Conversation text').fill('Sender: please send your OTP now.')
  await page.getByLabel('Stated payment purpose (required)').fill('Account verification')
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: /Analyse conversation/ }).click()
  await expect(page.getByRole('heading', { name: 'Needs clarification or review' })).toBeVisible()

  await page.getByRole('button', { name: /View in timeline/ }).first().click()
  await expect(page.locator('mark').first()).toBeVisible()

  await page.getByPlaceholder('Paste the next message exactly as received…').fill('Reference number SAFE-1.')
  await page.getByRole('button', { name: 'Add message' }).click()
  await expect(page.getByText(/result is historical/i)).toBeVisible()
  await page.getByRole('button', { name: 'Reassess current revision' }).click()
  await expect(page.getByRole('heading', { name: 'Needs clarification or review' })).toBeVisible()

  const second = await browser.newContext()
  const secondPage = await second.newPage()
  await secondPage.goto('/')
  const inaccessible = await secondPage.evaluate(async () => (await fetch('/cases/not-owned-by-this-session')).status)
  expect(inaccessible).toBe(401)
  await second.close()

  const csrfStatus = await page.evaluate(async () => (await fetch('/cases', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'missing-csrf' },
    body: JSON.stringify({ consent: true, payment_context: { stated_purpose: 'x' }, events: [{ event_id: 'x', channel: 'sms', text: 'x', source_order: 1 }] }),
  })).status)
  expect(csrfStatus).toBe(403)

  await page.getByRole('button', { name: 'Delete case' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete case' }).click()
  await expect(page.getByRole('heading', { name: 'Case deleted' })).toBeVisible()
  await first.close()
})

test('checkpoint preserves the assessment boundary', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Conversation text').fill('Sender: please send your OTP now.')
  await page.getByLabel('Stated payment purpose (required)').fill('Account verification')
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: /Analyse conversation/ }).click()
  await expect(page.getByRole('heading', { name: 'Needs clarification or review' })).toBeVisible()
  await page.getByRole('button', { name: /Open simulated Before You Pay checkpoint/ }).click()
  await expect(page.getByRole('heading', { name: 'Before You Pay' })).toBeVisible()
  await expect(page.getByText(/SIMULATION ONLY · NO PAYMENT ACTION/)).toBeVisible()
})
