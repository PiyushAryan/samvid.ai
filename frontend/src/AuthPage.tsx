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
import { getAuthClient, getAuthErrorMessage, isNeonAuthConfigured } from "./auth";
import "./auth.css";

export type AuthView = "sign-in" | "sign-up" | "forgot-password" | "verify-email";
type AuthTheme = "light" | "dark";

type AuthPageProps = {
  initialView?: AuthView;
  redirectTo?: string;
};

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
  "verify-email": {
    eyebrow: "Confirm your email",
    title: "Check your inbox",
    description: "Use the verification link or enter the verification code sent to your email."
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

export function AuthPage({ initialView = "sign-in", redirectTo = "/contracts" }: AuthPageProps) {
  const [view, setView] = useState<AuthView>(initialView);
  const [theme, setTheme] = useState<AuthTheme>(getInitialTheme);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const nameId = useId();
  const emailId = useId();
  const passwordId = useId();
  const verificationCodeId = useId();
  const errorId = useId();

  const copy = viewCopy[view];

  useEffect(() => {
    window.localStorage.setItem("samvid-theme", theme);
  }, [theme]);

  useEffect(() => {
    setView(initialView);
    setError("");
    setNotice("");
  }, [initialView]);

  const changeView = (nextView: AuthView) => {
    setView(nextView);
    setError("");
    setNotice("");
    setPassword("");
    setVerificationCode("");
    setShowPassword(false);
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
        const result = await client.requestPasswordReset({
          email: email.trim(),
          redirectTo: `${window.location.origin}/auth`
        });

        if (result.error) throw result.error;

        setNotice("Check your inbox for a secure password reset link.");
        return;
      }

      if (view === "verify-email") {
        const result = await client.emailOtp.verifyEmail({
          email: email.trim(),
          otp: verificationCode.trim()
        });
        if (result.error) throw result.error;

        const session = await client.getSession();
        if (session.data?.user?.emailVerified) {
          window.location.assign(redirectTo);
          return;
        }
        changeView("sign-in");
        setNotice("Email verified. Sign in to continue.");
        return;
      }

      const result = view === "sign-up"
        ? await client.signUp.email({
          name: name.trim() || accountNameFromEmail(email),
          email: email.trim(),
          password,
          callbackURL: `${window.location.origin}${redirectTo}`
        })
        : await client.signIn.email({
          email: email.trim(),
          password,
          rememberMe: true,
          callbackURL: `${window.location.origin}${redirectTo}`
        });

      if (result.error) throw result.error;

      if (view === "sign-up" && result.data?.user && !result.data.user.emailVerified) {
        setView("verify-email");
        setPassword("");
        setNotice(`We sent a verification message to ${email.trim()}.`);
        return;
      }

      window.location.assign(redirectTo);
    } catch (authError) {
      if (view === "sign-in" && requiresEmailVerification(authError)) {
        setView("verify-email");
        setPassword("");
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
        callbackURL: `${window.location.origin}${redirectTo}`
      });
      if (result.error) throw result.error;

      if (openVerificationView) {
        setView("verify-email");
        setPassword("");
        setVerificationCode("");
      }
      setNotice(`A new verification message was sent to ${normalizedEmail}.`);
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
          {(view === "forgot-password" || view === "verify-email") && (
            <button className="auth-back-button" type="button" onClick={() => changeView("sign-in")}>
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

            {view !== "forgot-password" && view !== "verify-email" && (
              <div className="auth-field">
                <div className="auth-label-row">
                  <label htmlFor={passwordId}>Password</label>
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
                    autoComplete={view === "sign-up" ? "new-password" : "current-password"}
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
                {view === "sign-up" && <small>Use 8 or more characters.</small>}
              </div>
            )}

            {view === "verify-email" && (
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
                    value={verificationCode}
                    onChange={(event) => setVerificationCode(event.target.value.replace(/\s/g, ""))}
                    placeholder="Enter the code from your email"
                    required
                  />
                </div>
                <small>Using a verification link? Open it in this browser instead.</small>
              </div>
            )}

            {error && <p id={errorId} className="auth-message auth-message-error" role="alert">{error}</p>}
            {notice && <p className="auth-message auth-message-success" role="status">{notice}</p>}

            <button
              className="auth-submit"
              type="submit"
              disabled={isSubmitting || (Boolean(notice) && view !== "verify-email")}
            >
              {isSubmitting ? (
                <><Loader2 className="auth-spinner" size={16} aria-hidden="true" /> Working...</>
              ) : (
                <>
                  {view === "sign-in" && "Sign in to workspace"}
                  {view === "sign-up" && "Create account"}
                  {view === "forgot-password" && "Send reset link"}
                  {view === "verify-email" && "Verify email"}
                  <ArrowRight size={16} aria-hidden="true" />
                </>
              )}
            </button>

            {view === "verify-email" && (
              <button
                className="auth-resend"
                type="button"
                disabled={isSubmitting}
                onClick={() => void resendVerification()}
              >
                Didn&apos;t receive it? Resend verification code
              </button>
            )}
          </form>

          {view === "sign-in" && (
            <button
              className="auth-verify-help"
              type="button"
              disabled={isSubmitting}
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
