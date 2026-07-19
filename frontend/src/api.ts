import { upload } from "@vercel/blob/client";
import { getAccessToken } from "./auth";

import type {
  ContractDetail,
  ContractListItem,
  SignerDraft,
  SignerStatus,
  SigningRequest,
  SigningRequestStatus
} from "./types";

export interface ApiErrorPayload {
  code?: string;
  message?: string;
  detail?: unknown;
}

export class ApiError extends Error {
  status: number;
  payload: ApiErrorPayload;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message || `Request failed with ${status}`);
    this.status = status;
    this.payload = payload;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (!(init?.body instanceof FormData) && init?.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(url, {
    ...init,
    headers
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("samvid:auth-required"));
    if (response.status === 403) window.dispatchEvent(new Event("samvid:access-denied"));
    let payload: ApiErrorPayload = {};
    try {
      const parsed = await response.json();
      payload = parsed.detail && typeof parsed.detail === "object" ? parsed.detail : { detail: parsed.detail };
    } catch {
      payload = { message: response.statusText };
    }
    throw new ApiError(response.status, payload);
  }
  return response.json() as Promise<T>;
}

export function listContracts(filters: { search?: string; reviewStatus?: string; signingStatus?: string }) {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.reviewStatus) params.set("review_status", filters.reviewStatus);
  if (filters.signingStatus) params.set("signing_status", filters.signingStatus);
  return request<ContractListItem[]>(`/api/contracts?${params.toString()}`);
}

export function getContract(contractId: string) {
  return request<ContractDetail>(`/api/contracts/${contractId}`);
}

export function listSigningRequests(status?: SigningRequestStatus | "") {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  return request<SigningRequest[]>(`/api/signing-requests?${params.toString()}`);
}

export function createSigningRequest(contractId: string, signers: SignerDraft[]) {
  return request<SigningRequest>(`/api/contracts/${contractId}/signing-requests`, {
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
  return request<SigningRequest>(`/api/signing-requests/${requestId}/signers`, {
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
  return request<SigningRequest>(`/api/signers/${signerId}/events`, {
    method: "POST",
    body: JSON.stringify({
      id: crypto.randomUUID(),
      status,
      note: note || null
    })
  });
}

export async function uploadContract(file: File, onProgress: (percent: number) => void): Promise<unknown> {
  if (import.meta.env.PROD) {
    return uploadContractThroughBlob(file, onProgress);
  }

  const token = await getAccessToken();
  const form = new FormData();
  form.append("file", file);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/contracts");
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText || "{}"));
        return;
      }
      try {
        const parsed = JSON.parse(xhr.responseText);
        reject(new ApiError(xhr.status, parsed.detail || parsed));
      } catch {
        reject(new ApiError(xhr.status, { message: xhr.statusText }));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, { message: "Upload failed." }));
    xhr.send(form);
  });
}

async function uploadContractThroughBlob(file: File, onProgress: (percent: number) => void): Promise<unknown> {
  const token = await getAccessToken();
  const safeFilename = file.name.replace(/[^a-zA-Z0-9._-]/g, "-");
  const blob = await upload(`contracts/${crypto.randomUUID()}/${safeFilename}`, file, {
    access: "private",
    handleUploadUrl: "/api/blob-upload",
    headers: { Authorization: `Bearer ${token}` },
    contentType: file.type || undefined,
    multipart: file.size > 5 * 1024 * 1024,
    onUploadProgress: ({ percentage }) => onProgress(Math.min(90, Math.round(percentage * 0.9)))
  });
  onProgress(92);
  const result = await request<unknown>("/api/contracts/from-blob", {
    method: "POST",
    body: JSON.stringify({
      pathname: blob.pathname,
      original_filename: file.name,
      content_type: file.type || blob.contentType || null
    })
  });
  onProgress(100);
  return result;
}

export async function getContractDocument(contractId: string): Promise<Blob> {
  const token = await getAccessToken();
  const response = await fetch(`/api/contracts/${contractId}/document`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("samvid:auth-required"));
    if (response.status === 403) window.dispatchEvent(new Event("samvid:access-denied"));
    throw new ApiError(response.status, { message: response.statusText || "Unable to load document" });
  }
  return response.blob();
}
