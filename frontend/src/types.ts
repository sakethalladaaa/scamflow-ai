export type Channel = 'sms' | 'whatsapp' | 'call_transcript' | 'email' | 'other_text'
export type AssessmentState =
  | 'high_risk_indicators'
  | 'needs_clarification_or_review'
  | 'no_strong_indicators'
  | 'unable_to_assess'

export interface EventInput { event_id: string; channel: Channel; text: string; source_order: number }
export interface StoredEvent extends EventInput { ingested_at: string }
export interface PaymentContext { stated_purpose: string; amount?: string | null; recipient_reference?: string | null }
export interface CaseRecord {
  case_id: string
  consent_version: string
  consented_at: string
  payment_context: PaymentContext
  revision: number
  created_at: string
  updated_at: string
  expires_at: string
  events: StoredEvent[]
}
export interface AssessmentEvidence {
  tactic: string; event_id: string; source_order: number; quote: string
  start_offset: number; end_offset: number; context: string
}
export interface Assessment {
  assessment_id: string; case_id: string; assessed_revision: number; state: AssessmentState
  reason_codes: string[]; explanation: string; evidence: AssessmentEvidence[]
  alert: { visible: boolean; reason: string; prior_warning_state: AssessmentState | null }
  tactics_used: string[]; relationships: string[]; suggested_next_action: string
  limitations: string[]; extraction_mode: string; extraction_version: string
  rule_version: string; schema_version: string; created_at: string
  is_current: boolean; idempotent_replay: boolean
}
