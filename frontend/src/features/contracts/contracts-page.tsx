"use client";

import { CheckCircle2, Filter, History, Loader2, RefreshCw, Search, Upload } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@/lib/navigation";
import { Dialog } from "@/components/shared/dialog";
import { MutationError, QueryState } from "@/components/shared/feedback";
import { PageHeader } from "@/components/shared/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { listContracts, uploadContract, type ContractUploadProgress } from "./api";
import type { ContractListItem } from "./types";
import { cx, EmptyState, formatDate, label, RiskCounts, StatusBadge } from "./ui";

const signingStatuses = ["", "not_started", "in_progress", "completed", "declined", "expired", "cancelled"];
const reviewStatuses = ["", "received", "validating", "queued", "parsing", "analysing", "validating_evidence", "review_ready", "ocr_required", "parse_failed", "analysis_failed"];
const activeReviewStatuses = new Set(["received", "validating", "queued", "parsing", "analysing", "validating_evidence"]);
const primaryButton = "primary";
const secondaryButton = "secondary";
const iconButton = "icon-button";
const pageClass = "page";
const toolbarControl = "toolbar-control";
const toolbarInput = "toolbar-input";
const tableWrap = "table-wrap";
const tableClass = "data-table";
const thClass = "table-heading";
const tdClass = "table-cell";
const mutedText = "muted";

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
    <section className={cx(pageClass, "contracts-page")}>
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
        <button
          className={iconButton}
          type="button"
          onClick={() => void contractsQuery.refetch()}
          aria-label="Refresh contracts"
          aria-busy={contractsQuery.isFetching}
          disabled={contractsQuery.isFetching}
        >
          <RefreshCw className={contractsQuery.isFetching ? "spin" : undefined} size={16} aria-hidden="true" />
        </button>
      </div>
      <QueryState query={contractsQuery} loadingFallback={<ContractsTableSkeleton />}>
        <ContractTable contracts={contractsQuery.data || []} />
      </QueryState>
      {uploadOpen && (
        <UploadDialog
          onClose={() => setUploadOpen(false)}
          onUploaded={() => {
            void queryClient.invalidateQueries({ queryKey: ["contracts"] });
          }}
        />
      )}
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

function UploadDialog({ onClose, onUploaded }: { onClose: () => void; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState<ContractUploadProgress>({
    percentage: 0,
    stage: "uploading"
  });
  const abortControllerRef = useRef<AbortController | null>(null);
  const mutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a PDF, DOCX, or TXT file.");
      const controller = new AbortController();
      abortControllerRef.current = controller;
      setUploadProgress({ percentage: 0, stage: "uploading" });
      return uploadContract(file, setUploadProgress, controller.signal);
    },
    onSuccess: onUploaded,
    onSettled: () => {
      abortControllerRef.current = null;
    }
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate();
  };
  const close = () => {
    abortControllerRef.current?.abort();
    onClose();
  };
  const chooseFile = (nextFile: File | null) => {
    mutation.reset();
    setUploadProgress({ percentage: 0, stage: "uploading" });
    setFile(nextFile);
  };
  const progressLabel = uploadProgress.stage === "uploading"
    ? `Uploading ${uploadProgress.percentage}%`
    : "Upload complete. Starting contract review…";

  if (mutation.isSuccess) {
    return (
      <Dialog title="Upload contract" onClose={close}>
        <div className="upload-success" role="status" aria-live="polite">
          <span className="upload-success-icon" aria-hidden="true"><CheckCircle2 size={20} /></span>
          <div>
            <strong>Contract received</strong>
            <p>{mutation.data.message || "The review has started and the contract list will update automatically."}</p>
            {file && <small>{file.name}</small>}
          </div>
        </div>
        <div className="dialog-actions">
          <button type="button" className={primaryButton} onClick={close}>Done</button>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog title="Upload contract" onClose={close}>
      <form onSubmit={submit} className="upload-form">
        <label className={cx("drop-zone", mutation.isPending && "is-disabled")}>
          <Upload size={20} />
          <span>{file ? file.name : "Choose PDF, DOCX, or TXT"}</span>
          <input
            className="drop-input"
            type="file"
            aria-label="Choose contract file"
            accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
            disabled={mutation.isPending}
            onChange={(event) => chooseFile(event.target.files?.[0] || null)}
          />
        </label>
        {mutation.isPending && (
          <div className="upload-progress" role="status" aria-live="polite">
            <div className="upload-progress-label">
              <span>{progressLabel}</span>
              {uploadProgress.stage === "uploading" && <span>{uploadProgress.percentage}%</span>}
            </div>
            <progress
              className="progress"
              aria-label={progressLabel}
              max={100}
              value={uploadProgress.stage === "uploading" ? uploadProgress.percentage : undefined}
            />
          </div>
        )}
        <div className="dialog-actions">
          <button type="button" className={secondaryButton} onClick={close}>Cancel</button>
          <button type="submit" className={primaryButton} disabled={!file || mutation.isPending}>
            {mutation.isPending ? <Loader2 className="spin" size={16} /> : <Upload size={16} />}
            {mutation.isPending
              ? uploadProgress.stage === "uploading" ? "Uploading" : "Starting review"
              : mutation.isError ? "Try again" : "Process"}
          </button>
        </div>
        <MutationError mutation={mutation} />
      </form>
    </Dialog>
  );
}

