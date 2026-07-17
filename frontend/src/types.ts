export type ReviewStatus = "received" | "validating" | "queued" | "parsing" | "analysing" | "validating_evidence" | "review_ready" | "ocr_required" | "parse_failed" | "analysis_failed" | "rejected_file";

export type SignerStatus = "pending" | "sent" | "viewed" | "signed" | "declined" | "expired" | "cancelled";

export type SigningRequestStatus = "not_started" | "in_progress" | "completed" | "declined" | "expired" | "cancelled";

export type RiskSeverity = "critical" | "high" | "medium" | "low";

export interface SigningSummary {
  active_request_id: string | null;
  status: SigningRequestStatus | null;
  required_signed: number;
  required_total: number;
  signer_total: number;
}

export interface ContractListItem {
  id: string;
  title: string;
  review_status: ReviewStatus | string;
  created_by: string;
  created_at: string;
  updated_at: string;
  current_version_id: string | null;
  original_filename: string | null;
  mime_type: string | null;
  risk_counts: Record<RiskSeverity, number>;
  signing_summary: SigningSummary;
}

export interface Evidence {
  page_number: number;
  exact_text: string;
  bbox?: Record<string, unknown> | null;
}

export interface ContractReview {
  contract_id: string;
  contract_type: string;
  parties: Array<{ name: string; role?: string | null; evidence?: Evidence | null }>;
  key_terms: Array<{ name: string; value: string | null; evidence?: Evidence | null; confidence: number }>;
  risks: Array<{
    title: string;
    severity: RiskSeverity;
    clause_type: string;
    explanation: string;
    recommendation: string;
    evidence: Evidence;
    confidence: number;
  }>;
  recommended_next_action: string;
  limitations: string[];
}

export interface ContractDetail extends ContractListItem {
  current_version: {
    id: string;
    original_filename: string;
    mime_type: string;
    size_bytes: number;
    sha256: string;
    created_at: string;
  } | null;
  review: ContractReview | null;
  signing_requests: SigningRequest[];
}

export interface SignerEvent {
  id: string;
  signer_id: string;
  status: SignerStatus;
  note: string | null;
  actor_email: string;
  actor_name: string;
  created_at: string;
}

export interface Signer {
  id: string;
  name: string;
  email: string;
  role: string | null;
  required: boolean;
  display_order: number;
  latest_status: SignerStatus;
  created_at: string;
  events: SignerEvent[];
}

export interface SigningRequest {
  id: string;
  workspace_id: string;
  contract_id: string;
  contract_title?: string | null;
  contract_version_id: string;
  status: SigningRequestStatus;
  active: boolean;
  created_by: string;
  created_at: string;
  closed_at: string | null;
  signers: Signer[];
}

export interface SignerDraft {
  name: string;
  email: string;
  role: string;
  required: boolean;
}
