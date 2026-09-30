"use client";

import { ArrowLeft, ArrowUpRight, FileText, ShieldCheck } from "lucide-react";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "@/lib/navigation";
import { getAdminContract, getAdminContractDocument, getAdminContractSigning } from "./api";
import { PdfDocumentView } from "@/features/contracts/document-viewer";
import { ReviewTab, RisksTab } from "@/features/contracts/review-components";
import { Timeline } from "@/features/signing/timeline";
import type { SigningRequest } from "@/features/signing/types";
import { AdminBadge, AdminDetailSkeleton, AdminDocumentSkeleton, AdminEmpty, AdminPageHeader, AdminQueryState, cx, formatLabel } from "./ui";

function useObjectUrl(blob: Blob | undefined) {
  return useMemo(() => {
    if (!blob) return undefined;
    return URL.createObjectURL(blob);
  }, [blob]);
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
              {["review", "risks", "document", "signing"].map((value) => (
                <button key={value} className={cx("tab", tab === value && "active")} onClick={() => setParams({ tab: value })} role="tab" aria-selected={tab === value}>
                  {formatLabel(value)}
                </button>
              ))}
            </div>
            {tab === "review" && <ReviewTab review={contractQuery.data.review} />}
            {tab === "risks" && <RisksTab review={contractQuery.data.review} />}
            {tab === "document" && (
              <AdminQueryState query={documentQuery} loading={<AdminDocumentSkeleton />}>
                {documentUrl && documentQuery.data ? (
                  contractQuery.data.current_version?.mime_type === "application/pdf"
                    ? <PdfDocumentView title={contractQuery.data.title} document={documentQuery.data} />
                    : <div className="document-panel admin-document-panel"><div className="admin-document-fallback"><FileText size={28} /><p>Browser preview is not available for this file type.</p><a className="secondary" href={documentUrl} target="_blank" rel="noreferrer">Open original</a></div></div>
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

