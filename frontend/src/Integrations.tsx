"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Unplug } from "lucide-react";

import {
  ApiError,
  beginSlackInstallation,
  disconnectSlackInstallation,
  getSlackIntegration
} from "./api";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.payload.message || (typeof error.payload.detail === "string" ? error.payload.detail : error.message);
  }
  return error instanceof Error ? error.message : "The integration request could not be completed.";
}

export function IntegrationsPanel() {
  const queryClient = useQueryClient();
  const integration = useQuery({ queryKey: ["slack-integration"], queryFn: getSlackIntegration });
  const install = useMutation({
    mutationFn: beginSlackInstallation,
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url)
  });
  const disconnect = useMutation({
    mutationFn: disconnectSlackInstallation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["slack-integration"] })
  });
  const active = integration.data?.installations.filter((item) => item.status === "active") || [];
  const connected = active.length > 0;
  const mutationError = install.error || disconnect.error;

  return (
    <section className="integration-card" aria-labelledby="slack-integration-title">
        <div className="integration-heading">
          <span className="integration-icon" aria-hidden="true">
            <img src="/250px-Slack_icon_2019.svg.webp" alt="" />
          </span>
          <div>
            <div className="integration-title-row">
              <h2 id="slack-integration-title">Slack</h2>
              <span className={`integration-status ${connected ? "is-connected" : ""}`}>
                {connected ? "Connected" : "Not Connected"}
              </span>
            </div>
            <p>Send a contract in a direct message or mention Samvid with an attachment.</p>
          </div>
        </div>

        {integration.isPending ? (
          <p className="integration-state"><Loader2 className="spin" size={16} aria-hidden="true" /> Loading Slack workspaces…</p>
        ) : integration.isError ? (
          <div className="integration-error" role="alert">
            <p>{errorMessage(integration.error)}</p>
            <button className="secondary compact" type="button" onClick={() => void integration.refetch()}>Retry</button>
          </div>
        ) : !integration.data.enabled ? (
          <p className="integration-state">Slack is not enabled for this Samvid deployment.</p>
        ) : (
          <>
            {active.length > 0 ? (
              <ul className="integration-list" aria-label="Connected Slack workspaces">
                {active.map((item) => (
                  <li key={item.id}>
                    <span><strong>{item.team_name || item.team_id}</strong><small>Connected</small></span>
                    <button
                      className="secondary compact"
                      type="button"
                      disabled={disconnect.isPending}
                      onClick={() => disconnect.mutate(item.id)}
                    >
                      {disconnect.isPending && disconnect.variables === item.id
                        ? <Loader2 className="spin" size={14} aria-hidden="true" />
                        : <Unplug size={14} aria-hidden="true" />}
                      Disconnect
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="integration-state">No Slack workspace is connected yet.</p>}

            <button className="primary integration-connect" type="button" disabled={install.isPending} onClick={() => install.mutate()}>
              {install.isPending && <Loader2 className="spin" size={14} aria-hidden="true" />}
              Connect
            </button>
          </>
        )}

        {mutationError && <p className="integration-error" role="alert">{errorMessage(mutationError)}</p>}
        <p className="integration-privacy">Samvid reads only files sent directly to it or attached to an explicit @mention.</p>
    </section>
  );
}

export function IntegrationsPage() {
  return (
    <main className="page integrations-page">
      <header className="page-header">
        <span>
          <small>Workspace settings</small>
          <h1>Integrations</h1>
        </span>
      </header>
      <IntegrationsPanel />
    </main>
  );
}
