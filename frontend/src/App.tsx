import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  Download,
  FileText,
  Filter,
  History,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Send,
  Upload,
  UserPlus,
  X
} from "lucide-react";
import { FormEvent, ReactNode, useState } from "react";
import { Link, NavLink, Outlet, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addSigner,
  appendSignerEvent,
  createSigningRequest,
  getContract,
  listContracts,
  listSigningRequests,
  uploadContract
} from "./api";
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

const signingStatuses: Array<SigningRequestStatus | ""> = ["", "not_started", "in_progress", "completed", "declined", "expired", "cancelled"];
const reviewStatuses = ["", "received", "parsing", "analysing", "review_ready", "ocr_required", "parse_failed", "analysis_failed"];
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
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link to="/contracts" className="brand" aria-label="Samvid contracts">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span>
            <strong>Samvid</strong>
            <small className="brand-caption">Contract workspace</small>
          </span>
        </Link>
        <nav className="sidebar-nav">
          <NavLink
            to="/contracts"
            className={({ isActive }) =>
              cx("nav-link", isActive && "active")
            }
          >
            <FileText size={17} /> Contracts
          </NavLink>
          <NavLink
            to="/signing"
            className={({ isActive }) =>
              cx("nav-link", isActive && "active")
            }
          >
            <History size={17} /> Signing
          </NavLink>
        </nav>
        <p className="tracking-note">
          Tracking only. Samvid does not execute electronic signatures.
        </p>
      </aside>
      <main>
        <Outlet />
      </main>
    </div>
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
    queryFn: () => listContracts({ search, reviewStatus, signingStatus })
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
      <QueryState query={contractsQuery}>
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
    enabled: Boolean(contractId)
  });

  return (
    <section className={pageClass}>
      <QueryState query={contractQuery}>
        {contractQuery.data && (
          <>
            <PageHeader
              eyebrow="Contract"
              title={contractQuery.data.title}
              action={
                <a className={secondaryButton} href={`/api/contracts/${contractQuery.data.id}/document`} target="_blank" rel="noreferrer">
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
            {tab === "document" && <DocumentTab contract={contractQuery.data} />}
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

function DocumentTab({ contract }: { contract: ContractDetail }) {
  const url = `/api/contracts/${contract.id}/document`;
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

function QueryState({ query, children }: { query: { isLoading: boolean; isError: boolean; error: unknown }; children: ReactNode }) {
  if (query.isLoading) {
    return <div className="state"><Loader2 className="spin" size={18} /> Loading</div>;
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
