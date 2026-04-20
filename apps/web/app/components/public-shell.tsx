import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Public marketing chrome — minimal nav for the OSS-only site.
 * No pricing, no sign-in: this is a free local tool, you install it.
 */
export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="public-shell">
      <header className="public-header">
        <Link href="/" className="public-brand">Instaply</Link>
        <nav className="public-nav">
          <Link href="/about">About</Link>
          <Link
            href="https://github.com/instaply/instaply"
            className="public-nav-cta"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub →
          </Link>
        </nav>
      </header>

      <main className="public-main">{children}</main>

      <footer className="public-footer">
        <div className="public-footer-links">
          <Link href="/about">About</Link>
          <Link href="/privacy">Privacy</Link>
          <Link
            href="https://github.com/instaply/instaply"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub
          </Link>
          <Link href="mailto:hello@asion.ai">Contact</Link>
        </div>
        <div className="public-footer-note">
          © {new Date().getFullYear()} Built by the Instaply open-source community. Free forever.
          MIT licensed. A project of{" "}
          <Link
            href="https://asion.ai"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "inherit", textDecoration: "underline" }}
          >
            Ravendise
          </Link>
          .
        </div>
      </footer>
    </div>
  );
}
