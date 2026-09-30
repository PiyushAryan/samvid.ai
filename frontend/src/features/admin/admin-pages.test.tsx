import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import { AdminAccessEventsPage } from "./access-events-page";
import { AdminContractDetailPage } from "./contract-detail-page";
import { AdminUserDetailPage } from "./user-detail-page";
import { AdminUsersPage } from "./users-page";
import * as adminApi from "./api";
import { setTestUrl } from "@/test/mocks/next-navigation";

vi.mock("./api", () => ({
  getAdminContract: vi.fn(),
  getAdminContractDocument: vi.fn(),
  getAdminContractSigning: vi.fn(),
  getAdminUser: vi.fn(),
  listAdminAccessEvents: vi.fn(),
  listAdminUserContracts: vi.fn(),
  listAdminUsers: vi.fn()
}));

function renderPage(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  setTestUrl("/admin/users");
});

test("admin users renders an empty account state", async () => {
  vi.mocked(adminApi.listAdminUsers).mockResolvedValue([]);
  renderPage(<AdminUsersPage />);
  expect(await screen.findByText("No user accounts match these filters.")).toBeInTheDocument();
});

test("admin user detail renders profile data and an empty contract state", async () => {
  setTestUrl("/admin/users/user-1");
  vi.mocked(adminApi.getAdminUser).mockResolvedValue({
    id: "user-1",
    email: "owner@example.com",
    name: "Contract Owner",
    role: "user",
    state: "active",
    source: "signup",
    workspace_id: "workspace-1",
    contract_count: 0,
    claimed_at: "2026-07-01T10:00:00Z",
    created_at: "2026-07-01T10:00:00Z"
  });
  vi.mocked(adminApi.listAdminUserContracts).mockResolvedValue([]);
  renderPage(<AdminUserDetailPage />);
  expect(await screen.findByRole("heading", { name: "Contract Owner" })).toBeInTheDocument();
  expect(await screen.findByText("This account has no matching contracts.")).toBeInTheDocument();
});

test("admin contract signing tab renders its empty state", async () => {
  setTestUrl("/admin/contracts/contract-1?tab=signing");
  vi.mocked(adminApi.getAdminContract).mockResolvedValue({
    id: "contract-1",
    title: "Services agreement",
    review_status: "review_ready",
    created_by: "user-1",
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:00:00Z",
    current_version_id: "version-1",
    original_filename: "services.pdf",
    mime_type: "application/pdf",
    risk_counts: { critical: 0, high: 0, medium: 0, low: 0 },
    signing_summary: { active_request_id: null, status: null, required_signed: 0, required_total: 0, signer_total: 0 },
    current_version: { id: "version-1", original_filename: "services.pdf", mime_type: "application/pdf", size_bytes: 1, sha256: "hash", created_at: "2026-07-01T10:00:00Z" },
    review: null,
    signing_requests: []
  });
  vi.mocked(adminApi.getAdminContractSigning).mockResolvedValue([]);
  renderPage(<AdminContractDetailPage />);
  expect(await screen.findByText("No signing activity has been recorded.")).toBeInTheDocument();
});

test("admin access events exposes a recoverable query error", async () => {
  setTestUrl("/admin/access-events");
  vi.mocked(adminApi.listAdminAccessEvents).mockRejectedValue(new Error("Audit service unavailable"));
  renderPage(<AdminAccessEventsPage />);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Audit service unavailable"));
});
