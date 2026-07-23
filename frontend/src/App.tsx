import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  ChevronsUpDown,
  Download,
  FileText,
  Filter,
  History,
  Loader2,
  LogOut,
  Moon,
  PanelLeft,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  MessageCircleMore,
  Component,
  SquarePen,
  Sun,
  Trash2,
  Upload,
  UserPlus,
  X,
  Undo2
} from "lucide-react";
import { FormEvent, KeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import {
  addSigner,
  ApiError,
  appendSignerEvent,
  createChatSession,
  createSigningRequest,
  deleteContract,
  getChatSession,
  getContract,
  getContractDocument,
  listChatSessions,
  listContracts,
  listSigningRequests,
  streamChatMessage,
  uploadContract
} from "./api";
import { useAuth } from "./AuthProvider";
import { setFaviconTheme } from "./favicon";
import type {
  ChatMessage,
  ChatSessionSummary,
  ContractDetail,
  ContractListItem,
  ContractReview,
  RiskSeverity,
  Signer,
  SignerDraft,
  SignerStatus,
  SigningRequest,
  SigningRequestStatus
} from "./types";
import { Skeleton } from "./components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "./components/ui/tooltip";

const MotionPanelLeft = motion.create(PanelLeft);
const MotionFileText = motion.create(FileText);
const MotionHistory = motion.create(History);

const signingStatuses: Array<SigningRequestStatus | ""> = ["", "not_started", "in_progress", "completed", "declined", "expired", "cancelled"];
const reviewStatuses = ["", "received", "validating", "queued", "parsing", "analysing", "validating_evidence", "review_ready", "ocr_required", "parse_failed", "analysis_failed"];
const activeReviewStatuses = new Set(["received", "validating", "queued", "parsing", "analysing", "validating_evidence"]);
const signerStatuses: SignerStatus[] = ["pending", "sent", "viewed", "signed", "declined", "expired", "cancelled"];
const terminalSignerStatuses: SignerStatus[] = ["signed", "declined", "expired", "cancelled"];

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

const mono = "mono";
const mutedText = "muted";
const primaryButton = "primary";
const secondaryButton = "secondary";
const iconButton = "icon-button";
const compactButton = "secondary compact";
const pageClass = "page";
const toolbarControl = "toolbar-control";
const toolbarInput = "toolbar-input";
const tableWrap = "table-wrap";
const tableClass = "data-table";
const thClass = "table-heading";
const tdClass = "table-cell";
const panelClass = "panel";
const panelCardClass = "panel panel-card";
const fieldLabelClass = "field";
const fieldControlClass = "field-control";

function SidebarChatHistory({
  activeChatId,
  onSelect
}: {
  activeChatId: string | null;
  onSelect: (chatId: string | null) => void;
}) {
  const sessionsQuery = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: listChatSessions
  });

  return (
    <section className="sidebar-chat-section" aria-labelledby="sidebar-chat-history-title">
      <button className="sidebar-new-chat" type="button" onClick={() => onSelect(null)}>
        <SquarePen size={16} aria-hidden="true" />
        <span>New chat</span>
      </button>
      <h2 id="sidebar-chat-history-title" className="sr-only">Chat history</h2>
      {sessionsQuery.isPending ? (
        <div className="sidebar-chat-loading" role="status" aria-label="Loading chat history">
          {[0, 1, 2].map((item) => <Skeleton key={item} className="sidebar-chat-skeleton" />)}
        </div>
      ) : sessionsQuery.isError ? (
        <div className="sidebar-chat-state" role="alert">
          <span>History unavailable</span>
          <button type="button" onClick={() => void sessionsQuery.refetch()}>Retry</button>
        </div>
      ) : sessionsQuery.data.length === 0 ? (
        <p className="sidebar-chat-empty">No conversations yet</p>
      ) : (
        <ul className="sidebar-chat-list">
          {sessionsQuery.data.map((session) => (
            <li key={session.id}>
              <button
                type="button"
                title={session.title}
                aria-current={activeChatId === session.id ? "page" : undefined}
                onClick={() => onSelect(session.id)}
              >
                {session.title}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AppShell() {
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
      <aside className="sidebar">
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
                      aria-disabled="true"
                      title="Settings are not available yet"
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
        <Outlet />
      </main>
    </motion.div>
  );
}

export function ChatsPage() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const activeChatId = searchParams.get("chat");
  const accountName = user?.name?.trim().split(/\s+/)[0] || "there";
  const [draft, setDraft] = useState("");
  const [liveConversation, setLiveConversation] = useState<{ sessionId: string; messages: ChatMessage[] } | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [streamError, setStreamError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const streamControllerRef = useRef<AbortController | null>(null);
  const sessionQuery = useQuery({
    queryKey: ["chat-session", activeChatId],
    queryFn: () => getChatSession(activeChatId!),
    enabled: Boolean(activeChatId)
  });
  const messages = liveConversation?.sessionId === activeChatId
    ? liveConversation.messages
    : sessionQuery.data?.messages || [];

  useEffect(() => {
    if (activeChatId && liveConversation?.sessionId === activeChatId) return;
    streamControllerRef.current?.abort();
    streamControllerRef.current = null;
    setLiveConversation((current) => current?.sessionId === activeChatId ? current : null);
    setStreamError("");
    setAnnouncement("");
    setIsSending(false);
  }, [activeChatId, liveConversation?.sessionId]);

  useEffect(() => () => streamControllerRef.current?.abort(), []);

  const submitMessage = async () => {
    const content = draft.trim();
    if (!content || isSending) return;

    setIsSending(true);
    setStreamError("");
    setAnnouncement("Searching your contracts");
    setDraft("");
    let sessionId = activeChatId;
    try {
      if (!sessionId) {
        const session = await createChatSession(chatTitle(content));
        sessionId = session.id;
        queryClient.setQueryData(["chat-session", session.id], session);
        queryClient.setQueryData<ChatSessionSummary[]>(["chat-sessions"], (current = []) => [session, ...current]);
        navigate(`/chats?chat=${encodeURIComponent(session.id)}`, { replace: true });
      }

      const now = new Date().toISOString();
      const userMessage: ChatMessage = {
        id: `pending-user-${crypto.randomUUID()}`,
        role: "user",
        content,
        sources: [],
        created_at: now
      };
      const assistantId = `pending-assistant-${crypto.randomUUID()}`;
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        sources: [],
        created_at: now
      };
      const baseMessages = sessionId === activeChatId ? messages : [];
      setLiveConversation({ sessionId, messages: [...baseMessages, userMessage, assistantMessage] });

      const controller = new AbortController();
      streamControllerRef.current = controller;
      await streamChatMessage(sessionId, content, {
        onDelta: (delta) => setLiveConversation((current) => updateChatMessage(current, sessionId!, assistantId, (message) => ({
          ...message,
          content: message.content + delta
        }))),
        onSources: (sources) => setLiveConversation((current) => updateChatMessage(current, sessionId!, assistantId, (message) => ({
          ...message,
          sources
        }))),
        onMessage: (message) => setLiveConversation((current) => updateChatMessage(current, sessionId!, assistantId, () => message))
      }, controller.signal);
      setAnnouncement("Answer ready");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["chat-sessions"] }),
        queryClient.invalidateQueries({ queryKey: ["chat-session", sessionId] })
      ]);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setStreamError(chatErrorMessage(error));
      setDraft(content);
      setLiveConversation((current) => current?.sessionId === sessionId
        ? { ...current, messages: current.messages.filter((message) => !message.id.startsWith("pending-assistant-")) }
        : current);
      setAnnouncement("Message was not completed");
    } finally {
      streamControllerRef.current = null;
      setIsSending(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitMessage();
  };

  return (
    <section className="ai-chat-page" aria-labelledby="ai-chat-title">
      <div className="ai-chat-content">
        <header className="ai-chat-header">
          <h1 id="ai-chat-title">Hello, {accountName}</h1>
          <p>{activeChatId && sessionQuery.data ? sessionQuery.data.title : "find anything about your contracts"}</p>
        </header>

        {activeChatId && sessionQuery.isPending && !liveConversation ? (
          <div className="ai-chat-conversation-state" role="status">
            <Loader2 className="spin" size={18} aria-hidden="true" />
            <span>Loading conversation</span>
          </div>
        ) : activeChatId && sessionQuery.isError && !liveConversation ? (
          <div className="ai-chat-conversation-state ai-chat-error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <strong>Conversation unavailable</strong>
            <span>{chatErrorMessage(sessionQuery.error)}</span>
            <button className={compactButton} type="button" onClick={() => void sessionQuery.refetch()}>Retry</button>
          </div>
        ) : messages.length > 0 ? (
          <div className="ai-chat-messages" aria-label="Contract chat conversation" aria-live="polite" aria-busy={isSending}>
            {messages.map((message) => (
              <article
                key={message.id}
                className={cx("ai-chat-message", `ai-chat-message-${message.role}`)}
              >
                <span className="ai-chat-message-role">
                  {message.role === "user" ? "You" : "Samvid"}
                </span>
                <p>{message.content || (isSending ? "Searching your contracts..." : "No response was returned.")}</p>
                {message.sources.length > 0 && (
                  <ul className="ai-chat-sources" aria-label="Sources">
                    {message.sources.map((source, index) => (
                      <li key={source.id || `${source.contract_id}-${source.page_number}-${index}`}>
                        <Link className="ai-chat-source" to={`/contracts/${encodeURIComponent(source.contract_id)}`}>
                          <FileText size={14} aria-hidden="true" />
                          <span>
                            <strong>{source.contract_title}</strong>
                            {source.page_number && <small>Page {source.page_number}</small>}
                          </span>
                          <ArrowUpRight size={13} aria-hidden="true" />
                        </Link>
                        {source.excerpt && <blockquote>{source.excerpt}</blockquote>}
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            ))}
          </div>
        ) : null}

        <form
          className="ai-chat-composer"
          onSubmit={handleSubmit}
        >
          <label className="ai-chat-label" htmlFor="ai-chat-prompt">
            Ask about a contract
          </label>
          <textarea
            id="ai-chat-prompt"
            className="ai-chat-textarea"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submitMessage();
              }
            }}
            placeholder="Ask a question about your contracts..."
            rows={1}
            disabled={isSending || Boolean(activeChatId && sessionQuery.isPending)}
          />

          <div className="ai-chat-composer-actions">
            <span className="ai-chat-context-note">Answers use your indexed contracts</span>
            <button
              className="ai-chat-send-button"
              type="submit"
              disabled={!draft.trim() || isSending || Boolean(activeChatId && sessionQuery.isPending)}
              aria-label="Send message"
            >
              {isSending ? <Loader2 className="spin" size={16} aria-hidden="true" /> : <Undo2 size={16} aria-hidden="true" />}
            </button>
          </div>
          {streamError && <p className="ai-chat-stream-error" role="alert">{streamError}</p>}
          <p className="ai-chat-status" role="status" aria-live="polite">
            {announcement}
          </p>
        </form>

        {!activeChatId && messages.length === 0 && (
          <div className="ai-chat-suggestions" aria-label="Suggested questions">
            <p>Try asking</p>
            <div>
              {[
                "What changed in my latest contract?",
                "Which contracts renew in the next 90 days?",
                "Summarize the risks in this agreement."
              ].map((suggestion) => (
                <button key={suggestion} type="button" onClick={() => setDraft(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function updateChatMessage(
  conversation: { sessionId: string; messages: ChatMessage[] } | null,
  sessionId: string,
  messageId: string,
  update: (message: ChatMessage) => ChatMessage
) {
  if (!conversation || conversation.sessionId !== sessionId) return conversation;
  return {
    ...conversation,
    messages: conversation.messages.map((message) => message.id === messageId ? update(message) : message)
  };
}

function chatTitle(content: string): string {
  const normalized = content.replace(/\s+/g, " ").trim();
  return normalized.length > 72 ? `${normalized.slice(0, 69)}...` : normalized;
}

function chatErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.payload.message) return error.payload.message;
    if (typeof error.payload.detail === "string") return error.payload.detail;
  }
  return error instanceof Error ? error.message : "Unable to reach Samvid AI. Please try again.";
}

export function ContractsPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [signingStatus, setSigningStatus] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const contractsQuery = useQuery({
    queryKey: ["contracts", search, reviewStatus, signingStatus],
    queryFn: () => listContracts({ search, reviewStatus, signingStatus }),
    refetchInterval: (query) =>
      query.state.data?.some((contract) => activeReviewStatuses.has(contract.review_status)) ? 3000 : false
  });

  return (
    <section className={pageClass}>
      <PageHeader
        eyebrow="Workspace"
        title="Contracts"
        action={
          <button className={primaryButton} onClick={() => setUploadOpen(true)}>
            <Upload size={16} /> Upload
          </button>
        }
      />
      <div className="toolbar" role="search">
        <label className="search-field">
          <Search size={16} />
          <input className={toolbarInput} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search contracts" />
        </label>
        <label className={toolbarControl}>
          <Filter size={16} />
          <select className={toolbarInput} value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value)} aria-label="Review status">
            {reviewStatuses.map((status) => (
              <option key={status || "all"} value={status}>
                {status ? label(status) : "All review statuses"}
              </option>
            ))}
          </select>
        </label>
        <label className={toolbarControl}>
          <History size={16} />
          <select className={toolbarInput} value={signingStatus} onChange={(event) => setSigningStatus(event.target.value)} aria-label="Signing status">
            {signingStatuses.map((status) => (
              <option key={status || "all"} value={status}>
                {status ? label(status) : "All signing statuses"}
              </option>
            ))}
          </select>
        </label>
        <button className={iconButton} onClick={() => contractsQuery.refetch()} aria-label="Refresh contracts">
          <RefreshCw size={16} />
        </button>
      </div>
      <QueryState query={contractsQuery} loadingFallback={<ContractsTableSkeleton />}>
        <ContractTable contracts={contractsQuery.data || []} />
      </QueryState>
      {uploadOpen && (
        <UploadDialog
          onClose={() => setUploadOpen(false)}
          onUploaded={() => {
            setUploadOpen(false);
            queryClient.invalidateQueries({ queryKey: ["contracts"] });
          }}
        />
      )}
    </section>
  );
}

export function ContractDetailPage() {
  const { contractId } = useParams();
  const [params, setParams] = useSearchParams();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const tab = params.get("tab") || "review";
  const contractQuery = useQuery({
    queryKey: ["contract", contractId],
    queryFn: () => getContract(contractId!),
    enabled: Boolean(contractId),
    refetchInterval: (query) =>
      query.state.data && activeReviewStatuses.has(query.state.data.review_status) ? 3000 : false
  });
  const documentQuery = useQuery({
    queryKey: ["contract-document", contractId],
    queryFn: () => getContractDocument(contractId!),
    enabled: Boolean(contractQuery.data?.current_version),
    staleTime: 5 * 60 * 1000
  });
  const documentUrl = useObjectUrl(documentQuery.data);

  return (
    <section className={pageClass}>
      <QueryState query={contractQuery}>
        {contractQuery.data && (
          <>
            <PageHeader
              eyebrow="Contract"
              title={contractQuery.data.title}
              action={
                <div className="page-header-actions">
                  <a
                    className={secondaryButton}
                    href={documentUrl || undefined}
                    target="_blank"
                    rel="noreferrer"
                    aria-disabled={!documentUrl}
                  >
                    Open original <ArrowUpRight size={15} />
                  </a>
                  <button className="destructive" type="button" onClick={() => setDeleteOpen(true)}>
                    <Trash2 size={15} aria-hidden="true" /> Delete
                  </button>
                </div>
              }
            />
            <div className="tabs" role="tablist">
              {["review", "document", "signing"].map((value) => (
                <button
                  key={value}
                  className={cx("tab", tab === value && "active")}
                  onClick={() => setParams({ tab: value })}
                  role="tab"
                  aria-selected={tab === value}
                >
                  {label(value)}
                </button>
              ))}
            </div>
            {tab === "review" && <ReviewTab review={contractQuery.data.review} />}
            {tab === "document" && (
              <DocumentTab
                contract={contractQuery.data}
                url={documentUrl}
                isLoading={documentQuery.isLoading}
                error={documentQuery.error instanceof Error ? documentQuery.error.message : null}
              />
            )}
            {tab === "signing" && <SigningTab contract={contractQuery.data} />}
            {deleteOpen && (
              <DeleteContractDialog
                contract={contractQuery.data}
                onClose={() => setDeleteOpen(false)}
                onDeleted={() => {
                  queryClient.removeQueries({ queryKey: ["contract", contractId] });
                  queryClient.removeQueries({ queryKey: ["contract-document", contractId] });
                  queryClient.invalidateQueries({ queryKey: ["contracts"] });
                  queryClient.invalidateQueries({ queryKey: ["signing-requests"] });
                  queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
                  navigate("/contracts", { replace: true });
                }}
              />
            )}
          </>
        )}
      </QueryState>
    </section>
  );
}

function DeleteContractDialog({
  contract,
  onClose,
  onDeleted
}: {
  contract: ContractDetail;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const mutation = useMutation({
    mutationFn: () => deleteContract(contract.id),
    onSuccess: onDeleted
  });

  return (
    <Dialog title="Delete contract" onClose={onClose}>
      <div className="delete-contract-warning">
        <span className="delete-contract-icon" aria-hidden="true"><Trash2 size={18} /></span>
        <div>
          <strong>This permanently removes {contract.title}.</strong>
          <p>
            The original document, review, extracted knowledge, signing history, and contract-linked conversations
            will be deleted. This action cannot be undone.
          </p>
        </div>
      </div>
      <div className="dialog-actions">
        <button className={secondaryButton} type="button" onClick={onClose} disabled={mutation.isPending}>
          Cancel
        </button>
        <button className="destructive" type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          {mutation.isPending ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
          Permanently delete
        </button>
      </div>
      <MutationError mutation={mutation} />
    </Dialog>
  );
}

export function SigningPage() {
  const [status, setStatus] = useState<SigningRequestStatus | "">("");
  const signingQuery = useQuery({
    queryKey: ["signing-requests", status],
    queryFn: () => listSigningRequests(status)
  });
  return (
    <section className={pageClass}>
      <PageHeader eyebrow="Signer tracking" title="Signing requests" />
      <div className="toolbar">
        <label className={toolbarControl}>
          <Filter size={16} />
          <select className={toolbarInput} value={status} onChange={(event) => setStatus(event.target.value as SigningRequestStatus | "")} aria-label="Signing request status">
            {signingStatuses.map((item) => (
              <option key={item || "all"} value={item}>
                {item ? label(item) : "All request statuses"}
              </option>
            ))}
          </select>
        </label>
      </div>
      <QueryState query={signingQuery}>
        <div className="request-list">
          {(signingQuery.data || []).map((request) => (
            <Link className="request-row" to={`/contracts/${request.contract_id}?tab=signing`} key={request.id}>
              <span className="request-meta">
                <strong>{request.contract_title || "Untitled contract"}</strong>
                <small className={mutedText}>{request.signers.length} signer{request.signers.length === 1 ? "" : "s"}</small>
              </span>
              <span className="request-status">
                <StatusBadge status={request.status} />
                <ChevronRight size={16} aria-hidden="true" />
              </span>
            </Link>
          ))}
          {signingQuery.data?.length === 0 && <EmptyState title="No signing requests match this filter." />}
        </div>
      </QueryState>
    </section>
  );
}

export function ContractTable({ contracts }: { contracts: ContractListItem[] }) {
  if (!contracts.length) return <EmptyState title="No contracts found." />;
  return (
    <div className={tableWrap}>
      <table className={cx(tableClass, "contracts-table")}>
        <thead>
          <tr>
            <th className={thClass}>Contract</th>
            <th className={thClass}>Review</th>
            <th className={thClass}>Risks</th>
            <th className={thClass}>Signing</th>
            <th className={thClass}>Updated</th>
          </tr>
        </thead>
        <tbody>
          {contracts.map((contract) => (
            <tr key={contract.id}>
              <td className={tdClass}>
                <Link className="row-title" to={`/contracts/${contract.id}`}>
                  {contract.title}
                </Link>
                <small className={mutedText}>{contract.original_filename || "Stored document"}</small>
              </td>
              <td className={tdClass}>
                <StatusBadge status={contract.review_status} />
              </td>
              <td className={tdClass}>
                <RiskCounts counts={contract.risk_counts} />
              </td>
              <td className={tdClass}>
                {contract.signing_summary.status ? (
                  <span className="signing-cell">
                    <StatusBadge status={contract.signing_summary.status} />
                    <small className={mutedText}>
                      {contract.signing_summary.required_signed}/{contract.signing_summary.required_total} required
                    </small>
                  </span>
                ) : (
                  <span className={mutedText}>Not started</span>
                )}
              </td>
              <td className={cx(tdClass, "date-cell")}>{formatDate(contract.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ContractsTableSkeleton() {
  return (
    <div className="contracts-loading" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">Loading contracts</span>
      <div className={cx(tableWrap, "contracts-skeleton")} aria-hidden="true">
        <table className={cx(tableClass, "contracts-table")}>
          <thead>
            <tr>
              <th className={thClass}>Contract</th>
              <th className={thClass}>Review</th>
              <th className={thClass}>Risks</th>
              <th className={thClass}>Signing</th>
              <th className={thClass}>Updated</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 4 }, (_, index) => (
              <tr key={index}>
                <td className={tdClass}>
                  <div className="skeleton-stack skeleton-contract">
                    <Skeleton className="skeleton-line skeleton-title" />
                    <Skeleton className="skeleton-line skeleton-filename" />
                  </div>
                </td>
                <td className={tdClass}>
                  <Skeleton className="skeleton-badge" />
                </td>
                <td className={tdClass}>
                  <div className="skeleton-inline">
                    <Skeleton className="skeleton-chip" />
                    <Skeleton className="skeleton-chip" />
                  </div>
                </td>
                <td className={tdClass}>
                  <div className="skeleton-stack">
                    <Skeleton className="skeleton-badge skeleton-signing" />
                    <Skeleton className="skeleton-line skeleton-counter" />
                  </div>
                </td>
                <td className={tdClass}>
                  <Skeleton className="skeleton-line skeleton-date" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ReviewTab({ review }: { review: ContractReview | null }) {
  if (!review) return <EmptyState title="Review is not ready yet." />;
  return (
    <div className="detail-grid">
      <section className={panelClass}>
        <PanelTitle>Summary</PanelTitle>
        <dl className="definition-list">
          <div>
            <dt>Type</dt>
            <dd>{review.contract_type}</dd>
          </div>
          <div>
            <dt>Recommended next action</dt>
            <dd>{review.recommended_next_action}</dd>
          </div>
        </dl>
      </section>
      <section className={panelClass}>
        <PanelTitle>Parties</PanelTitle>
        <div className="term-list">
          {review.parties.map((party) => (
            <div key={`${party.name}-${party.role || "party"}`}>
              <strong>{party.name}</strong>
              <span>{party.role || "Party"}</span>
            </div>
          ))}
          {!review.parties.length && <span className={mutedText}>No parties extracted.</span>}
        </div>
      </section>
      <section className={panelClass}>
        <PanelTitle>Key terms</PanelTitle>
        <div className="term-list">
          {review.key_terms.map((term) => (
            <div key={term.name}>
              <strong>{term.name}</strong>
              <span>{term.value || "Not found"}</span>
            </div>
          ))}
          {!review.key_terms.length && <span className={mutedText}>No key terms extracted.</span>}
        </div>
      </section>
      <section className={cx(panelClass, "wide")}>
        <PanelTitle>Risks</PanelTitle>
        <div className="risk-list">
          {review.risks.map((risk) => (
            <article key={`${risk.title}-${risk.evidence.page_number}`} className="risk-item">
              <div className="risk-heading">
                <StatusBadge status={risk.severity} />
                <strong>{risk.title}</strong>
              </div>
              <p>{risk.explanation}</p>
              <blockquote>
                Page {risk.evidence.page_number}: {risk.evidence.exact_text}
              </blockquote>
              <p><b>Recommendation:</b> {risk.recommendation}</p>
            </article>
          ))}
          {!review.risks.length && <span className={mutedText}>No evidence-grounded risks found.</span>}
        </div>
      </section>
      <section className={cx(panelClass, "wide")}>
        <PanelTitle>Limitations</PanelTitle>
        <ul className="plain-list">
          {review.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
          {!review.limitations.length && <li>No limitations recorded.</li>}
        </ul>
      </section>
    </div>
  );
}

function DocumentTab({
  contract,
  url,
  isLoading,
  error
}: {
  contract: ContractDetail;
  url: string | null;
  isLoading: boolean;
  error: string | null;
}) {
  if (error) {
    return <section className="panel error">Unable to load this document. {error}</section>;
  }
  if (isLoading || !url) {
    return (
      <section className="document-panel document-panel-loading" aria-label="Loading document" aria-busy="true">
        <Loader2 className="spin" size={24} aria-hidden="true" />
      </section>
    );
  }
  if (contract.mime_type === "application/pdf") {
    return (
      <section className="document-panel">
        <iframe title={`${contract.title} PDF preview`} src={url} />
      </section>
    );
  }
  return (
    <section className="panel document-download">
      <FileText size={32} />
      <span>{contract.original_filename || "Original document"}</span>
      <a className={primaryButton} href={url}>
        <Download size={16} /> Download
      </a>
    </section>
  );
}

function useObjectUrl(blob: Blob | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const nextUrl = URL.createObjectURL(blob);
    setUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [blob]);
  return url;
}

function SigningTab({ contract }: { contract: ContractDetail }) {
  const queryClient = useQueryClient();
  const [draftSigners, setDraftSigners] = useState<SignerDraft[]>([blankSigner()]);
  const [updateTarget, setUpdateTarget] = useState<Signer | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const currentRequest = contract.signing_requests.find((request) => request.active) || contract.signing_requests[0] || null;
  const createMutation = useMutation({
    mutationFn: () => createSigningRequest(contract.id, draftSigners.filter((signer) => signer.name && signer.email)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["contract", contract.id] })
  });

  return (
    <div className="signing-layout">
      <div className="notice">
        <AlertTriangle size={17} />
        Tracking only. Samvid does not create, place, execute, or certify electronic signatures.
      </div>
      {!currentRequest ? (
        <section className={panelClass}>
          <PanelTitle>Create signing request</PanelTitle>
          <SignerEditor signers={draftSigners} onChange={setDraftSigners} />
          <button className={primaryButton} onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            {createMutation.isPending ? <Loader2 className="spin" size={16} /> : <Send size={16} />} Create request
          </button>
          <MutationError mutation={createMutation} />
        </section>
      ) : (
        <section className={cx(panelClass, "wide")}>
          <div className="panel-heading">
            <span>
              <PanelTitle>Signer identities</PanelTitle>
              <small className={mutedText}>Pinned to version {currentRequest.contract_version_id}</small>
            </span>
            <span className="heading-actions">
              <StatusBadge status={currentRequest.status} />
              {currentRequest.active && (
                <button className={secondaryButton} onClick={() => setAddOpen(true)}>
                  <UserPlus size={16} /> Add signer
                </button>
              )}
            </span>
          </div>
          <SignerTable request={currentRequest} onUpdate={setUpdateTarget} />
          <Timeline request={currentRequest} />
        </section>
      )}
      {contract.signing_requests.length > 1 && (
        <section className={panelCardClass}>
          <PanelTitle>Historical requests</PanelTitle>
          <div className="compact-list">
            {contract.signing_requests.map((request) => (
              <div key={request.id}>
                <span>{formatDate(request.created_at)}</span>
                <StatusBadge status={request.status} />
              </div>
            ))}
          </div>
        </section>
      )}
      {updateTarget && currentRequest && <StatusDialog signer={updateTarget} contractId={contract.id} onClose={() => setUpdateTarget(null)} />}
      {addOpen && currentRequest && <AddSignerDialog request={currentRequest} contractId={contract.id} onClose={() => setAddOpen(false)} />}
    </div>
  );
}

function SignerTable({ request, onUpdate }: { request: SigningRequest; onUpdate: (signer: Signer) => void }) {
  return (
    <div className={tableWrap}>
      <table className={cx(tableClass, "signer-table")}>
        <thead>
          <tr>
            <th className={thClass}>Name</th>
            <th className={thClass}>Email</th>
            <th className={thClass}>Role</th>
            <th className={thClass}>Need</th>
            <th className={thClass}>Status</th>
            <th className={thClass} />
          </tr>
        </thead>
        <tbody>
          {request.signers.map((signer) => (
            <tr key={signer.id}>
              <td className={tdClass}><strong>{signer.name}</strong></td>
              <td className={tdClass}>{signer.email}</td>
              <td className={tdClass}>{signer.role || "Signer"}</td>
              <td className={tdClass}>{signer.required ? "Required" : "Optional"}</td>
              <td className={tdClass}><StatusBadge status={signer.latest_status} /></td>
              <td className={cx(tdClass, "table-action")}>
                <button className={compactButton} onClick={() => onUpdate(signer)}>
                  Update
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Timeline({ request }: { request: SigningRequest }) {
  const events = request.signers
    .flatMap((signer) => signer.events.map((event) => ({ ...event, signer })))
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  return (
    <section className="timeline" aria-label="Immutable signer event timeline">
      <PanelTitle>Timeline</PanelTitle>
      {events.map((event) => (
        <article key={event.id}>
          <span className="timeline-dot" />
          <div className="timeline-event">
            <strong>{event.signer.name}</strong>
            <StatusBadge status={event.status} />
            <small className={mutedText}>{event.actor_name} - {formatDate(event.created_at)}</small>
            {event.note && <p>{event.note}</p>}
          </div>
        </article>
      ))}
    </section>
  );
}

function StatusDialog({ signer, contractId, onClose }: { signer: Signer; contractId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SignerStatus>("sent");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const terminal = terminalSignerStatuses.includes(status);
  const mutation = useMutation({
    mutationFn: () => appendSignerEvent(signer.id, status, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
      queryClient.invalidateQueries({ queryKey: ["signing-requests"] });
      onClose();
    }
  });
  return (
    <Dialog title={`Update ${signer.name}`} onClose={onClose}>
      <label className={fieldLabelClass}>
        Status
        <select className={fieldControlClass} value={status} onChange={(event) => setStatus(event.target.value as SignerStatus)}>
          {signerStatuses.map((item) => (
            <option key={item} value={item}>{label(item)}</option>
          ))}
        </select>
      </label>
      <label className={cx(fieldLabelClass, "field-spaced")}>
        Note
        <textarea className={fieldControlClass} value={note} onChange={(event) => setNote(event.target.value)} rows={4} placeholder="Optional context" />
      </label>
      {terminal && (
        <label className="check">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          Confirm this terminal status is a manual tracking update only.
        </label>
      )}
      <div className="dialog-actions">
        <button className={secondaryButton} onClick={onClose}>Cancel</button>
        <button className={primaryButton} onClick={() => mutation.mutate()} disabled={mutation.isPending || (terminal && !confirmed)}>
          {mutation.isPending ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />} Append event
        </button>
      </div>
      <MutationError mutation={mutation} />
    </Dialog>
  );
}

function AddSignerDialog({ request, contractId, onClose }: { request: SigningRequest; contractId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [signer, setSigner] = useState(blankSigner());
  const mutation = useMutation({
    mutationFn: () => addSigner(request.id, signer),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
      onClose();
    }
  });
  return (
    <Dialog title="Add signer" onClose={onClose}>
      <SignerFields signer={signer} onChange={setSigner} />
      <div className="dialog-actions">
        <button className={secondaryButton} onClick={onClose}>Cancel</button>
        <button className={primaryButton} onClick={() => mutation.mutate()} disabled={mutation.isPending || !signer.name || !signer.email}>
          <UserPlus size={16} /> Add signer
        </button>
      </div>
      <MutationError mutation={mutation} />
    </Dialog>
  );
}

function SignerEditor({ signers, onChange }: { signers: SignerDraft[]; onChange: (signers: SignerDraft[]) => void }) {
  return (
    <div className="signer-editor">
      {signers.map((signer, index) => (
        <div className="signer-draft" key={index}>
          <SignerFields
            signer={signer}
            onChange={(updated) => onChange(signers.map((item, itemIndex) => (itemIndex === index ? updated : item)))}
          />
          <button className={iconButton} aria-label="Remove signer" onClick={() => onChange(signers.filter((_, itemIndex) => itemIndex !== index))}>
            <X size={16} />
          </button>
        </div>
      ))}
      <button className={secondaryButton} onClick={() => onChange([...signers, blankSigner()])}>
        <Plus size={16} /> Add row
      </button>
    </div>
  );
}

function SignerFields({ signer, onChange }: { signer: SignerDraft; onChange: (signer: SignerDraft) => void }) {
  return (
    <div className="signer-fields">
      <label className={fieldLabelClass}>
        Name
        <input className={fieldControlClass} value={signer.name} onChange={(event) => onChange({ ...signer, name: event.target.value })} />
      </label>
      <label className={fieldLabelClass}>
        Email
        <input className={fieldControlClass} type="email" value={signer.email} onChange={(event) => onChange({ ...signer, email: event.target.value })} />
      </label>
      <label className={fieldLabelClass}>
        Role
        <input className={fieldControlClass} value={signer.role} onChange={(event) => onChange({ ...signer, role: event.target.value })} />
      </label>
      <label className="check">
        <input type="checkbox" checked={signer.required} onChange={(event) => onChange({ ...signer, required: event.target.checked })} />
        Required
      </label>
    </div>
  );
}

function UploadDialog({ onClose, onUploaded }: { onClose: () => void; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const mutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a PDF, DOCX, or TXT file.");
      return uploadContract(file, setProgress);
    },
    onSuccess: onUploaded
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate();
  };
  return (
    <Dialog title="Upload contract" onClose={onClose}>
      <form onSubmit={submit} className="upload-form">
        <label className="drop-zone">
          <Upload size={20} />
          <span>{file ? file.name : "Choose PDF, DOCX, or TXT"}</span>
          <input
            className="drop-input"
            type="file"
            accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
        </label>
        {mutation.isPending && (
          <progress className="progress" aria-label="Upload progress" max={100} value={progress} />
        )}
        <div className="dialog-actions">
          <button type="button" className={secondaryButton} onClick={onClose}>Cancel</button>
          <button type="submit" className={primaryButton} disabled={!file || mutation.isPending}>
            {mutation.isPending ? <Loader2 className="spin" size={16} /> : <Upload size={16} />} Process
          </button>
        </div>
        <MutationError mutation={mutation} />
      </form>
    </Dialog>
  );
}

function Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <div className="dialog-header">
          <PanelTitle>{title}</PanelTitle>
          <button className={iconButton} onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function PageHeader({ eyebrow, title, action }: { eyebrow: string; title: string; action?: ReactNode }) {
  return (
    <header className="page-header">
      <span>
        <small>{eyebrow}</small>
        <h1>{title}</h1>
      </span>
      {action}
    </header>
  );
}

function PanelTitle({ children }: { children: ReactNode }) {
  return <h2>{children}</h2>;
}

function QueryState({
  query,
  children,
  loadingFallback
}: {
  query: { isLoading: boolean; isError: boolean; error: unknown };
  children: ReactNode;
  loadingFallback?: ReactNode;
}) {
  if (query.isLoading) {
    return loadingFallback || <div className="state"><Loader2 className="spin" size={18} /> Loading</div>;
  }
  if (query.isError) {
    return <div className="state error"><AlertTriangle size={18} /> {query.error instanceof Error ? query.error.message : "Something went wrong."}</div>;
  }
  return <>{children}</>;
}

function MutationError({ mutation }: { mutation: { isError: boolean; error: unknown } }) {
  if (!mutation.isError) return null;
  return <p className="form-error">{mutation.error instanceof Error ? mutation.error.message : "Request failed."}</p>;
}

function EmptyState({ title }: { title: string }) {
  return <div className="empty">{title}</div>;
}

function StatusBadge({ status }: { status: string }) {
  return <span className={cx("badge", statusTone(status))}>{label(status)}</span>;
}

function RiskCounts({ counts }: { counts: Record<RiskSeverity, number> }) {
  const total = counts.critical + counts.high + counts.medium + counts.low;
  if (!total) return <span className={mutedText}>None</span>;
  return (
    <span className="risk-counts">
      {(["critical", "high", "medium", "low"] as RiskSeverity[]).map((severity) =>
        counts[severity] ? <span className={cx("risk-dot", riskTone(severity))} key={severity}>{counts[severity]}</span> : null
      )}
    </span>
  );
}

function blankSigner(): SignerDraft {
  return { name: "", email: "", role: "", required: true };
}

function label(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusTone(status: string): string {
  if (["completed", "signed", "review_ready", "low"].includes(status)) return "success";
  if (["declined", "cancelled", "expired", "critical", "high", "parse_failed", "analysis_failed", "rejected_file"].includes(status)) return "danger";
  if (["sent", "viewed", "in_progress", "medium", "ocr_required", "analysing", "parsing"].includes(status)) return "warning";
  return "neutral";
}

function riskTone(status: string): string {
  if (["low"].includes(status)) return "success";
  if (["critical", "high"].includes(status)) return "danger";
  if (["medium"].includes(status)) return "warning";
  return "neutral";
}
