"use client";

import Link from "next/link";
import { ChevronRight, Menu, X } from "lucide-react";
import { useEffect, useState } from "react";

import { consoleNavItems } from "../console-data";
import { SignOutButton } from "./sign-out-button";
import { CreditBadge } from "./credit-badge";
import { getBrowserSupabase } from "../lib/supabase-browser";

interface ConsoleAction {
  href: string;
  label: string;
  variant?: "primary" | "secondary";
}

interface ConsoleShellProps {
  activePath: string;
  eyebrow: string;
  title: string;
  description?: string;
  actions?: ConsoleAction[];
  children: React.ReactNode;
  aside?: React.ReactNode;
}

export function ConsoleShell({
  activePath,
  eyebrow,
  title,
  description,
  actions = [],
  children,
  aside,
}: ConsoleShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const workspaceItems = consoleNavItems.filter((i) => i.section === "workspace");
  const accountItems = consoleNavItems.filter((i) => i.section === "account");

  // Close mobile nav on route change
  useEffect(() => {
    setMobileNavOpen(false);
  }, [activePath]);

  // Load user email
  useEffect(() => {
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (user?.email) setUserEmail(user.email);
    })();
  }, []);

  // Lock body scroll when mobile menu is open
  useEffect(() => {
    if (mobileNavOpen) {
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = "";
      };
    }
  }, [mobileNavOpen]);

  return (
    <main className="console-app">
      {/* Mobile top bar */}
      <div className="console-mobile-bar">
        <button
          type="button"
          className="console-mobile-trigger"
          onClick={() => setMobileNavOpen(true)}
          aria-label="Open menu"
        >
          <Menu size={18} />
        </button>
        <strong>Instaply</strong>
        <CreditBadge />
      </div>

      <aside
        className={`console-sidebar glass${mobileNavOpen ? " console-sidebar-open" : ""}`}
      >
        <button
          type="button"
          className="console-mobile-close"
          onClick={() => setMobileNavOpen(false)}
          aria-label="Close menu"
        >
          <X size={18} />
        </button>

        <div className="console-brand">
          <div>
            <strong>Instaply</strong>
            <p>Your job application workspace</p>
          </div>
        </div>

        <div className="console-credit-row">
          <CreditBadge />
        </div>

        <div className="console-sidebar-section">
          <span className="console-sidebar-label">Workspace</span>
          <nav className="console-nav">
            {workspaceItems.map((item) => (
              <Link
                className={
                  item.href === activePath
                    ? "console-nav-link console-nav-link-active"
                    : "console-nav-link"
                }
                href={item.href}
                key={item.href}
              >
                <span>{item.label}</span>
                {item.href === activePath ? <ChevronRight size={16} /> : null}
              </Link>
            ))}
          </nav>
        </div>

        <div className="console-sidebar-section">
          <span className="console-sidebar-label">Account</span>
          <nav className="console-nav">
            {accountItems.map((item) => (
              <Link
                className={
                  item.href === activePath
                    ? "console-nav-link console-nav-link-active"
                    : "console-nav-link"
                }
                href={item.href}
                key={item.href}
              >
                <span>{item.label}</span>
                {item.href === activePath ? <ChevronRight size={16} /> : null}
              </Link>
            ))}
          </nav>
        </div>

        <div className="console-sidebar-footer-row">
          {userEmail && (
            <div className="console-user-email" title={userEmail}>
              {userEmail}
            </div>
          )}
          <SignOutButton />
        </div>
      </aside>

      {mobileNavOpen && (
        <div
          className="console-sidebar-overlay"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <section className="console-main">
        <section className="console-top">
          <section className="console-page-header">
            <div className="console-page-heading">
              {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
              <h1>{title}</h1>
              {description ? <p>{description}</p> : null}
            </div>

            {actions.length > 0 ? (
              <div className="console-page-actions">
                {actions.map((action) => (
                  <Link
                    className={
                      action.variant === "secondary"
                        ? "button-secondary"
                        : "button-primary"
                    }
                    href={action.href}
                    key={`${action.href}-${action.label}`}
                  >
                    {action.label}
                  </Link>
                ))}
              </div>
            ) : null}
          </section>
        </section>

        <section
          className={aside ? "console-content" : "console-content console-content-single"}
        >
          <div className="console-content-main">{children}</div>
          {aside ? <aside className="console-content-side">{aside}</aside> : null}
        </section>
      </section>
    </main>
  );
}
