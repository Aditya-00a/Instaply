import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Clean chrome for public/marketing pages:
 * landing, pricing, terms, privacy, refund.
 * Only links to pages that actually exist.
 */
export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="public-shell">
      <header className="public-header">
        <Link href="/" className="public-brand">Instaply</Link>
        <nav className="public-nav">
          <Link href="/pricing">Pricing</Link>
          <Link href="/about">About</Link>
          <Link href="/sign-in" className="public-nav-cta">Sign in</Link>
        </nav>
      </header>

      <main className="public-main">{children}</main>

      <footer className="public-footer">
        <div className="public-footer-links">
          <Link href="/pricing">Pricing</Link>
          <Link href="/about">About</Link>
          <Link href="/terms">Terms of Service</Link>
          <Link href="/privacy">Privacy Policy</Link>
          <Link href="/refund">Refund Policy</Link>
          <Link href="mailto:hello@asion.ai">Contact</Link>
        </div>
        <div className="public-footer-note">
          © {new Date().getFullYear()} Ravendise. Instaply is a product of
          Ravendise. We file applications — we do not guarantee interviews or
          offers.
        </div>
      </footer>
    </div>
  );
}
