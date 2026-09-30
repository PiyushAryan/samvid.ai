export interface SlackInstallation {
  id: string;
  team_id: string;
  team_name: string | null;
  status: "active" | "revoked" | "disconnected" | string;
  created_at?: string | null;
}

export interface SlackIntegrationStatus {
  enabled: boolean;
  installations: SlackInstallation[];
}
