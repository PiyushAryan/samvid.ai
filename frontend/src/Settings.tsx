"use client";

import { HugeiconsIcon } from "@hugeicons/react";
import { ConnectIcon, Plug01Icon, User03Icon } from "@hugeicons/core-free-icons";
import { useState } from "react";
import { useAuth } from "./AuthProvider";
import { IntegrationsPanel } from "./Integrations";

type SettingsTab = "profile" | "integrations" | "plugins";


function ProfilePanel() {
  const { user } = useAuth();
  const name = user?.name || "Samvid user";
  const email = user?.email || "No email available";
  const initials = name.trim().split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase() || "SU";

  return (
    <div className="settings-content-panel">
      <header className="settings-content-header">
        <h1>Profile settings</h1>
        <p>Manage your personal information and account preferences.</p>
      </header>

      <section className="settings-profile-card" aria-label="Profile summary">
        <div className="settings-avatar" aria-hidden="true">{initials}</div>
        <strong>{name}</strong>
        <button className="secondary compact" type="button" disabled>Edit</button>
      </section>

      <section className="settings-account-card" aria-label="Account details">
        <h2>Account</h2>
        <div className="settings-account-row">
          <span><small>Email</small><strong>{email}</strong></span>
          <span className="settings-verified">Verified</span>
        </div>
        <div className="settings-account-row">
          <span><small>Password</small><strong aria-label="Password hidden">••••••••••••</strong></span>
          <button className="secondary compact" type="button" disabled>Change password</button>
        </div>
      </section>
    </div>
  );
}

function PluginsPanel() {
  return (
    <div className="settings-content-panel">
      <header className="settings-content-header">
        <h1>Plugins</h1>
        <p>Manage plugins available to your workspace.</p>
      </header>
      <section className="settings-empty-card">
        No plugins are installed yet.
      </section>
    </div>
  );
}

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("profile");

  return (
    <main className="settings-page">
      <div className="settings-page-content page">
        <aside className="settings-nav" aria-label="Settings navigation">
        <h1>Settings</h1>
        <nav>
          <button
            className="settings-nav-item"
            data-active={activeTab === "profile"}
            type="button"
            aria-current={activeTab === "profile" ? "page" : undefined}
            onClick={() => setActiveTab("profile")}
          >
            <HugeiconsIcon icon={User03Icon} size={18} strokeWidth={1.8} aria-hidden="true" />
            <span>Profile</span>
          </button>
          <button
            className="settings-nav-item"
            data-active={activeTab === "integrations"}
            type="button"
            aria-current={activeTab === "integrations" ? "page" : undefined}
            onClick={() => setActiveTab("integrations")}
          >
            <HugeiconsIcon icon={ConnectIcon} size={18} strokeWidth={1.8} aria-hidden="true" />
            <span>Integrations</span>
          </button>
          <button
            className="settings-nav-item"
            data-active={activeTab === "plugins"}
            type="button"
            aria-current={activeTab === "plugins" ? "page" : undefined}
            onClick={() => setActiveTab("plugins")}
          >
            <HugeiconsIcon icon={Plug01Icon} size={18} strokeWidth={1.8} aria-hidden="true" />
            <span>Plugins</span>
          </button>
        </nav>
        </aside>

        {activeTab === "profile" ? <ProfilePanel /> : activeTab === "integrations" ? (
          <div className="settings-content-panel">
            <header className="settings-content-header">
              <h1>Integrations</h1>
              <p>Connect the tools your workspace uses to keep contract work moving.</p>
            </header>
            <IntegrationsPanel />
          </div>
        ) : <PluginsPanel />}
      </div>
    </main>
  );
}
