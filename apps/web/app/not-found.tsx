import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "./components/public-shell";

export const metadata: Metadata = {
  title: "Page not found",
};

export default function NotFound() {
  return (
    <PublicShell>
      <div className="not-found-shell">
        <div className="not-found-code">404 — not found</div>
        <h1 className="not-found-title">We couldn&apos;t find that page.</h1>
        <p className="not-found-body">
          The link may be broken or the page may have moved. Try one of
          the places below.
        </p>
        <div className="not-found-actions">
          <Link href="/" className="landing-cta">Go home</Link>
          <Link href="/pricing" className="landing-cta landing-cta-secondary">See pricing</Link>
          <Link href="/how-it-works" className="landing-cta landing-cta-secondary">How it works</Link>
        </div>
      </div>
    </PublicShell>
  );
}
