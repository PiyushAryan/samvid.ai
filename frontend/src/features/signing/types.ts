export type SignerStatus = "pending" | "sent" | "viewed" | "signed" | "declined" | "expired" | "cancelled";
export type SigningRequestStatus = "not_started" | "in_progress" | "completed" | "declined" | "expired" | "cancelled";

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
