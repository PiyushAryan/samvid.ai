"use client";

import { ChevronRight, Filter } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@/lib/navigation";
import { QueryState } from "@/components/shared/feedback";
import { PageHeader } from "@/components/shared/page-header";
import { listSigningRequests } from "./api";
import type { SigningRequestStatus } from "./types";
import { cx, EmptyState, label, StatusBadge } from "./ui";

const signingStatuses: Array<SigningRequestStatus | ""> = ["", "not_started", "in_progress", "completed", "declined", "expired", "cancelled"];
const pageClass = "page";
const toolbarControl = "toolbar-control";
const toolbarInput = "toolbar-input";
const mutedText = "muted";

export function SigningPage() {
  const [status, setStatus] = useState<SigningRequestStatus | "">("");
  const signingQuery = useQuery({
    queryKey: ["signing-requests", status],
    queryFn: () => listSigningRequests(status)
  });
  return (
    <section className={cx(pageClass, "signing-page")}>
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

