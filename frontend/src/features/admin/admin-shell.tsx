"use client";

import { ClipboardList, LogOut, Moon, PanelLeft, Sun, Users } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Link, NavLink, useNavigate } from "@/lib/navigation";
import { useAuth } from "@/features/auth/auth-provider";
import { setFaviconTheme } from "@/lib/favicon";
import { cx } from "./ui";

function getInitialTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  const saved = window.localStorage.getItem("samvid-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function AdminShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(getInitialTheme);
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const reducedMotion = useReducedMotion();
  const transition = reducedMotion ? { duration: 0 } : { duration: 0.28, ease: [0.22, 1, 0.36, 1] as const };
  const adminName = user?.name || "Samvid admin";
  const adminEmail = user?.email || "";

  useEffect(() => {
    window.localStorage.setItem("samvid-theme", theme);
    document.documentElement.dataset.appTheme = theme;
    document.documentElement.style.colorScheme = theme;
    setFaviconTheme(theme);
  }, [theme]);

  useEffect(() => () => {
    delete document.documentElement.dataset.appTheme;
    document.documentElement.style.removeProperty("color-scheme");
  }, []);

  return (
    <motion.div
      className={cx("app-shell", "admin-shell", collapsed && "sidebar-collapsed")}
      data-theme={theme}
      initial={false}
      animate={{ "--sidebar-width": collapsed ? "68px" : "232px" }}
      transition={transition}
    >
      <aside className="sidebar admin-sidebar">
        <div className="sidebar-brand-row">
          <Link to="/admin" className="brand" aria-label="Samvid administration">
            <img
              className="brand-mark brand-mark-image"
              src={theme === "dark" ? "/favicon-dark.svg" : "/favicon-light.svg"}
              alt=""
              aria-hidden="true"

            />
            <motion.span
              className="brand-copy"
              initial={false}
              animate={collapsed ? { width: 0, opacity: 0 } : { width: "auto", opacity: 1 }}
              transition={transition}
              aria-hidden={collapsed}
            >
              <strong>Samvid</strong>
              <small className="brand-caption">Platform Overview</small>
            </motion.span>
          </Link>
          <button
            className="icon-button sidebar-toggle"
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-pressed={collapsed}
          >
            <PanelLeft size={16} strokeWidth={1.7} aria-hidden="true" />
          </button>
        </div>

        <nav className="sidebar-nav admin-sidebar-nav" aria-label="Administration">
          <NavLink to="/admin/users" className="nav-link">
            <Users size={17} aria-hidden="true" />
            <span className="nav-label">Users</span>
          </NavLink>
          <NavLink to="/admin/access-events" className="nav-link">
            <ClipboardList size={17} aria-hidden="true" />
            <span className="nav-label">Access log</span>
          </NavLink>
        </nav>

        <div className="admin-sidebar-footer">
          {!collapsed && (
            <div className="admin-sidebar-identity">
              <span title={adminName}>{adminName}</span>
              {adminEmail && <small title={adminEmail}>{adminEmail}</small>}
            </div>
          )}
          <div className="admin-sidebar-actions">
            <button
              className="icon-button"
              type="button"
              onClick={() => setTheme((value) => value === "light" ? "dark" : "light")}
              aria-label={theme === "dark" ? "Use light theme" : "Use dark theme"}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <button
              className="icon-button"
              type="button"
              onClick={() => void signOut().finally(() => navigate("/auth", { replace: true }))}
              aria-label="Sign out"
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <main className="workspace-main admin-main">
        {children}
      </main>
    </motion.div>
  );
}

