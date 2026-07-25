import { render, screen, waitFor } from "@testing-library/react";
import { usePathname, useSearchParams } from "next/navigation";
import { beforeEach, expect, test, vi } from "vitest";

import { AuthProvider, AuthRouteLoading, RequireAuth, useAuth } from "./AuthProvider";
import { setTestUrl } from "./test-navigation";

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
  setTestUrl("/contracts");
  return render(
    <AuthProvider>
      <RequireAuth><div>Private workspace</div></RequireAuth>
      <LocationProbe />
    </AuthProvider>
  );
}

function LocationProbe() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  return <output data-testid="location">{`${pathname}${search ? `?${search}` : ""}`}</output>;
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

test("marks an unverified session without checking workspace access", async () => {
  authMocks.getAuthSession.mockResolvedValue({
    user: { id: "u1", email: "asha@example.com", name: "Asha", emailVerified: false },
    session: { token: "token" }
  });

  render(<AuthProvider><AuthStateProbe /></AuthProvider>);

  await waitFor(() => expect(screen.getByTestId("auth-state")).toHaveTextContent("unverified"));
  expect(authMocks.checkWorkspaceAccess).not.toHaveBeenCalled();
});

function AuthStateProbe() {
  const { accessStatus } = useAuth();
  return <output data-testid="auth-state">{accessStatus}</output>;
}

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

test("keeps the workspace visible during a background session refresh", async () => {
  authMocks.getAuthSession.mockResolvedValueOnce({
    user: { id: "u1", email: "asha@example.com", name: "Asha", emailVerified: true },
    session: { token: "token" }
  });
  authMocks.checkWorkspaceAccess.mockResolvedValueOnce({
    status: "allowed",
    profile: {
      user: { subject: "u1", email: "asha@example.com", name: "Asha", email_verified: true },
      account: { id: "account-1", role: "user", state: "active", workspace_id: "user-1" }
    }
  });

  renderProtectedRoute();

  expect(await screen.findByText("Private workspace")).toBeInTheDocument();

  let resolveRefresh!: (value: unknown) => void;
  authMocks.getAuthSession.mockReturnValueOnce(new Promise((resolve) => {
    resolveRefresh = resolve;
  }));
  document.dispatchEvent(new Event("visibilitychange"));

  await waitFor(() => expect(authMocks.getAuthSession).toHaveBeenCalledTimes(2));
  expect(screen.getByText("Private workspace")).toBeInTheDocument();
  expect(screen.queryByRole("main", { name: "Loading your workspace" })).not.toBeInTheDocument();

  resolveRefresh({
    user: { id: "u1", email: "asha@example.com", name: "Asha", emailVerified: true },
    session: { token: "token" }
  });
});
