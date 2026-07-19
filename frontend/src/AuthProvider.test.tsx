import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";

import { AuthProvider, RequireAuth } from "./AuthProvider";

const authMocks = vi.hoisted(() => ({
  getAuthSession: vi.fn(),
  checkWorkspaceAccess: vi.fn(),
  signOut: vi.fn()
}));

vi.mock("./auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./auth")>();
  return {
    ...actual,
    isNeonAuthConfigured: true,
    getAuthSession: authMocks.getAuthSession,
    checkWorkspaceAccess: authMocks.checkWorkspaceAccess,
    getAuthClient: () => ({ signOut: authMocks.signOut })
  };
});

function renderProtectedRoute() {
  return render(
    <MemoryRouter initialEntries={["/contracts"]}>
      <AuthProvider>
        <Routes>
          <Route path="/auth" element={<div>Authentication route</div>} />
          <Route
            path="/contracts"
            element={<RequireAuth><div>Private workspace</div></RequireAuth>}
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authMocks.signOut.mockResolvedValue({});
});

test("routes an unverified session back to email verification", async () => {
  authMocks.getAuthSession.mockResolvedValue({
    user: { id: "u1", email: "asha@example.com", name: "Asha", emailVerified: false },
    session: { token: "token" }
  });

  renderProtectedRoute();

  expect(await screen.findByText("Authentication route")).toBeInTheDocument();
  expect(authMocks.checkWorkspaceAccess).not.toHaveBeenCalled();
});

test("shows a dedicated state when the backend allowlist rejects the account", async () => {
  authMocks.getAuthSession.mockResolvedValue({
    user: { id: "u1", email: "asha@example.com", name: "Asha", emailVerified: true },
    session: { token: "token" }
  });
  authMocks.checkWorkspaceAccess.mockResolvedValue({
    status: "denied",
    message: "This account does not have access to the Samvid workspace"
  });

  renderProtectedRoute();

  expect(await screen.findByRole("heading", { name: "This account is not authorized." })).toBeInTheDocument();
  expect(screen.getByText(/does not have access/)).toBeInTheDocument();
  expect(screen.queryByText("Private workspace")).not.toBeInTheDocument();
});

test("renders the workspace only after backend authorization succeeds", async () => {
  authMocks.getAuthSession.mockResolvedValue({
    user: { id: "u1", email: "asha@example.com", name: "Asha", emailVerified: true },
    session: { token: "token" }
  });
  authMocks.checkWorkspaceAccess.mockResolvedValue({ status: "allowed" });

  renderProtectedRoute();

  expect(await screen.findByText("Private workspace")).toBeInTheDocument();
});
