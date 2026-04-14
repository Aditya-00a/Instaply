"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Chrome, LockKeyhole, Mail, MoveRight, Sparkles } from "lucide-react";
import { useState } from "react";

const DEMO_EMAIL = "demo@instaply.app";
const DEMO_PASSWORD = "InstaplyDemo123!";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [error, setError] = useState("");

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (email.trim().toLowerCase() === DEMO_EMAIL.toLowerCase() && password === DEMO_PASSWORD) {
      setError("");
      router.push("/dashboard");
      return;
    }

    setError("Use the demo email and password shown below.");
  };

  return (
    <main className="auth-shell auth-shell-brand">
      <section className="auth-frame">
        <article className="auth-split-card">
          <div className="auth-form-panel">
            <div className="auth-brand-row">
              <Link className="auth-brand-mark" href="/">
                <Sparkles size={16} />
                <span>Instaply</span>
              </Link>
            </div>

            <div className="auth-copy-block">
              <h1 className="auth-heading">Welcome back</h1>
              <p className="auth-copy">Sign in to manage your applications, answers, documents, and billing in one place.</p>
            </div>

            <div className="auth-tab-row" aria-label="Authentication mode">
              <button className="auth-tab auth-tab-active" type="button">
                Sign in
              </button>
              <button className="auth-tab" type="button">
                Create account
              </button>
            </div>

            <div className="auth-demo-credentials">
              <strong>Demo access</strong>
              <span>{DEMO_EMAIL}</span>
              <span>{DEMO_PASSWORD}</span>
            </div>

            <form className="auth-form" onSubmit={handleSubmit}>
              <label className="auth-field">
                <span>Email address</span>
                <div className="auth-input-shell">
                  <Mail size={16} />
                  <input placeholder="Enter your email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
                </div>
              </label>

              <label className="auth-field">
                <span>Password</span>
                <div className="auth-input-shell">
                  <LockKeyhole size={16} />
                  <input
                    placeholder="Enter your password"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </div>
              </label>

              <div className="auth-row">
                <label className="auth-checkbox">
                  <input type="checkbox" />
                  <span>Remember me</span>
                </label>
                <Link href="/">Forgot password?</Link>
              </div>

              {error ? <div className="auth-error">{error}</div> : null}

              <button className="auth-button auth-button-primary" type="submit">
                Sign in
                <MoveRight size={16} />
              </button>
            </form>

            <div className="auth-divider">
              <span>or continue with</span>
            </div>

            <div className="auth-actions">
              <button className="auth-button auth-button-secondary" type="button">
                <Chrome size={16} />
                Continue with Google
              </button>
              <button className="auth-button auth-button-secondary" type="button">
                <Mail size={16} />
                Continue with email link
              </button>
            </div>

            <div className="auth-helper">
              <span>Private beta accounts and tester seats can sign in here.</span>
              <Link href="/">Back to website</Link>
            </div>
          </div>

          <aside className="auth-visual-panel">
            <div className="auth-visual-surface">
              <div className="auth-orb auth-orb-large" />
              <div className="auth-orb auth-orb-small" />
              <div className="auth-visual-copy">
                <p className="eyebrow">Private workspace</p>
                <h2>Review strong matches, clear blocked answers, and move tailored applications forward.</h2>
                <div className="auth-visual-pills">
                  <span className="auth-visual-pill">Matched roles</span>
                  <span className="auth-visual-pill">Saved answers</span>
                  <span className="auth-visual-pill">Tailored packets</span>
                </div>
              </div>
              <div className="auth-visual-note">Sign in to manage your profile, review queue, documents, credits, and application progress.</div>
            </div>
          </aside>
        </article>
      </section>
    </main>
  );
}
