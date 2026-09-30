"use client";

import { Component, FileText, History, LogOut, MessageCircleMore, Moon, PanelLeft, Settings, Sun, ChevronsUpDown } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Link, NavLink, useLocation, useNavigate } from "@/lib/navigation";
import { useAuth } from "@/features/auth/auth-provider";
import { SidebarChatHistory } from "@/features/chat/sidebar-chat-history";
import { setFaviconTheme } from "@/lib/favicon";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const MotionPanelLeft = motion.create(PanelLeft);
const MotionFileText = motion.create(FileText);
const MotionHistory = motion.create(History);
const iconButton = "icon-button";

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function AppShell({ children }: { children: ReactNode }) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarMenuOpen, setSidebarMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const accountName = user?.name || "Samvid user";
  const accountEmail = user?.email || "";
  const workspaceView = location.pathname.startsWith("/chats") ? "chats" : "console";
  const activeChatId = new URLSearchParams(location.search).get("chat");
  const sidebarMenuRef = useRef<HTMLDivElement>(null);
  const sidebarMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    if (typeof window === "undefined") return "light";

    const savedTheme = window.localStorage.getItem("samvid-theme");
    if (savedTheme === "light" || savedTheme === "dark") return savedTheme;

    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const reduceMotion = useReducedMotion();
  const sidebarTransition = reduceMotion
    ? { duration: 0 }
    : { duration: 0.3, ease: [0.22, 1, 0.36, 1] as const };

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

  useEffect(() => {
    if (!sidebarMenuOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!sidebarMenuRef.current?.contains(event.target as Node)) {
        setSidebarMenuOpen(false);
      }
    };
    const handleEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setSidebarMenuOpen(false);
        sidebarMenuTriggerRef.current?.focus();
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [sidebarMenuOpen]);

  const focusSidebarMenuItem = (position: "first" | "last") => {
    window.requestAnimationFrame(() => {
      const items = sidebarMenuRef.current?.querySelectorAll<HTMLButtonElement>(".sidebar-menu-item");
      if (!items?.length) return;
      items[position === "first" ? 0 : items.length - 1].focus();
    });
  };

  const handleSidebarMenuTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setSidebarMenuOpen(true);
      focusSidebarMenuItem(event.key === "ArrowDown" ? "first" : "last");
    }
  };

  const handleSidebarMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Home" && event.key !== "End") {
      return;
    }

    event.preventDefault();
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".sidebar-menu-item"));
    if (!items.length) return;
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement);
    let nextIndex = currentIndex;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = items.length - 1;
    if (event.key === "ArrowDown") nextIndex = (currentIndex + 1) % items.length;
    if (event.key === "ArrowUp") nextIndex = (currentIndex - 1 + items.length) % items.length;
    items[nextIndex].focus();
  };

  return (
    <motion.div
      className={cx("app-shell", sidebarCollapsed && "sidebar-collapsed")}
      data-theme={theme}
      initial={false}
      animate={{ "--sidebar-width": sidebarCollapsed ? "68px" : "248px" }}
      transition={sidebarTransition}
    >
      <aside className={cx("sidebar", workspaceView === "chats" && "sidebar--chats")}>
        <div className="sidebar-brand-row">
          <Link to="/chats" className="brand" aria-label="Samvid workspace">
            <motion.span
              className="brand-mark"
              aria-hidden="true"
              layout="position"
              transition={sidebarTransition}
            >
              S
            </motion.span>
            <motion.span
              className="brand-copy"
              initial={false}
              animate={sidebarCollapsed
                ? { width: 0, opacity: 0, x: -6 }
                : { width: "auto", opacity: 1, x: 0 }}
              transition={sidebarTransition}
              aria-hidden={sidebarCollapsed}
            >
              <strong>Samvid</strong>
              <small className="brand-caption">Contract workspace</small>
            </motion.span>
          </Link>
          <div className="sidebar-menu-controls">
            <div className="sidebar-menu" ref={sidebarMenuRef}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    ref={sidebarMenuTriggerRef}
                    className={cx(iconButton, "sidebar-menu-trigger")}
                    type="button"
                    aria-label={sidebarMenuOpen ? "Close sidebar actions" : "Open sidebar actions"}
                    aria-haspopup="menu"
                    aria-expanded={sidebarMenuOpen}
                    aria-controls="sidebar-actions-menu"
                    onClick={() => setSidebarMenuOpen((open) => !open)}
                    onKeyDown={handleSidebarMenuTriggerKeyDown}
                  >
                    <ChevronsUpDown size={16} strokeWidth={1.7} aria-hidden="true" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">Sidebar actions</TooltipContent>
              </Tooltip>
              {sidebarMenuOpen && (
                <div
                  id="sidebar-actions-menu"
                  className="sidebar-menu-popover"
                  role="menu"
                  aria-label="Sidebar actions"
                  onKeyDown={handleSidebarMenuKeyDown}
                >
                  <p className="sidebar-menu-eyebrow">Account</p>
                  <button
                    className="sidebar-menu-item sidebar-account"
                    type="button"
                    role="menuitem"
                    aria-label={`Account: ${accountName}`}
                    aria-disabled="true"
                    title="Account management is not available yet"
                  >
                    <span className="sidebar-account-avatar" aria-hidden="true">
                      {accountName.trim().charAt(0).toUpperCase()}
                    </span>
                    <span className="sidebar-account-copy">
                      <span className="sidebar-account-title">
                        <strong>{accountName}</strong>
                      </span>
                      <small className="sidebar-account-email">{accountEmail}</small>
                    </span>
                  </button>
                  <div className="sidebar-menu-actions" role="group" aria-label="Account actions">
                    <button
                      className="sidebar-menu-item sidebar-menu-action"
                      type="button"
                      role="menuitem"
                    aria-label="Settings"
                    title="Integrations and settings"
                    onClick={() => {
                      setSidebarMenuOpen(false);
                      navigate("/settings");
                    }}
                    >
                      <Settings size={19} aria-hidden="true" />
                    </button>
                    <button
                      className="sidebar-menu-item sidebar-menu-action"
                      type="button"
                      role="menuitemcheckbox"
                      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
                      aria-checked={theme === "dark"}
                      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
                      onClick={() => {
                        setTheme((currentTheme) => currentTheme === "light" ? "dark" : "light");
                        setSidebarMenuOpen(false);
                      }}
                    >
                      {theme === "dark"
                        ? <Sun size={19} aria-hidden="true" />
                        : <Moon size={19} aria-hidden="true" />}
                    </button>
                    <button
                      className="sidebar-menu-item sidebar-menu-action sidebar-menu-logout"
                      type="button"
                      role="menuitem"
                      aria-label="Logout"
                      title="Sign out"
                      onClick={() => {
                        setSidebarMenuOpen(false);
                        void signOut().finally(() => navigate("/auth", { replace: true }));
                      }}
                    >
                      <LogOut size={19} aria-hidden="true" />
                    </button>
                  </div>
                </div>
              )}
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <motion.button
                  className={cx(iconButton, "sidebar-toggle")}
                  type="button"
                  onClick={() => {
                    setSidebarMenuOpen(false);
                    setSidebarCollapsed((collapsed) => !collapsed);
                  }}
                  aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                  aria-pressed={sidebarCollapsed}
                  layout="position"
                  transition={sidebarTransition}
                >
                  <MotionPanelLeft
                    size={16}
                    strokeWidth={1.7}
                    aria-hidden="true"
                    initial={false}
                    animate={{ rotate: sidebarCollapsed ? 180 : 0 }}
                    transition={sidebarTransition}
                  />
                </motion.button>
              </TooltipTrigger>
              {sidebarCollapsed && <TooltipContent side="right">Expand sidebar</TooltipContent>}
            </Tooltip>
          </div>
        </div>
        <nav className="sidebar-nav">
          <div
            className="sidebar-view-switch"
            data-active={workspaceView}
            role="group"
            aria-label="Workspace view"
          >
            <span className="sidebar-view-indicator" aria-hidden="true" />
            <button
              type="button"
              className="sidebar-view-option"
              aria-pressed={workspaceView === "console"}
              onClick={() => navigate("/contracts")}
            >
              <Component size={15} aria-hidden="true" />
              <span className="sidebar-view-label">console</span>
            </button>
            <button
              type="button"
              className="sidebar-view-option"
              aria-pressed={workspaceView === "chats"}
              onClick={() => navigate("/chats")}
            >
              <MessageCircleMore size={15} aria-hidden="true" />
              <span className="sidebar-view-label">chats</span>
            </button>
          </div>
          {workspaceView === "chats" && (
            <SidebarChatHistory
              activeChatId={activeChatId}
              onSelect={(chatId) => navigate(chatId ? `/chats?chat=${encodeURIComponent(chatId)}` : "/chats")}
            />
          )}
          {workspaceView === "console" && (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <NavLink
                    to="/contracts"
                    aria-label="Contracts"
                    className="nav-link"
                  >
                    <MotionFileText size={17} layout="position" transition={sidebarTransition} />
                    <motion.span
                      className="nav-label"
                      initial={false}
                      animate={sidebarCollapsed
                        ? { width: 0, opacity: 0, x: -5 }
                        : { width: "auto", opacity: 1, x: 0 }}
                      transition={sidebarTransition}
                      aria-hidden={sidebarCollapsed}
                    >
                      Contracts
                    </motion.span>
                  </NavLink>
                </TooltipTrigger>
                {sidebarCollapsed && <TooltipContent side="right">Contracts</TooltipContent>}
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <NavLink
                    to="/signing"
                    aria-label="Signing"
                    className="nav-link"
                  >
                    <MotionHistory size={17} layout="position" transition={sidebarTransition} />
                    <motion.span
                      className="nav-label"
                      initial={false}
                      animate={sidebarCollapsed
                        ? { width: 0, opacity: 0, x: -5 }
                        : { width: "auto", opacity: 1, x: 0 }}
                      transition={sidebarTransition}
                      aria-hidden={sidebarCollapsed}
                    >
                      Signing
                    </motion.span>
                  </NavLink>
                </TooltipTrigger>
                {sidebarCollapsed && <TooltipContent side="right">Signing</TooltipContent>}
              </Tooltip>
            </>
          )}
        </nav>
        {workspaceView === "console" && (
          <motion.p
            className="tracking-note"
            initial={false}
            animate={sidebarCollapsed
              ? { height: 0, opacity: 0, paddingTop: 0 }
              : { height: "auto", opacity: 1, paddingTop: 12 }}
            transition={sidebarTransition}
            aria-hidden={sidebarCollapsed}
          >
            Tracking only. Samvid does not execute electronic signatures.
          </motion.p>
        )}
      </aside>
      <main className="workspace-main">
        {children}
      </main>
    </motion.div>
  );
}

