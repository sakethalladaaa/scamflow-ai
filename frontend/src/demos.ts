import type { EventInput, PaymentContext } from './types'

export interface DemoScenario {
  id: string
  title: string
  payment: PaymentContext
  events: EventInput[]
}

// Expected outcomes and family/provenance metadata intentionally live outside
// this detector-input module (see evaluation/scenarios). Only the revealed
// prefix returned below is ever submitted.
export const demos: DemoScenario[] = [
  {
    id: 'digital-arrest',
    title: 'Digital Arrest progression',
    payment: { stated_purpose: 'Caller-requested verification', amount: '25000', recipient_reference: 'Unknown UPI recipient' },
    events: [
      { event_id: 'demo-da-1', channel: 'call_transcript', text: 'I am a cyber crime officer. Your account is under investigation.', source_order: 1 },
      { event_id: 'demo-da-2', channel: 'call_transcript', text: 'You will be arrested. Stay on the call.', source_order: 2 },
      { event_id: 'demo-da-3', channel: 'call_transcript', text: 'Transfer money for verification and do not tell anyone.', source_order: 3 },
    ],
  },
  {
    id: 'fake-refund',
    title: 'Fake Refund progression',
    payment: { stated_purpose: 'Claimed merchant refund', amount: '999', recipient_reference: 'Personal UPI recipient' },
    events: [
      { event_id: 'demo-fr-1', channel: 'whatsapp', text: 'Your refund has been approved.', source_order: 1 },
      { event_id: 'demo-fr-2', channel: 'whatsapp', text: 'Pay a processing fee to receive your refund.', source_order: 2 },
      { event_id: 'demo-fr-3', channel: 'whatsapp', text: 'Send it to a different account and share your OTP.', source_order: 3 },
    ],
  },
  {
    id: 'unsupported',
    title: 'Assessment failure journey',
    payment: { stated_purpose: 'Unknown request' },
    events: [{ event_id: 'demo-u-1', channel: 'sms', text: 'A completely unfamiliar synthetic message.', source_order: 1 }],
  },
]

export const revealedPrefix = (scenario: DemoScenario, count: number): EventInput[] =>
  scenario.events.slice(0, count).map((event) => ({ ...event }))
