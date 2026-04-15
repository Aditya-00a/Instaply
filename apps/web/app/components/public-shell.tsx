import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Minimal Coinbase-clean chrome for public/marketing pages:
 * pricing, terms, privacy, refund. Shared header + footer.
 *
 * Kept deliberately plain — no animations, no split panels. Links in
 * the header send people to sign-in; the footer surfaces the legal set.
 */
export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="public-shell">
      <header className="public-header">
        <Link href="/" className="public-brand">Instaply</Link>
        <nav className="public-nav">
          <Link href="/about">Product</Link>
          <Link href="/how-it-works">How it works</Link>
          <Link href="/pricing">Pricing</Link>
          <Link href="/contact">Contact</Link>
          <Link href="/sign-in" className="public-nav-cta">Sign in</Link>
        </nav>
      </header>

      <main className="public-main">{children}</main>

      <footer className="public-footer">
        <div className="public-footer-links">
          <Link href="/about">Product</Link>
          <Link href="/how-it-works">How it works</Link>
          <Link href="/integrations">Integrations</Link>
          <Link href="/pricing">Pricing</Link>
          <Link href="/security">Security</Link>
          <Link href="/status">Status</Link>
          <Link href="/changelog">Changelog</Link>
          <Link href="/careers">Careers</Link>
          <Link href="/terms">Terms of Service</Link>
          <Link href="/privacy">Privacy Policy</Link>
          <Link href="/refund">Refund Policy</Link>
          <Link href="/contact">Contact</Link>
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
