import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Instaply — Agentic job applications",
  description:
    "Instaply files real job applications on your behalf. $1 per confirmed submission. By Ravendise.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-ink text-white min-h-screen antialiased">
        <header className="border-b border-white/10">
          <nav className="mx-auto max-w-5xl flex items-center justify-between px-6 py-4">
            <a href="/" className="font-semibold tracking-tight">
              Instaply
            </a>
            <div className="flex gap-5 text-sm text-white/70">
              <a href="/applications" className="hover:text-white">Applications</a>
              <a href="/billing" className="hover:text-white">Billing</a>
              <a href="/settings/mcp" className="hover:text-white">MCP</a>
              <a href="/signup" className="hover:text-white">Sign in</a>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-5xl px-6 py-10 text-xs text-white/50 space-y-3 border-t border-white/10 mt-10">
          <nav className="flex flex-wrap gap-x-5 gap-y-2">
            <a href="/pricing" className="hover:text-white">Pricing</a>
            <a href="/terms" className="hover:text-white">Terms of Service</a>
            <a href="/privacy" className="hover:text-white">Privacy Policy</a>
            <a href="/refund" className="hover:text-white">Refund Policy</a>
            <a href="mailto:support@asion.ai" className="hover:text-white">Contact</a>
          </nav>
          <div>
            © {new Date().getFullYear()} Ravendise. Instaply is a product of Ravendise.
            We file applications — we do not guarantee interviews or offers.
          </div>
        </footer>
      </body>
    </html>
  );
}
