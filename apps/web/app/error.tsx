"use client";

import Link from "next/link";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="not-found-shell" style={{ minHeight: "70vh" }}>
      <div className="not-found-code">Something went wrong</div>
      <h2 className="not-found-title">We hit an unexpected error.</h2>
      <p className="not-found-body">
        {error.message || "The page could not load. Try refreshing, or contact us if it persists."}
      </p>
      <div className="not-found-actions">
        <button onClick={reset} className="landing-cta" type="button">
          Try again
        </button>
        <Link href="/dashboard" className="landing-cta landing-cta-secondary">
          Go to dashboard
        </Link>
        <Link href="/contact" className="landing-cta landing-cta-secondary">
          Contact support
        </Link>
      </div>
    </div>
  );
}
