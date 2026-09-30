"use client";

import { ArrowUpRight, Loader2, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "@/lib/navigation";
import { Dialog } from "@/components/shared/dialog";
import { MutationError, QueryState } from "@/components/shared/feedback";
import { PageHeader } from "@/components/shared/page-header";
import { deleteContract, getContract, getContractDocument } from "./api";
import type { ContractDetail } from "./types";
import { DocumentTab, useObjectUrl } from "./document-viewer";
import { ReviewTab, RisksTab } from "./review-components";
import { SigningTab } from "@/features/signing/signing-tab";
import { cx, label } from "./ui";

const activeReviewStatuses = new Set(["received", "validating", "queued", "parsing", "analysing", "validating_evidence"]);
const pageClass = "page";
const secondaryButton = "secondary";

export function ContractDetailPage() {
  const { contractId } = useParams();
  const [params, setParams] = useSearchParams();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const urlTab = params.get("tab") || "review";
  const [tab, setTab] = useState(urlTab);

  useEffect(() => {
    setTab(urlTab);
  }, [urlTab]);
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
    enabled: tab === "document" && Boolean(contractQuery.data?.current_version),
    staleTime: 5 * 60 * 1000
  });
  const documentUrl = useObjectUrl(documentQuery.data);

  return (
    <section className={cx(pageClass, "contract-detail-page", `contract-detail-page-${tab}`)}>
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
            <div className="tabs" role="tablist" aria-label="Contract sections">
              {["review", "risks", "document", "signing"].map((value) => (
                <button
                  key={value}
                  className={cx("tab", tab === value && "active")}
                  onClick={() => {
                    setTab(value);
                    setParams({ tab: value });
                  }}
                  role="tab"
                  aria-selected={tab === value}
                >
                  {label(value)}
                </button>
              ))}
            </div>
            {tab === "review" && <ReviewTab review={contractQuery.data.review} />}
            {tab === "risks" && <RisksTab review={contractQuery.data.review} />}
            {tab === "document" && (
              <DocumentTab
                contract={contractQuery.data}
                document={documentQuery.data}
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

