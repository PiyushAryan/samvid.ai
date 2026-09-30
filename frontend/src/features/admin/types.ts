export type AdminAccountState = "unclaimed" | "active";
export type AdminAccountSource = "signup" | "inbound_email" | "inbound_slack";

export interface AdminUserSummary {
  id: string;
  email: string;
  name: string;
  role: "user" | "super_admin";
  state: AdminAccountState;
  source: AdminAccountSource;
  workspace_id: string | null;
  contract_count: number;
  claimed_at: string | null;
  created_at: string;
  updated_at?: string;
}

export interface AdminUserDetail extends AdminUserSummary {
  auth_subject?: string | null;
  latest_contract_at?: string | null;
}

export interface AdminAccessEvent {
  id: string;
  actor_account_id: string;
  actor_email?: string | null;
  target_user_id?: string | null;
  target_user_email?: string | null;
  contract_id?: string | null;
  contract_title?: string | null;
  workspace_id?: string | null;
  event_type: string;
  metadata?: Record<string, unknown> | null;
  created_at: string;
}

export interface AdminCollection<T> {
  items: T[];
  total: number;
  page?: number;
  page_size?: number;
}

export type CollectionResponse<T> = T[] | AdminCollection<T>;
