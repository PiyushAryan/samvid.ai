import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";

import { AuthProvider, AuthRouteLoading, RequireAuth } from "./AuthProvider";

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
  window.localStorage.clear();
  authMocks.signOut.mockResolvedValue({});
});

test("uses the saved theme favicon while authentication is loading", () => {
  window.localStorage.setItem("samvid-theme", "dark");

  render(<AuthRouteLoading label="Checking your session" />);

  expect(screen.getByRole("main", { name: "Checking your session" })).toHaveAttribute("data-theme", "dark");
  expect(document.querySelector(".auth-route-loading-logo")).toHaveAttribute("src", "/favicon-dark.svg");
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

test("shows a dedicated state when account provisioning rejects access", async () => {
  authMocks.getAuthSession.mockResolvedValue({
    user: { id: "u1", email: "asha@example.com", name: "Asha", emailVerified: true },
    session: { token: "token" }
  });
  authMocks.checkWorkspaceAccess.mockResolvedValue({
    status: "denied",
    message: "This account does not have access to the Samvid workspace"
  });

  renderProtectedRoute();

  expect(await screen.findByRole("heading", { name: "This account is not available." })).toBeInTheDocument();
  expect(screen.getByText(/does not have access/)).toBeInTheDocument();
  expect(screen.queryByText("Private workspace")).not.toBeInTheDocument();
});

test("renders the workspace only after backend authorization succeeds", async () => {
  authMocks.getAuthSession.mockResolvedValue({
    user: { id: "u1", email: "asha@example.com", name: "Asha", emailVerified: true },
    session: { token: "token" }
  });
  authMocks.checkWorkspaceAccess.mockResolvedValue({
    status: "allowed",
    profile: {
      user: { subject: "u1", email: "asha@example.com", name: "Asha", email_verified: true },
      account: { id: "account-1", role: "user", state: "active", workspace_id: "user-1" }
    }
  });

  renderProtectedRoute();

  expect(await screen.findByText("Private workspace")).toBeInTheDocument();
});
