import { requestJson } from "@/lib/http-client";
import type { SlackIntegrationStatus } from "./types";

export function getSlackIntegration() {
  return requestJson<SlackIntegrationStatus>("/api/integrations/slack");
}

export function beginSlackInstallation() {
  return requestJson<{ authorize_url: string }>("/api/integrations/slack/install", { method: "POST" });
}

export function disconnectSlackInstallation(installationId: string) {
  return requestJson<void>(`/api/integrations/slack/${encodeURIComponent(installationId)}`, { method: "DELETE" });
}
