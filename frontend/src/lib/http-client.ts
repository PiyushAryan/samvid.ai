import { getAccessToken } from "@/features/auth/auth";

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

function dispatchAuthorizationEvent(status: number) {
  if (status === 401) window.dispatchEvent(new Event("samvid:auth-required"));
  if (status === 403) window.dispatchEvent(new Event("samvid:access-denied"));
}

export async function responseApiError(response: Response): Promise<ApiError> {
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

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (!(init?.body instanceof FormData) && init?.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    dispatchAuthorizationEvent(response.status);
    throw await responseApiError(response);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function requestBlob(url: string, init?: RequestInit): Promise<Blob> {
  const token = await getAccessToken();
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    dispatchAuthorizationEvent(response.status);
    throw await responseApiError(response);
  }
  return response.blob();
}
