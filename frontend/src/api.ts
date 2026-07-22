import { upload } from "@vercel/blob/client";
import { getAccessToken, getCurrentAccount } from "./auth";

import type {
  AdminAccessEvent,
  AdminCollection,
  AdminUserDetail,
  AdminUserSummary,
  ChatMessage,
  ChatSession,
  ChatSessionSummary,
  ChatSource,
  ContractDetail,
  ContractListItem,
  SignerDraft,
  SignerStatus,
  SigningRequest,
  SigningRequestStatus
} from "./types";

export type CollectionResponse<T> = T[] | AdminCollection<T>;

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
  if (response.status === 204) return undefined as T;
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

export function deleteContract(contractId: string) {
  return request<void>(`/api/contracts/${encodeURIComponent(contractId)}`, {
    method: "DELETE"
  });
}

function collectionItems<T>(response: T[] | { items: T[] }): T[] {
  return Array.isArray(response) ? response : response.items;
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  const response = await request<ChatSessionSummary[] | { items: ChatSessionSummary[] }>("/api/chats");
  return collectionItems(response);
}

export function createChatSession(title?: string) {
  return request<ChatSession>("/api/chats", {
    method: "POST",
    body: JSON.stringify({ title: title?.trim() || null })
  });
}

export function getChatSession(sessionId: string) {
  return request<ChatSession>(`/api/chats/${encodeURIComponent(sessionId)}`);
}

export interface ChatStreamHandlers {
  onDelta?: (delta: string) => void;
  onSources?: (sources: ChatSource[]) => void;
  onMessage?: (message: ChatMessage) => void;
}

export async function streamChatMessage(
  sessionId: string,
  content: string,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const token = await getAccessToken();
  const response = await fetch(`/api/chats/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ content }),
    signal
  });

  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("samvid:auth-required"));
    if (response.status === 403) window.dispatchEvent(new Event("samvid:access-denied"));
    throw await responseApiError(response);
  }

  if (response.headers.get("content-type")?.includes("application/json")) {
    const message = await response.json() as ChatMessage;
    handlers.onMessage?.(message);
    return;
  }
  if (!response.body) throw new ApiError(502, { message: "The chat stream did not return a response body." });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    blocks.forEach((block) => dispatchChatStreamBlock(block, handlers));
    if (done) break;
  }
  if (buffer.trim()) dispatchChatStreamBlock(buffer, handlers);
}

function dispatchChatStreamBlock(block: string, handlers: ChatStreamHandlers) {
  let eventName = "message";
  const data: string[] = [];
  block.split(/\r?\n/).forEach((line) => {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  });
  if (!data.length) return;

  const raw = data.join("\n");
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    payload = { delta: raw };
  }
  const type = String(payload.type || eventName).replace(/_/g, ".");
  if (["message.delta", "delta", "token"].includes(type)) {
    const delta = payload.delta ?? payload.token ?? payload.content;
    if (typeof delta === "string") handlers.onDelta?.(delta);
    return;
  }
  if (["message.sources", "sources"].includes(type) && Array.isArray(payload.sources)) {
    handlers.onSources?.(payload.sources as unknown as ChatSource[]);
    return;
  }
  if (["message.completed", "completed", "done"].includes(type) && payload.message) {
    handlers.onMessage?.(payload.message as unknown as ChatMessage);
    return;
  }
  if (type === "error") {
    throw new ApiError(502, {
      code: typeof payload.code === "string" ? payload.code : undefined,
      message: typeof payload.message === "string" ? payload.message : "The chat stream failed."
    });
  }
}

async function responseApiError(response: Response): Promise<ApiError> {
  let payload: ApiErrorPayload = { message: response.statusText || "Request failed." };
  try {
    const parsed = await response.json();
    payload = parsed.detail && typeof parsed.detail === "object"
      ? parsed.detail
      : { message: typeof parsed.detail === "string" ? parsed.detail : parsed.message };
  } catch {
    // Keep the status-text fallback for non-JSON responses.
  }
  return new ApiError(response.status, payload);
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
  const account = getCurrentAccount();
  if (account?.role !== "user" || !account.workspace_id) {
    throw new ApiError(403, { message: "A personal Samvid account is required to upload contracts." });
  }
  const safeFilename = file.name.replace(/[^a-zA-Z0-9._-]/g, "-");
  const blob = await upload(`contracts/${account.workspace_id}/${crypto.randomUUID()}/${safeFilename}`, file, {
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
  return requestBlob(`/api/contracts/${contractId}/document`);
}

async function requestBlob(url: string): Promise<Blob> {
  const token = await getAccessToken();
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("samvid:auth-required"));
    if (response.status === 403) window.dispatchEvent(new Event("samvid:access-denied"));
    throw new ApiError(response.status, { message: response.statusText || "Unable to load document" });
  }
  return response.blob();
}

function adminParams(filters: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listAdminUsers(filters: { search?: string; state?: string; page?: number } = {}) {
  return request<CollectionResponse<AdminUserSummary>>(`/api/admin/users${adminParams(filters)}`);
}

export function getAdminUser(userId: string) {
  return request<AdminUserDetail>(`/api/admin/users/${encodeURIComponent(userId)}`);
}

export function listAdminUserContracts(
  userId: string,
  filters: { search?: string; reviewStatus?: string; signingStatus?: string; page?: number } = {}
) {
  return request<CollectionResponse<ContractListItem>>(
    `/api/admin/users/${encodeURIComponent(userId)}/contracts${adminParams({
      search: filters.search,
      review_status: filters.reviewStatus,
      signing_status: filters.signingStatus,
      page: filters.page
    })}`
  );
}

export function getAdminContract(contractId: string) {
  return request<ContractDetail>(`/api/admin/contracts/${encodeURIComponent(contractId)}`);
}

export function getAdminContractDocument(contractId: string) {
  return requestBlob(`/api/admin/contracts/${encodeURIComponent(contractId)}/document`);
}

export function getAdminContractSigning(contractId: string) {
  return request<SigningRequest[] | { items: SigningRequest[] }>(
    `/api/admin/contracts/${encodeURIComponent(contractId)}/signing`
  );
}

export function listAdminAccessEvents(filters: { search?: string; eventType?: string; page?: number } = {}) {
  return request<CollectionResponse<AdminAccessEvent>>(
    `/api/admin/access-events${adminParams({
      search: filters.search,
      event_type: filters.eventType,
      page: filters.page
    })}`
  );
}
