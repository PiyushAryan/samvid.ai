import { requestJson } from "@/lib/http-client";
import type { SignerDraft, SignerStatus, SigningRequest, SigningRequestStatus } from "./types";

export function listSigningRequests(status?: SigningRequestStatus | "") {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  return requestJson<SigningRequest[]>(`/api/signing-requests?${params.toString()}`);
}

export function createSigningRequest(contractId: string, signers: SignerDraft[]) {
  return requestJson<SigningRequest>(`/api/contracts/${contractId}/signing-requests`, {
    method: "POST",
    body: JSON.stringify({
      signers: signers.map((signer, index) => ({
        name: signer.name,
        email: signer.email,
        role: signer.role || null,
        required: signer.required,
        display_order: index
      }))
    })
  });
}

export function addSigner(requestId: string, signer: SignerDraft) {
  return requestJson<SigningRequest>(`/api/signing-requests/${requestId}/signers`, {
    method: "POST",
    body: JSON.stringify({
      name: signer.name,
      email: signer.email,
      role: signer.role || null,
      required: signer.required
    })
  });
}

export function appendSignerEvent(signerId: string, status: SignerStatus, note: string | null) {
  return requestJson<SigningRequest>(`/api/signers/${signerId}/events`, {
    method: "POST",
    body: JSON.stringify({ id: crypto.randomUUID(), status, note: note || null })
  });
}
