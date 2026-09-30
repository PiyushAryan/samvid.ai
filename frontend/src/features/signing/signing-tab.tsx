"use client";

import { AlertTriangle, CheckCircle2, Loader2, Plus, Send, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Dialog } from "@/components/shared/dialog";
import { MutationError } from "@/components/shared/feedback";
import type { ContractDetail } from "@/features/contracts/types";
import { addSigner, appendSignerEvent, createSigningRequest } from "./api";
import type { Signer, SignerDraft, SignerStatus, SigningRequest } from "./types";
import { Timeline } from "./timeline";
import { cx, formatDate, label, PanelTitle, StatusBadge } from "./ui";

const signerStatuses: SignerStatus[] = ["pending", "sent", "viewed", "signed", "declined", "expired", "cancelled"];
const terminalSignerStatuses: SignerStatus[] = ["signed", "declined", "expired", "cancelled"];
const primaryButton = "primary";
const secondaryButton = "secondary";
const iconButton = "icon-button";
const compactButton = "secondary compact";
const tableWrap = "table-wrap";
const tableClass = "data-table";
const thClass = "table-heading";
const tdClass = "table-cell";
const panelClass = "panel";
const panelCardClass = "panel panel-card";
const fieldLabelClass = "field";
const fieldControlClass = "field-control";
const mutedText = "muted";

function blankSigner(): SignerDraft {
  return { name: "", email: "", role: "", required: true };
}

export function SigningTab({ contract }: { contract: ContractDetail }) {
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
