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
  Paperclip,
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
  Upload,
  UserPlus,
  X
} from "lucide-react";
import { DragEvent, FormEvent, KeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import {
  addSigner,
  appendSignerEvent,
  createSigningRequest,
  getContract,
  getContractDocument,
  listContracts,
  listSigningRequests,
  uploadContract
} from "./api";
import { useAuth } from "./AuthProvider";
import { setFaviconTheme } from "./favicon";
import type {
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
      animate={{ "--sidebar-width": sidebarCollapsed ? "68px" : "232px" }}
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
            <section className="sidebar-chat-section" aria-labelledby="sidebar-chat-history-title">
              <button
                className="sidebar-new-chat"
                type="button"
                onClick={() => navigate("/chats")}
              >
                <SquarePen size={16} aria-hidden="true" />
                <span>New chat</span>
              </button>
              <h2 id="sidebar-chat-history-title">Today</h2>
              <ol className="sidebar-chat-list">
                {["1", "2"].map((chatId) => (
                  <li key={chatId}>
                    <button
                      type="button"
                      aria-current={activeChatId === chatId ? "page" : undefined}
                      onClick={() => navigate(`/chats?chat=${chatId}`)}
                    >
                      chat
                    </button>
                  </li>
                ))}
              </ol>
            </section>
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

type LocalChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
};

type ChatAttachment = {
  id: string;
  file: File;
};

export function ChatsPage() {
  const { user } = useAuth();
  const accountName = user?.name || "there";
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [messages, setMessages] = useState<LocalChatMessage[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messageIdRef = useRef(0);

  const attachFiles = (files: FileList | File[]) => {
    const incoming = Array.from(files);
    if (!incoming.length) return;

    setAttachments((current) => [
      ...current,
      ...incoming.map((file) => ({
        id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID?.() || Math.random()}`,
        file
      }))
    ]);
    setAnnouncement(`${incoming.length} ${incoming.length === 1 ? "file" : "files"} attached`);
  };

  const removeAttachment = (id: string) => {
    setAttachments((current) => {
      const attachment = current.find((item) => item.id === id);
      if (attachment) setAnnouncement(`${attachment.file.name} removed`);
      return current.filter((item) => item.id !== id);
    });
  };

  const submitMessage = () => {
    const message = draft.trim();
    if (!message && attachments.length === 0) return;

    const attachmentSummary = attachments.length
      ? `${attachments.length} ${attachments.length === 1 ? "attachment" : "attachments"}`
      : "";
    const userText = [message, attachmentSummary].filter(Boolean).join(" · ");
    const userId = ++messageIdRef.current;
    const assistantId = ++messageIdRef.current;
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", text: userText },
      {
        id: assistantId,
        role: "assistant",
        text: "This chat is running locally and is not connected to an AI service yet. Your message was not sent to a backend."
      }
    ]);
    setDraft("");
    setAttachments([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
    setAnnouncement("Message added to this local conversation");
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submitMessage();
  };

  const handleDrop = (event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsDragging(false);
    attachFiles(event.dataTransfer.files);
  };

  return (
    <section className="ai-chat-page" aria-labelledby="ai-chat-title">
      <div className="ai-chat-content">
        <header className="ai-chat-header">
          <p className="ai-chat-eyebrow">Samvid AI</p>
          <h1 id="ai-chat-title">Hello, {accountName}</h1>
          <p>find anything about your contracts</p>
        </header>

        {messages.length > 0 && (
          <div className="ai-chat-messages" aria-label="Local chat conversation" aria-live="polite">
            {messages.map((message) => (
              <article
                key={message.id}
                className={cx("ai-chat-message", `ai-chat-message-${message.role}`)}
              >
                <span className="ai-chat-message-role">
                  {message.role === "user" ? "You" : "Samvid"}
                </span>
                <p>{message.text}</p>
              </article>
            ))}
          </div>
        )}

        <form
          className={cx("ai-chat-composer", isDragging && "ai-chat-composer-dragging")}
          onSubmit={handleSubmit}
          onDragEnter={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node)) setIsDragging(false);
          }}
          onDrop={handleDrop}
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
                submitMessage();
              }
            }}
            placeholder="Ask a question about your contracts..."
            rows={2}
          />

          {attachments.length > 0 && (
            <ul className="ai-chat-attachments" aria-label="Attachments">
              {attachments.map((attachment) => (
                <li className="ai-chat-attachment" key={attachment.id}>
                  <FileText size={14} aria-hidden="true" />
                  <span title={attachment.file.name}>{attachment.file.name}</span>
                  <button
                    type="button"
                    onClick={() => removeAttachment(attachment.id)}
                    aria-label={`Remove ${attachment.file.name}`}
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="ai-chat-composer-actions">
            <input
              ref={fileInputRef}
              id="ai-chat-file-input"
              className="ai-chat-file-input"
              type="file"
              multiple
              onChange={(event) => {
                if (event.target.files) attachFiles(event.target.files);
                event.target.value = "";
              }}
            />
            <button
              className="ai-chat-attach-button"
              type="button"
              onClick={() => fileInputRef.current?.click()}
              aria-label="Attach files"
            >
              <Paperclip size={16} aria-hidden="true" />
              <span>Drop to attach</span>
            </button>
            <button
              className="ai-chat-send-button"
              type="submit"
              disabled={!draft.trim() && attachments.length === 0}
              aria-label="Send message"
            >
              <Send size={16} aria-hidden="true" />
              <span>Send</span>
            </button>
          </div>
          <p className="ai-chat-status" role="status" aria-live="polite">
            {announcement}
          </p>
        </form>
      </div>
    </section>
  );
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
                <a
                  className={secondaryButton}
                  href={documentUrl || undefined}
                  target="_blank"
                  rel="noreferrer"
                  aria-disabled={!documentUrl}
                >
                  Open original <ArrowUpRight size={15} />
                </a>
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
          </>
        )}
      </QueryState>
    </section>
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
