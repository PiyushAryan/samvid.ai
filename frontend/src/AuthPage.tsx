import {
  ArrowLeft,
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Loader2,
  LockKeyhole,
  Mail,
  Moon,
  Sun
} from "lucide-react";
import { FormEvent, useEffect, useId, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  getAuthClient,
  getAuthErrorMessage,
  isNeonAuthConfigured,
  PENDING_AUTH_EMAIL_KEY,
  safeInternalPath
} from "./auth";
import "./auth.css";

export type AuthView = "sign-in" | "sign-up" | "forgot-password" | "reset-password" | "verify-email";
type AuthTheme = "light" | "dark";

type AuthPageProps = {
  initialView?: AuthView;
  initialEmail?: string;
  redirectTo?: string;
};

const VERIFICATION_CODE_LENGTH = 6;
const RESEND_COOLDOWN_SECONDS = 30;

const viewCopy: Record<AuthView, { eyebrow: string; title: string; description: string }> = {
  "sign-in": {
    eyebrow: "Workspace access",
    title: "Welcome back",
    description: "Sign in to continue reviewing, tracking, and moving contracts forward."
  },
  "sign-up": {
    eyebrow: "Create workspace access",
    title: "Start with Samvid",
    description: "Create your account and bring every contract into one accountable workflow."
  },
  "forgot-password": {
    eyebrow: "Account recovery",
    title: "Reset your password",
    description: "Enter your work email and we will send you a secure reset link."
  },
  "reset-password": {
    eyebrow: "Account recovery",
    title: "Choose a new password",
    description: "Set a new password for your Samvid account."
  },
  "verify-email": {
    eyebrow: "Confirm your email",
    title: "Check your inbox",
    description: "Enter the six-digit verification code sent to your email."
  }
};

function getInitialTheme(): AuthTheme {
  if (typeof window === "undefined") return "light";

  const savedTheme = window.localStorage.getItem("samvid-theme");
  if (savedTheme === "light" || savedTheme === "dark") return savedTheme;

  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function accountNameFromEmail(email: string) {
  const localPart = email.split("@")[0]?.trim() || "User";
  return localPart
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function getPendingEmail() {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(PENDING_AUTH_EMAIL_KEY) || "";
}

function requiresEmailVerification(error: unknown) {
  if (!error || typeof error !== "object") return false;
  const code = "code" in error && typeof error.code === "string" ? error.code : "";
  const message = "message" in error && typeof error.message === "string" ? error.message : "";
  const normalizedMessage = message.toLowerCase();
  return code.toUpperCase().includes("EMAIL_NOT_VERIFIED")
    || normalizedMessage.includes("verification required")
    || normalizedMessage.includes("email not verified")
    || normalizedMessage.includes("verify your email");
}

export function AuthPage({ initialView = "sign-in", initialEmail = "", redirectTo = "/contracts" }: AuthPageProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const safeRedirectTo = safeInternalPath(redirectTo);
  const [view, setView] = useState<AuthView>(initialView);
  const [theme, setTheme] = useState<AuthTheme>(getInitialTheme);
  const [name, setName] = useState("");
  const [email, setEmail] = useState(() => initialEmail || getPendingEmail());
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [verificationResendSeconds, setVerificationResendSeconds] = useState(0);
  const [resetRequestSeconds, setResetRequestSeconds] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const nameId = useId();
  const emailId = useId();
  const passwordId = useId();
  const confirmPasswordId = useId();
  const verificationCodeId = useId();
  const verificationCodeHintId = useId();
  const errorId = useId();

  const copy = viewCopy[view];

  useEffect(() => {
    window.localStorage.setItem("samvid-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (view !== initialView) {
      setView(initialView);
      setError("");
      setNotice("");
    }
    if (initialEmail) setEmail(initialEmail);
    else if (initialView === "verify-email") setEmail((current) => current || getPendingEmail());
    // Internal navigation updates `view` first, so its new notice is preserved.
  }, [initialEmail, initialView]);

  useEffect(() => {
    if (verificationResendSeconds <= 0 && resetRequestSeconds <= 0) return;
    const timer = window.setInterval(() => {
      setVerificationResendSeconds((seconds) => Math.max(0, seconds - 1));
      setResetRequestSeconds((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [resetRequestSeconds, verificationResendSeconds]);

  const changeView = (nextView: AuthView, options: { replace?: boolean } = {}) => {
    setView(nextView);
    setError("");
    setNotice("");
    setPassword("");
    setConfirmPassword("");
    setVerificationCode("");
    setShowPassword(false);

    const params = new URLSearchParams();
    if (nextView !== "sign-in") params.set("view", nextView);
    if (safeRedirectTo !== "/contracts") params.set("returnTo", safeRedirectTo);
    if (nextView === "reset-password") {
      const token = new URLSearchParams(location.search).get("token");
      if (token) params.set("token", token);
    }
    const search = params.toString();
    navigate(`/auth${search ? `?${search}` : ""}`, { replace: options.replace });
  };

  const rememberPendingEmail = (value: string) => {
    window.sessionStorage.setItem(PENDING_AUTH_EMAIL_KEY, value);
    setEmail(value);
  };

  const leaveVerification = async (nextView: "sign-in" | "sign-up") => {
    setIsSubmitting(true);
    try {
      if (isNeonAuthConfigured) await getAuthClient().signOut();
    } finally {
      window.sessionStorage.removeItem(PENDING_AUTH_EMAIL_KEY);
      window.dispatchEvent(new Event("samvid:auth-required"));
      setEmail("");
      setView(nextView);
      setError("");
      setNotice("");
      setIsSubmitting(false);
      navigate(`/auth${nextView === "sign-up" ? "?view=sign-up&signedOut=1" : "?signedOut=1"}`, { replace: true });
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setNotice("");

    if (!isNeonAuthConfigured) {
      setError("Authentication is not configured for this environment.");
      return;
    }

    setIsSubmitting(true);

    try {
      const client = getAuthClient();

      if (view === "forgot-password") {
        if (resetRequestSeconds > 0) return;
        const result = await client.requestPasswordReset({
          email: email.trim(),
          redirectTo: `${window.location.origin}/auth?view=reset-password&returnTo=${encodeURIComponent(safeRedirectTo)}`
        });

        if (result.error) throw result.error;

        setResetRequestSeconds(RESEND_COOLDOWN_SECONDS);
        setNotice("If an account exists for this email, a password reset link has been sent.");
        return;
      }

      if (view === "reset-password") {
        const token = new URLSearchParams(location.search).get("token");
        if (!token || token === "INVALID_TOKEN") {
          setError("This password reset link is invalid or has expired. Request a new link.");
          return;
        }
        if (password !== confirmPassword) {
          setError("The passwords do not match.");
          return;
        }

        const result = await client.resetPassword({
          newPassword: password,
          token
        });
        if (result.error) throw result.error;

        await client.signOut();
        window.dispatchEvent(new Event("samvid:auth-required"));
        setView("sign-in");
        setPassword("");
        setConfirmPassword("");
        navigate("/auth?reset=complete", { replace: true });
        setNotice("Password updated. Sign in with your new password.");
        return;
      }

      if (view === "verify-email") {
        if (verificationCode.length !== VERIFICATION_CODE_LENGTH) {
          setError(`Enter the ${VERIFICATION_CODE_LENGTH}-digit verification code.`);
          return;
        }
        const result = await client.emailOtp.verifyEmail({
          email: email.trim(),
          otp: verificationCode
        });
        if (result.error) throw result.error;

        const session = await client.getSession();
        if (result.data?.user?.emailVerified || session.data?.user?.emailVerified) {
          window.sessionStorage.removeItem(PENDING_AUTH_EMAIL_KEY);
          window.location.assign(safeRedirectTo);
          return;
        }
        window.sessionStorage.removeItem(PENDING_AUTH_EMAIL_KEY);
        changeView("sign-in", { replace: true });
        setNotice("Email verified. Sign in to continue.");
        return;
      }

      const result = view === "sign-up"
        ? await client.signUp.email({
          name: name.trim() || accountNameFromEmail(email),
          email: email.trim(),
          password,
          callbackURL: `${window.location.origin}${safeRedirectTo}`
        })
        : await client.signIn.email({
          email: email.trim(),
          password,
          rememberMe: true,
          callbackURL: `${window.location.origin}${safeRedirectTo}`
        });

      if (result.error) throw result.error;

      if (view === "sign-up" && result.data?.user && !result.data.user.emailVerified) {
        rememberPendingEmail(email.trim());
        changeView("verify-email", { replace: true });
        setNotice(`We sent a verification message to ${email.trim()}.`);
        return;
      }

      window.location.assign(safeRedirectTo);
    } catch (authError) {
      if (view === "sign-in" && requiresEmailVerification(authError)) {
        rememberPendingEmail(email.trim());
        changeView("verify-email");
        setNotice(`Verify ${email.trim()} before signing in.`);
        return;
      }
      setError(getAuthErrorMessage(authError, "We could not complete that request. Please try again."));
    } finally {
      setIsSubmitting(false);
    }
  };

  const resendVerification = async (openVerificationView = false) => {
    setError("");
    setNotice("");

    const normalizedEmail = email.trim();
    if (!normalizedEmail) {
      setError("Enter your email address before requesting a verification code.");
      return;
    }

    if (!isNeonAuthConfigured) {
      setError("Authentication is not configured for this environment.");
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await getAuthClient().sendVerificationEmail({
        email: normalizedEmail,
        callbackURL: `${window.location.origin}${safeRedirectTo}`
      });
      if (result.error) throw result.error;

      rememberPendingEmail(normalizedEmail);
      if (openVerificationView) {
        changeView("verify-email");
      }
      setVerificationResendSeconds(RESEND_COOLDOWN_SECONDS);
      setNotice(`A new verification code was sent to ${normalizedEmail}.`);
    } catch (authError) {
      setError(getAuthErrorMessage(authError, "We could not resend the verification message."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="auth-page" data-theme={theme}>
      <div className="auth-backdrop" aria-hidden="true" />
      <div className="auth-scrim" aria-hidden="true" />

      <header className="auth-topbar">
        <a className="auth-brand" href="/" aria-label="Samvid home">
          <span className="auth-brand-mark" aria-hidden="true">S</span>
          <span>
            <strong>Samvid</strong>
            <small>Contract workspace</small>
          </span>
        </a>

        <button
          className="auth-theme-toggle"
          type="button"
          aria-label={`Use ${theme === "light" ? "dark" : "light"} appearance`}
          title={`Use ${theme === "light" ? "dark" : "light"} appearance`}
          onClick={() => setTheme((current) => current === "light" ? "dark" : "light")}
        >
          {theme === "light" ? <Moon size={17} aria-hidden="true" /> : <Sun size={17} aria-hidden="true" />}
        </button>
      </header>

      <section className="auth-layout" aria-label="Samvid authentication">
        <div className="auth-context">
          <p className="auth-context-label">SAMVID / SECURE ACCESS</p>
          <h1>The contract work that should not depend on memory.</h1>
          <p>
            Review risks, follow every version, and keep signatures moving from one focused workspace.
          </p>
          <ul className="auth-context-points" aria-label="Workspace capabilities">
            <li><Check size={15} aria-hidden="true" /> Plain-language contract review</li>
            <li><Check size={15} aria-hidden="true" /> Searchable activity and signing history</li>
            <li><Check size={15} aria-hidden="true" /> Secure, branch-aware account access</li>
          </ul>
        </div>

        <div className="auth-panel">
          {(view === "forgot-password" || view === "reset-password" || view === "verify-email") && (
            <button
              className="auth-back-button"
              type="button"
              onClick={() => view === "verify-email" ? void leaveVerification("sign-in") : changeView("sign-in")}
            >
              <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
            </button>
          )}

          <div className="auth-heading">
            <p>{copy.eyebrow}</p>
            <h2>{copy.title}</h2>
            <span>{copy.description}</span>
          </div>

          <form className="auth-form" onSubmit={handleSubmit} aria-describedby={error ? errorId : undefined}>
            {view === "sign-up" && (
              <div className="auth-field">
                <label htmlFor={nameId}>Full name</label>
                <div className="auth-input-shell">
                  <span className="auth-field-monogram" aria-hidden="true">Aa</span>
                  <input
                    id={nameId}
                    name="name"
                    type="text"
                    autoComplete="name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Your name"
                    required
                  />
                </div>
              </div>
            )}

            {view !== "reset-password" && view !== "verify-email" && (
              <div className="auth-field">
                <label htmlFor={emailId}>Work email</label>
                <div className="auth-input-shell">
                  <Mail size={16} aria-hidden="true" />
                  <input
                    id={emailId}
                    name="email"
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="you@company.com"
                    required
                  />
                </div>
              </div>
            )}

            {view !== "forgot-password" && view !== "verify-email" && (
              <div className="auth-field">
                <div className="auth-label-row">
                  <label htmlFor={passwordId}>{view === "reset-password" ? "New password" : "Password"}</label>
                  {view === "sign-in" && (
                    <button type="button" onClick={() => changeView("forgot-password")}>
                      Forgot password?
                    </button>
                  )}
                </div>
                <div className="auth-input-shell">
                  <LockKeyhole size={16} aria-hidden="true" />
                  <input
                    id={passwordId}
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete={view === "sign-up" || view === "reset-password" ? "new-password" : "current-password"}
                    minLength={8}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="At least 8 characters"
                    required
                  />
                  <button
                    className="auth-password-toggle"
                    type="button"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword((visible) => !visible)}
                  >
                    {showPassword ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
                  </button>
                </div>
                {(view === "sign-up" || view === "reset-password") && <small>Use 8 or more characters.</small>}
              </div>
            )}

            {view === "reset-password" && (
              <div className="auth-field">
                <label htmlFor={confirmPasswordId}>Confirm new password</label>
                <div className="auth-input-shell">
                  <LockKeyhole size={16} aria-hidden="true" />
                  <input
                    id={confirmPasswordId}
                    name="confirm-password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    minLength={8}
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    placeholder="Repeat your new password"
                    required
                  />
                </div>
              </div>
            )}

            {view === "verify-email" && (
              <>
                <div className="auth-email-summary">
                  <Mail size={16} aria-hidden="true" />
                  <span>
                    <small>Verification code sent to</small>
                    <strong>{email || "your email"}</strong>
                  </span>
                  <button type="button" onClick={() => void leaveVerification("sign-up")}>Change</button>
                </div>
                <div className="auth-field">
                  <label htmlFor={verificationCodeId}>Verification code</label>
                  <div className="auth-input-shell auth-code-input-shell">
                    <Mail size={16} aria-hidden="true" />
                    <input
                      id={verificationCodeId}
                      name="verification-code"
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      pattern={`[0-9]{${VERIFICATION_CODE_LENGTH}}`}
                      maxLength={VERIFICATION_CODE_LENGTH}
                      aria-describedby={verificationCodeHintId}
                      value={verificationCode}
                      onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, "").slice(0, VERIFICATION_CODE_LENGTH))}
                      placeholder="000000"
                      required
                    />
                  </div>
                  <small id={verificationCodeHintId}>Codes expire after 15 minutes.</small>
                </div>
              </>
            )}

            {error && <p id={errorId} className="auth-message auth-message-error" role="alert">{error}</p>}
            {notice && <p className="auth-message auth-message-success" role="status">{notice}</p>}

            <button
              className="auth-submit"
              type="submit"
              disabled={isSubmitting || (view === "forgot-password" && resetRequestSeconds > 0)}
            >
              {isSubmitting ? (
                <><Loader2 className="auth-spinner" size={16} aria-hidden="true" /> Working...</>
              ) : (
                <>
                  {view === "sign-in" && "Sign in to workspace"}
                  {view === "sign-up" && "Create account"}
                  {view === "forgot-password" && (resetRequestSeconds > 0
                    ? `Send again in ${resetRequestSeconds}s`
                    : notice ? "Send another reset link" : "Send reset link")}
                  {view === "reset-password" && "Update password"}
                  {view === "verify-email" && "Verify email"}
                  <ArrowRight size={16} aria-hidden="true" />
                </>
              )}
            </button>

            {view === "verify-email" && (
              <button
                className="auth-resend"
                type="button"
                disabled={isSubmitting || verificationResendSeconds > 0}
                onClick={() => void resendVerification()}
              >
                {verificationResendSeconds > 0
                  ? `Resend available in ${verificationResendSeconds}s`
                  : "Didn't receive it? Resend verification code"}
              </button>
            )}
          </form>

          {view === "sign-in" && (
            <button
              className="auth-verify-help"
              type="button"
              disabled={isSubmitting || verificationResendSeconds > 0}
              onClick={() => void resendVerification(true)}
            >
              Email not verified? Resend verification code
            </button>
          )}

          {view !== "forgot-password" && (
            <p className="auth-switch">
              {view === "sign-in" ? "New to Samvid?" : "Already have access?"}
              <button type="button" onClick={() => changeView(view === "sign-in" ? "sign-up" : "sign-in")}>
                {view === "sign-in" ? "Create an account" : "Sign in"}
              </button>
            </p>
          )}

          <p className="auth-legal">
            By continuing, you agree to Samvid&apos;s Terms and Privacy Policy.
          </p>
        </div>
      </section>
    </main>
  );
}

export default AuthPage;
