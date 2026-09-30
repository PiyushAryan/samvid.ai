import { upload } from "@vercel/blob/client";
import { getAccessToken, getCurrentAccount } from "@/lib/auth-session";
import { ApiError, requestBlob, requestJson } from "@/lib/http-client";
import type { ContractDetail, ContractListItem } from "./types";

export type ContractUploadStage = "uploading" | "starting_review";

export interface ContractUploadProgress {
  percentage: number;
  stage: ContractUploadStage;
}

export interface ContractUploadResult {
  contract_id: string;
  contract_version_id: string;
  status: string;
  message: string;
}

export function listContracts(filters: { search?: string; reviewStatus?: string; signingStatus?: string }) {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.reviewStatus) params.set("review_status", filters.reviewStatus);
  if (filters.signingStatus) params.set("signing_status", filters.signingStatus);
  return requestJson<ContractListItem[]>(`/api/contracts?${params.toString()}`);
}

export function getContract(contractId: string) {
  return requestJson<ContractDetail>(`/api/contracts/${contractId}`);
}

export function deleteContract(contractId: string) {
  return requestJson<void>(`/api/contracts/${encodeURIComponent(contractId)}`, { method: "DELETE" });
}

const fileUploadTimeoutMs = 120_000;
const reviewStartTimeoutMs = 45_000;

async function withUploadTimeout<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number,
  timeoutMessage: string,
  parentSignal?: AbortSignal
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const abortFromParent = () => controller.abort(parentSignal?.reason);
  if (parentSignal?.aborted) abortFromParent();
  else parentSignal?.addEventListener("abort", abortFromParent, { once: true });
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    return await operation(controller.signal);
  } catch (error) {
    if (timedOut) throw new ApiError(408, { code: "upload_timeout", message: timeoutMessage });
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
    parentSignal?.removeEventListener("abort", abortFromParent);
  }
}

export async function uploadContract(
  file: File,
  onProgress: (progress: ContractUploadProgress) => void,
  signal?: AbortSignal
): Promise<ContractUploadResult> {
  if (process.env.NODE_ENV === "production") return uploadContractThroughBlob(file, onProgress, signal);

  const token = await getAccessToken();
  const form = new FormData();
  form.append("file", file);
  onProgress({ percentage: 0, stage: "uploading" });
  return withUploadTimeout(
    (requestSignal) => new Promise<ContractUploadResult>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const abortRequest = () => xhr.abort();
      requestSignal.addEventListener("abort", abortRequest, { once: true });
      xhr.open("POST", "/api/contracts");
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress({ percentage: Math.round((event.loaded / event.total) * 100), stage: "uploading" });
        }
      };
      xhr.upload.onload = () => onProgress({ percentage: 100, stage: "starting_review" });
      xhr.onload = () => {
        requestSignal.removeEventListener("abort", abortRequest);
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText || "{}") as ContractUploadResult);
          return;
        }
        try {
          const parsed = JSON.parse(xhr.responseText);
          reject(new ApiError(xhr.status, parsed.detail || parsed));
        } catch {
          reject(new ApiError(xhr.status, { message: xhr.statusText }));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, { message: "Upload failed. Check your connection and try again." }));
      xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
      xhr.send(form);
    }),
    fileUploadTimeoutMs,
    "The upload took too long. Check your connection and try again.",
    signal
  );
}

async function uploadContractThroughBlob(
  file: File,
  onProgress: (progress: ContractUploadProgress) => void,
  signal?: AbortSignal
): Promise<ContractUploadResult> {
  const token = await getAccessToken();
  const account = getCurrentAccount();
  if (account?.role !== "user" || !account.workspace_id) {
    throw new ApiError(403, { message: "A personal Samvid account is required to upload contracts." });
  }
  const safeFilename = file.name.replace(/[^a-zA-Z0-9._-]/g, "-");
  onProgress({ percentage: 0, stage: "uploading" });
  const blob = await withUploadTimeout(
    (uploadSignal) => upload(`contracts/${account.workspace_id}/${crypto.randomUUID()}/${safeFilename}`, file, {
      access: "private",
      handleUploadUrl: "/api/blob-upload",
      headers: { Authorization: `Bearer ${token}` },
      contentType: file.type || undefined,
      multipart: file.size > 5 * 1024 * 1024,
      abortSignal: uploadSignal,
      onUploadProgress: ({ percentage }) => onProgress({ percentage: Math.round(percentage), stage: "uploading" })
    }),
    fileUploadTimeoutMs,
    "The file upload took too long. Check your connection and try again.",
    signal
  );
  onProgress({ percentage: 100, stage: "starting_review" });
  return withUploadTimeout(
    (registrationSignal) => requestJson<ContractUploadResult>("/api/contracts/from-blob", {
      method: "POST",
      body: JSON.stringify({
        pathname: blob.pathname,
        original_filename: file.name,
        content_type: file.type || blob.contentType || null
      }),
      signal: registrationSignal
    }),
    reviewStartTimeoutMs,
    "The file was uploaded, but starting its review took too long. Refresh Contracts before trying again.",
    signal
  );
}

export function getContractDocument(contractId: string) {
  return requestBlob(`/api/contracts/${contractId}/document`);
}
