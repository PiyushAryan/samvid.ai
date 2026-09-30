import type { SigningRequest, SigningRequestStatus } from "@/features/signing/types";

export type ReviewStatus = "received" | "validating" | "queued" | "parsing" | "analysing" | "validating_evidence" | "review_ready" | "ocr_required" | "parse_failed" | "analysis_failed" | "rejected_file";
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
