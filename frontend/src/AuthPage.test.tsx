import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { AuthPage } from "./AuthPage";
import { safeInternalPath } from "./auth";

const authClient = vi.hoisted(() => ({
  signUp: { email: vi.fn() },
  signIn: { email: vi.fn() },
  emailOtp: {
    verifyEmail: vi.fn()
  },
  sendVerificationEmail: vi.fn(),
  getSession: vi.fn(),
  requestPasswordReset: vi.fn(),
  resetPassword: vi.fn(),
  signOut: vi.fn()
}));

vi.mock("./auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./auth")>();
  return {
    ...actual,
    isNeonAuthConfigured: true,
    getAuthClient: () => authClient
  };
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderAuth(
  initialView: Parameters<typeof AuthPage>[0]["initialView"],
  initialEntry = `/auth${initialView && initialView !== "sign-in" ? `?view=${initialView}` : ""}`,
  initialEmail = ""
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthPage initialView={initialView} initialEmail={initialEmail} />
      <LocationProbe />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  authClient.signUp.email.mockResolvedValue({ data: null, error: null });
  authClient.signIn.email.mockResolvedValue({ data: null, error: null });
  authClient.emailOtp.verifyEmail.mockResolvedValue({ data: null, error: null });
  authClient.sendVerificationEmail.mockResolvedValue({ data: { status: true }, error: null });
  authClient.getSession.mockResolvedValue({ data: null, error: null });
  authClient.requestPasswordReset.mockResolvedValue({ data: { status: true }, error: null });
  authClient.resetPassword.mockResolvedValue({ data: { status: true }, error: null });
  authClient.signOut.mockResolvedValue({ data: { success: true }, error: null });
});

describe("Samvid authentication", () => {
  test("continues an unverified signup in a locked verification-code view", async () => {
    authClient.signUp.email.mockResolvedValue({
      data: { user: { emailVerified: false } },
      error: null
    });
    renderAuth("sign-up");

    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Asha Nair" } });
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "asha@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secure-pass-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Check your inbox" })).toBeInTheDocument();
    expect(screen.getByText("asha@example.com")).toBeInTheDocument();
    expect(screen.getByText("We sent a verification message to asha@example.com.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Work email")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Verification code")).toHaveAttribute("maxlength", "6");
    expect(window.sessionStorage.getItem("samvid-pending-auth-email")).toBe("asha@example.com");
  });

  test("resends verification with Neon's configured verification method", async () => {
    renderAuth("verify-email", "/auth?view=verify-email", "asha@example.com");

    fireEvent.click(screen.getByRole("button", { name: /resend verification code/i }));

    await waitFor(() => {
      expect(authClient.sendVerificationEmail).toHaveBeenCalledWith({
        email: "asha@example.com",
        callbackURL: expect.stringContaining("/contracts")
      });
    });
    expect(screen.getByRole("button", { name: /resend available in 30s/i })).toBeDisabled();
  });

  test("requests a password reset with a dedicated callback", async () => {
    renderAuth("forgot-password");
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "asha@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));

    await waitFor(() => expect(authClient.requestPasswordReset).toHaveBeenCalledOnce());
    expect(authClient.requestPasswordReset.mock.calls[0][0]).toEqual({
      email: "asha@example.com",
      redirectTo: expect.stringContaining("/auth?view=reset-password")
    });
    expect(screen.getByText(/if an account exists/i)).toBeInTheDocument();
  });

  test("consumes a reset token and removes it from navigation history", async () => {
    renderAuth("reset-password", "/auth?view=reset-password&token=reset-token");
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-password-123" } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "new-password-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    await waitFor(() => {
      expect(authClient.resetPassword).toHaveBeenCalledWith({
        newPassword: "new-password-123",
        token: "reset-token"
      });
    });
    expect(screen.getByTestId("location")).toHaveTextContent("/auth?reset=complete");
    expect(screen.getByText("Password updated. Sign in with your new password.")).toBeInTheDocument();
  });

  test("rejects browser-normalized external return paths", () => {
    expect(safeInternalPath("/contracts?status=ready")).toBe("/contracts?status=ready");
    expect(safeInternalPath("https://example.com/contracts")).toBe("/contracts");
    expect(safeInternalPath("/\\example.com/contracts")).toBe("/contracts");
  });
});
