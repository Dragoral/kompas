export type Role = 'doctor' | 'patient' | 'admin'
export type Severity = 'critical' | 'high' | 'medium'
export type ReferralLevel = 'mandatory' | 'desirable'

export interface User {
  id: number
  login: string
  role: Role
  full_name: string
  specialty: string | null
  is_duty: boolean
  mfa_enabled: boolean
}

export interface LoginResponse {
  token: string
  user: User
  expires_in: number
}

export interface Regimen {
  dose_mg?: number
  times_per_day?: number
  daily_mg?: number
  max_daily_mg?: number
  timing?: string
  duration?: string
}

export interface Diagnosis {
  icd10: string
  title?: string
}

export interface ScaleSummary {
  score: number
  band: string | null
  severity: number | null
  delta: number | null
}

export interface PatientRow {
  id: number
  code: string
  full_name: string
  age: number | null
  sex: 'm' | 'f'
  diagnoses: Diagnosis[]
  risk_score: number
  monitoring_active: boolean
  therapy: string | null
  scales: Record<string, ScaleSummary>
  adherence_pct: number | null
  alerts: Partial<Record<Severity, number>>
  referral: ReferralLevel | null
  pending_actions: number
  last_diary_days: number | null
}

export interface Alert {
  id: number
  patient_id: number
  patient_name: string | null
  rule_id: string
  severity: Severity
  title: string
  message: string | null
  status: string
  created_at: string
  acknowledged_at: string | null
  escalated_to: number | null
}

export interface ClinicalAction {
  id: number
  patient_id: number
  kind: string
  level: ReferralLevel | null
  title: string
  status: string
  created_at: string
}

export interface Prescription {
  id: number
  drug_id: string
  trade_name: string
  regimen: Regimen | null
  status: string
  off_label: boolean
  mode: string
  started_at: string
  stopped_at: string | null
}

export interface PatientCard {
  header: {
    full_name: string
    age: number | null
    sex: 'm' | 'f'
    bmi: number | null
    diagnoses: Diagnosis[]
    medications: { name: string; regimen?: Regimen; dose?: string; prescribed_here: boolean }[]
    allergies: string[]
  }
  patient: {
    id: number
    code: string
    monitoring_active: boolean
    in_person_visit_at: string | null
  }
  context: {
    scales: Record<string, ScaleSummary & { days_ago: number | null; count: number }>
    adherence: { pct_14d: number | null; missed_streak: number }
  }
  prescriptions: Prescription[]
  alerts: Alert[]
  actions: ClinicalAction[]
  assignments: { id: number; scale_code: string; every_days: number | null; next_due: string | null; reason: string | null }[]
}

export interface RouteReason {
  id: string
  title: string
  level: ReferralLevel
  source: string | null
}

export interface Route {
  target: string
  title: string
  level: ReferralLevel | null
  urgency: string | null
  reasons: RouteReason[]
}

export interface Finding {
  title?: string
  text?: string
  severity?: string
  source?: string
}

export interface DrugAssessment {
  drug_id: string
  trade_name: string
  inn: string
  status: 'indicated' | 'off_label' | 'contraindicated'
  regimen: Regimen | null
  contraindications: Finding[]
  cautions: Finding[]
  interactions: Finding[]
  note: string
}

export interface Recommendations {
  drugs: DrugAssessment[]
  routing: { routes: Route[]; verified: boolean } | null
  guidelines_note: string | null
}

export interface ScaleOption {
  value: number
  label: string
}

export interface ScaleItem {
  n: number
  text: string
  type?: 'choice' | 'yes_no' | 'number'
  options?: ScaleOption[]
  min?: number
  max?: number
  required?: boolean
}

export interface ScaleDefinition {
  code: string
  title: string
  respondent: 'patient' | 'clinician'
  period?: string
  options?: ScaleOption[]
  items: ScaleItem[]
}

export interface ScaleResult {
  id: number
  score: number
  band: string | null
  crisis: boolean
}

export interface Overview {
  patient: { id: number; full_name: string; code: string }
  doctor: { full_name: string; specialty: string | null }
  consent: { accepted: boolean; version: string | null; current_version: string }
  monitoring_active: boolean
  therapy: { id: number; trade_name: string; regimen: Regimen | null; special_instructions: string[] } | null
  doses_today: { id: number; scheduled_for: string; status: string }[]
  due_scales: { code: string; title: string; reason: string | null }[]
  diary_done_today: boolean
  crisis: boolean
  crisis_contacts: { title: string; phone: string }[]
  unread_messages: number
}

export interface ConsentText {
  version: string
  sha256: string
  text: string
}

export interface KnowledgeRow {
  kind: string
  code: string
  version: number
  active: boolean
  updated_at: string
  title: string
  verified: boolean | null
  has_draft: boolean
}

export interface KnowledgeDraft {
  id: number
  kind: string
  code: string
  change_note: string | null
  proposed_at: string
  proposed_by: number | null
  current_version: number | null
}

export interface ValidationResult {
  valid: boolean
  errors: { path: string; message: string }[]
  warnings: { path: string; message: string }[]
}

export interface ImportResult {
  draft: Record<string, unknown>
  todo: string[]
  errors: { path: string; message: string }[]
  warnings: { path: string; message: string }[]
}

export interface StaffUser {
  id: number
  login: string
  role: Role
  full_name: string
  specialty: string | null
  is_duty: boolean
  is_reviewer: boolean
  active: boolean
  mfa_enabled: boolean
  locked_until: string | null
}

export interface SystemStatus {
  environment: string
  database: string
  uptime_s: number
  checks: Record<string, { ok: boolean; [key: string]: unknown }>
  problems: { ts: number; component: string; ref: string; error: string; level: string; request_id: string | null }[]
  queues: Record<string, number>
  knowledge_drafts_pending: number
  backups: { count: number; latest: string | null }
  checked_at: string
}
