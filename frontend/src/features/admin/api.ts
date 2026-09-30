import { requestBlob, requestJson } from "@/lib/http-client";
import type { ContractDetail, ContractListItem } from "@/features/contracts/types";
import type { SigningRequest } from "@/features/signing/types";
import type { AdminAccessEvent, AdminCollection, AdminUserDetail, AdminUserSummary, CollectionResponse } from "./types";

function adminParams(filters: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listAdminUsers(filters: { search?: string; state?: string; page?: number } = {}) {
  return requestJson<CollectionResponse<AdminUserSummary>>(`/api/admin/users${adminParams(filters)}`);
}

export function getAdminUser(userId: string) {
  return requestJson<AdminUserDetail>(`/api/admin/users/${encodeURIComponent(userId)}`);
}

export function listAdminUserContracts(
  userId: string,
  filters: { search?: string; reviewStatus?: string; signingStatus?: string; page?: number } = {}
) {
  return requestJson<CollectionResponse<ContractListItem>>(
    `/api/admin/users/${encodeURIComponent(userId)}/contracts${adminParams({
      search: filters.search,
      review_status: filters.reviewStatus,
      signing_status: filters.signingStatus,
      page: filters.page
    })}`
  );
}

export function getAdminContract(contractId: string) {
  return requestJson<ContractDetail>(`/api/admin/contracts/${encodeURIComponent(contractId)}`);
}

export function getAdminContractDocument(contractId: string) {
  return requestBlob(`/api/admin/contracts/${encodeURIComponent(contractId)}/document`);
}

export function getAdminContractSigning(contractId: string) {
  return requestJson<SigningRequest[] | AdminCollection<SigningRequest>>(
    `/api/admin/contracts/${encodeURIComponent(contractId)}/signing`
  );
}

export function listAdminAccessEvents(filters: { search?: string; eventType?: string; page?: number } = {}) {
  return requestJson<CollectionResponse<AdminAccessEvent>>(
    `/api/admin/access-events${adminParams({
      search: filters.search,
      event_type: filters.eventType,
      page: filters.page
    })}`
  );
}
