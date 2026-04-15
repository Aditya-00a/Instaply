import Link from "next/link";
import { Cable, ChevronRight } from "lucide-react";

import { consoleNavItems } from "../console-data";
import { SignOutButton } from "./sign-out-button";

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
  aside
}: ConsoleShellProps) {
  const workspaceItems = consoleNavItems.filter((item) => item.section === "workspace");
  const accountItems = consoleNavItems.filter((item) => item.section === "account");

  return (
    <main className="console-app">
      <aside className="console-sidebar glass">
        <div className="console-brand">
          <div className="pill">
            <Cable size={14} />
            MCP first
          </div>
          <div>
            <strong>Instaply</strong>
            <p>Private job search and apply workspace</p>
          </div>
        </div>

        <div className="console-sidebar-section">
          <span className="console-sidebar-label">Workspace</span>
          <nav className="console-nav">
            {workspaceItems.map((item) => (
              <Link
                className={item.href === activePath ? "console-nav-link console-nav-link-active" : "console-nav-link"}
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
                className={item.href === activePath ? "console-nav-link console-nav-link-active" : "console-nav-link"}
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
          <SignOutButton />
        </div>

      </aside>

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
                    className={action.variant === "secondary" ? "button-secondary" : "button-primary"}
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

        <section className={aside ? "console-content" : "console-content console-content-single"}>
          <div className="console-content-main">{children}</div>
          {aside ? <aside className="console-content-side">{aside}</aside> : null}
        </section>
      </section>
    </main>
  );
}
