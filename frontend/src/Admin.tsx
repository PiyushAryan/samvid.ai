import {
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  ClipboardList,
  FileText,
  History,
  LogOut,
  Moon,
  PanelLeft,
  RefreshCw,
  Search,
  ShieldCheck,
  Sun,
  Users
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  getAdminContract,
  getAdminContractDocument,
  getAdminContractSigning,
  getAdminUser,
  listAdminAccessEvents,
  listAdminUserContracts,
  listAdminUsers,
  type CollectionResponse
} from "./api";
import { ReviewTab, Timeline } from "./App";
import { useAuth } from "./AuthProvider";
import { Skeleton } from "./components/ui/skeleton";
import { setFaviconTheme } from "./favicon";
import type {
  AdminAccessEvent,
  AdminUserSummary,
  ContractListItem,
  SigningRequest
} from "./types";

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function collectionItems<T>(response: CollectionResponse<T> | undefined): T[] {
  if (!response) return [];
  return Array.isArray(response) ? response : response.items;
}

function getInitialTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  const saved = window.localStorage.getItem("samvid-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function AdminShell() {
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
        <Outlet />
      </main>
    </motion.div>
  );
}

export function AdminUsersPage() {
  const [search, setSearch] = useState("");
  const [state, setState] = useState("");
  const usersQuery = useQuery({
    queryKey: ["admin", "users", search, state],
    queryFn: () => listAdminUsers({ search, state })
  });
  const users = collectionItems(usersQuery.data);

  return (
    <section className="page admin-page" aria-labelledby="admin-users-title">
      <AdminPageHeader
        eyebrow="Platform oversight"
        title="User accounts"
        description="Read-only visibility across private Samvid accounts."
        titleId="admin-users-title"
      />
      <div className="admin-summary-strip" aria-label="Account summary">
        <SummaryMetric label="Visible accounts" value={String(users.length)} />
        <SummaryMetric label="Active" value={String(users.filter((item) => item.state === "active").length)} />
        <SummaryMetric label="Unclaimed" value={String(users.filter((item) => item.state === "unclaimed").length)} />
      </div>
      <div className="toolbar admin-toolbar" role="search">
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <input
            className="toolbar-input"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search name or email"
          />
        </label>
        <label className="toolbar-control">
          <span className="admin-control-label">State</span>
          <select className="toolbar-input" value={state} onChange={(event) => setState(event.target.value)} aria-label="Account state">
            <option value="">All states</option>
            <option value="active">Active</option>
            <option value="unclaimed">Unclaimed</option>
          </select>
        </label>
        <button className="icon-button" type="button" onClick={() => void usersQuery.refetch()} aria-label="Refresh users">
          <RefreshCw size={16} />
        </button>
      </div>
      <AdminQueryState query={usersQuery} loading={<AdminTableSkeleton columns={5} />}>
        {users.length ? <AdminUsersTable users={users} /> : <AdminEmpty title="No user accounts match these filters." />}
      </AdminQueryState>
    </section>
  );
}

function AdminUsersTable({ users }: { users: AdminUserSummary[] }) {
  return (
    <div className="table-wrap admin-table-wrap">
      <table className="data-table admin-table">
        <thead><tr>
          <th className="table-heading">Account</th>
          <th className="table-heading">State</th>
          <th className="table-heading">Source</th>
          <th className="table-heading">Contracts</th>
          <th className="table-heading"><span className="sr-only">Open</span></th>
        </tr></thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id}>
              <td className="table-cell">
                <Link className="admin-account-link" to={`/admin/users/${user.id}`}>
                  <span className="admin-avatar" aria-hidden="true">{(user.name || user.email).charAt(0).toUpperCase()}</span>
                  <span><strong>{user.name || "Unnamed account"}</strong><small>{user.email}</small></span>
                </Link>
              </td>
              <td className="table-cell"><AdminBadge value={user.state} /></td>
              <td className="table-cell admin-muted">{formatLabel(user.source)}</td>
              <td className="table-cell">{user.contract_count ?? 0}</td>
              <td className="table-cell admin-row-action"><Link to={`/admin/users/${user.id}`} aria-label={`Open ${user.email}`}><ChevronRight size={17} /></Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AdminUserDetailPage() {
  const { userId = "" } = useParams();
  const [search, setSearch] = useState("");
  const userQuery = useQuery({
    queryKey: ["admin", "user", userId],
    queryFn: () => getAdminUser(userId),
    enabled: Boolean(userId)
  });
  const contractsQuery = useQuery({
    queryKey: ["admin", "user", userId, "contracts", search],
    queryFn: () => listAdminUserContracts(userId, { search }),
    enabled: Boolean(userId)
  });
  const contracts = collectionItems(contractsQuery.data);

  return (
    <section className="page admin-page">
      <Link className="admin-back-link" to="/admin/users"><ArrowLeft size={15} /> User accounts</Link>
      <AdminQueryState query={userQuery} loading={<AdminDetailSkeleton />}>
        {userQuery.data && (
          <>
            <AdminPageHeader
              eyebrow="Private account"
              title={userQuery.data.name || userQuery.data.email}
              description={userQuery.data.email}
            />
            <dl className="admin-account-facts">
              <div><dt>State</dt><dd><AdminBadge value={userQuery.data.state} /></dd></div>
              <div><dt>Source</dt><dd>{formatLabel(userQuery.data.source)}</dd></div>
              <div><dt>Contracts</dt><dd>{userQuery.data.contract_count ?? contracts.length}</dd></div>
              <div><dt>Joined</dt><dd>{formatDate(userQuery.data.claimed_at || userQuery.data.created_at)}</dd></div>
            </dl>
          </>
        )}
      </AdminQueryState>

      <section className="admin-section" aria-labelledby="user-contracts-title">
        <div className="admin-section-heading">
          <div><span>Private data</span><h2 id="user-contracts-title">Contracts</h2></div>
          <label className="search-field admin-inline-search">
            <Search size={15} />
            <input className="toolbar-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search contracts" />
          </label>
        </div>
        <AdminQueryState query={contractsQuery} loading={<AdminTableSkeleton columns={4} />}>
          {contracts.length ? <AdminContractsTable contracts={contracts} /> : <AdminEmpty title="This account has no matching contracts." />}
        </AdminQueryState>
      </section>
    </section>
  );
}

function AdminContractsTable({ contracts }: { contracts: ContractListItem[] }) {
  return (
    <div className="table-wrap admin-table-wrap">
      <table className="data-table admin-table">
        <thead><tr>
          <th className="table-heading">Contract</th>
          <th className="table-heading">Review</th>
          <th className="table-heading">Signing</th>
          <th className="table-heading">Updated</th>
        </tr></thead>
        <tbody>
          {contracts.map((contract) => (
            <tr key={contract.id}>
              <td className="table-cell"><Link className="admin-contract-link" to={`/admin/contracts/${contract.id}`}><FileText size={16} /><span><strong>{contract.title}</strong><small>{contract.original_filename}</small></span></Link></td>
              <td className="table-cell"><AdminBadge value={contract.review_status} /></td>
              <td className="table-cell"><AdminBadge value={contract.signing_summary?.status || "not_started"} /></td>
              <td className="table-cell admin-muted">{formatDate(contract.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AdminContractDetailPage() {
  const { contractId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "review";
  const contractQuery = useQuery({
    queryKey: ["admin", "contract", contractId],
    queryFn: () => getAdminContract(contractId),
    enabled: Boolean(contractId)
  });
  const documentQuery = useQuery({
    queryKey: ["admin", "contract", contractId, "document"],
    queryFn: () => getAdminContractDocument(contractId),
    enabled: tab === "document" && Boolean(contractQuery.data?.current_version)
  });
  const signingQuery = useQuery({
    queryKey: ["admin", "contract", contractId, "signing"],
    queryFn: () => getAdminContractSigning(contractId),
    enabled: tab === "signing"
  });
  const documentUrl = useObjectUrl(documentQuery.data);
  const signingRequests = Array.isArray(signingQuery.data) ? signingQuery.data : signingQuery.data?.items || [];

  return (
    <section className="page admin-page">
      <button className="admin-back-link admin-back-button" type="button" onClick={() => history.back()}><ArrowLeft size={15} /> Back</button>
      <AdminQueryState query={contractQuery} loading={<AdminDetailSkeleton />}>
        {contractQuery.data && (
          <>
            <AdminPageHeader
              eyebrow="Read-only contract"
              title={contractQuery.data.title}
              description="Oversight view. Changes and workflow actions are disabled."
              action={documentUrl ? <a className="secondary" href={documentUrl} target="_blank" rel="noreferrer">Open original <ArrowUpRight size={15} /></a> : undefined}
            />
            <div className="admin-readonly-notice"><ShieldCheck size={17} /><span>Super-admin access is logged. This view cannot modify user data.</span></div>
            <div className="tabs" role="tablist" aria-label="Contract oversight sections">
              {["review", "document", "signing"].map((value) => (
                <button key={value} className={cx("tab", tab === value && "active")} onClick={() => setParams({ tab: value })} role="tab" aria-selected={tab === value}>
                  {formatLabel(value)}
                </button>
              ))}
            </div>
            {tab === "review" && <ReviewTab review={contractQuery.data.review} />}
            {tab === "document" && (
              <AdminQueryState query={documentQuery} loading={<AdminDocumentSkeleton />}>
                {documentUrl ? (
                  <div className="document-panel admin-document-panel">
                    {contractQuery.data.current_version?.mime_type === "application/pdf"
                      ? <iframe title={contractQuery.data.title} src={documentUrl} />
                      : <div className="admin-document-fallback"><FileText size={28} /><p>Browser preview is not available for this file type.</p><a className="secondary" href={documentUrl} target="_blank" rel="noreferrer">Open original</a></div>}
                  </div>
                ) : <AdminEmpty title="No original document is available." />}
              </AdminQueryState>
            )}
            {tab === "signing" && (
              <AdminQueryState query={signingQuery} loading={<AdminDetailSkeleton />}>
                {signingRequests.length ? (
                  <div className="admin-signing-list">
                    {signingRequests.map((request) => <AdminSigningRequest key={request.id} request={request} />)}
                  </div>
                ) : <AdminEmpty title="No signing activity has been recorded." />}
              </AdminQueryState>
            )}
          </>
        )}
      </AdminQueryState>
    </section>
  );
}

function AdminSigningRequest({ request }: { request: SigningRequest }) {
  return (
    <article className="panel panel-card admin-signing-card">
      <div className="admin-section-heading">
        <div><span>Signing request</span><h2>{formatLabel(request.status)}</h2></div>
        <AdminBadge value={request.status} />
      </div>
      <div className="admin-signer-list">
        {request.signers.map((signer) => (
          <div key={signer.id}><span><strong>{signer.name}</strong><small>{signer.email}</small></span><AdminBadge value={signer.latest_status} /></div>
        ))}
      </div>
      <Timeline request={request} />
    </article>
  );
}

export function AdminAccessEventsPage() {
  const [search, setSearch] = useState("");
  const eventsQuery = useQuery({
    queryKey: ["admin", "access-events", search],
    queryFn: () => listAdminAccessEvents({ search })
  });
  const events = collectionItems(eventsQuery.data);

  return (
    <section className="page admin-page" aria-labelledby="access-events-title">
      <AdminPageHeader
        eyebrow="Privacy audit"
        title="Access log"
        description="A record of super-admin access to private account data."
        titleId="access-events-title"
      />
      <div className="toolbar admin-toolbar" role="search">
        <label className="search-field">
          <Search size={16} />
          <input className="toolbar-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search events" />
        </label>
        <button className="icon-button" type="button" onClick={() => void eventsQuery.refetch()} aria-label="Refresh access log"><RefreshCw size={16} /></button>
      </div>
      <AdminQueryState query={eventsQuery} loading={<AdminTableSkeleton columns={4} />}>
        {events.length ? <AdminEventsTable events={events} /> : <AdminEmpty title="No access events have been recorded." />}
      </AdminQueryState>
    </section>
  );
}

function AdminEventsTable({ events }: { events: AdminAccessEvent[] }) {
  return (
    <div className="table-wrap admin-table-wrap">
      <table className="data-table admin-table">
        <thead><tr><th className="table-heading">Event</th><th className="table-heading">Target</th><th className="table-heading">Contract</th><th className="table-heading">Time</th></tr></thead>
        <tbody>{events.map((event) => (
          <tr key={event.id}>
            <td className="table-cell"><span className="admin-event-name"><History size={15} /><span><strong>{formatLabel(event.event_type)}</strong><small>{event.actor_email || "Super admin"}</small></span></span></td>
            <td className="table-cell admin-muted">{event.target_user_email || "—"}</td>
            <td className="table-cell admin-muted">{event.contract_title || event.contract_id || "—"}</td>
            <td className="table-cell admin-muted">{formatDate(event.created_at)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function AdminPageHeader({ eyebrow, title, description, titleId, action }: { eyebrow: string; title: string; description: string; titleId?: string; action?: ReactNode }) {
  return (
    <header className="page-header admin-page-header">
      <div><small>{eyebrow}</small><h1 id={titleId}>{title}</h1><p>{description}</p></div>
      {action}
    </header>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function AdminBadge({ value }: { value: string }) {
  return <span className={cx("status", "admin-badge", `admin-badge-${value.replace(/_/g, "-")}`)}>{formatLabel(value)}</span>;
}

function AdminEmpty({ title }: { title: string }) {
  return <div className="empty admin-empty"><ShieldCheck size={22} /><p>{title}</p></div>;
}

function AdminQueryState({ query, loading, children }: { query: { isLoading: boolean; isError: boolean; error: unknown }; loading: ReactNode; children: ReactNode }) {
  if (query.isLoading) return loading;
  if (query.isError) return <div className="state error" role="alert">{query.error instanceof Error ? query.error.message : "Unable to load oversight data."}</div>;
  return children;
}

function AdminTableSkeleton({ columns }: { columns: number }) {
  return <div className="admin-skeleton-table" role="status" aria-label="Loading data">{Array.from({ length: 4 * columns }, (_, index) => <Skeleton key={index} className="admin-skeleton-cell" />)}</div>;
}

function AdminDetailSkeleton() {
  return <div className="admin-detail-skeleton" role="status" aria-label="Loading details"><Skeleton className="admin-skeleton-title" /><Skeleton /><Skeleton /><Skeleton /></div>;
}

function AdminDocumentSkeleton() {
  return <div className="admin-document-skeleton" role="status" aria-label="Loading document"><Skeleton /></div>;
}

function useObjectUrl(blob: Blob | undefined) {
  return useMemo(() => {
    if (!blob) return undefined;
    return URL.createObjectURL(blob);
  }, [blob]);
}

function formatLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
