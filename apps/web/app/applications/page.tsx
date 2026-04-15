"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ExternalLink, Search, Sparkles } from "lucide-react";

import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type AppRow = {
  id: string;
  status: string;
  fit_score: number | null;
  created_at: string;
  confirmed_at: string | null;
  error_message: string | null;
  jobs: {
    title: string | null;
    company_name: string | null;
    source: string | null;
    apply_url: string | null;
    location: string | null;
  } | null;
};

type State =
  | { kind: "demo" }
  | { kind: "loading" }
  | { kind: "live"; rows: AppRow[] }
  | { kind: "error"; message: string };

const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  in_progress: "In progress",
  submitted: "Submitted",
  confirmed: "Confirmed",
  failed: "Failed",
  needs_review: "Needs review",
  skipped: "Skipped",
};

const STATUS_CLASS: Record<string, string> = {
  confirmed: "app-pill-success",
  submitted: "app-pill-info",
  queued: "app-pill-muted",
  in_progress: "app-pill-info",
  needs_review: "app-pill-warn",
  failed: "app-pill-danger",
  skipped: "app-pill-muted",
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function humanSource(s: string | null): string {
  if (!s) return "—";
  const map: Record<string, string> = {
    greenhouse: "Greenhouse",
    lever: "Lever",
    smartrecruiters: "SmartRecruiters",
    workday: "Workday",
    ashby: "Ashby",
    icims: "iCIMS",
    manual: "Manual",
  };
  return map[s] || s;
}

const demoRows = [
  { role: "Risk Analyst", company: "Interactive Brokers", source: "Greenhouse", status: "Ready for apply", fit: "91%" },
  { role: "Product Analyst", company: "T. Rowe Price", source: "Workday", status: "Needs review", fit: "88%" },
  { role: "AML Operations Analyst", company: "Ramp", source: "Lever", status: "Queued", fit: "84%" },
  { role: "Strategy Analyst", company: "Apollo", source: "Greenhouse", status: "Fresh match", fit: "79%" },
];

export default function ApplicationsPage() {
  const [state, setState] = useState<State>(
    isSupabaseConfigured() ? { kind: "loading" } : { kind: "demo" }
  );
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    let cancelled = false;

    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) {
        if (!cancelled) setState({ kind: "demo" });
        return;
      }
      try {
        const {
          data: { user },
        } = await supabase.auth.getUser();
        if (!user) {
          if (!cancelled) setState({ kind: "demo" });
          return;
        }

        const { data, error } = await supabase
          .from("applications")
          .select(
            "id, status, fit_score, created_at, confirmed_at, error_message, jobs(title, company_name, source, apply_url, location)"
          )
          .order("created_at", { ascending: false });

        if (error) throw error;
        if (!cancelled) setState({ kind: "live", rows: (data ?? []) as unknown as AppRow[] });
      } catch (e) {
        if (!cancelled)
          setState({
            kind: "error",
            message: e instanceof Error ? e.message : "Unknown error",
          });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const rows = state.kind === "live" ? state.rows : [];
  const filtered = filter === "all" ? rows : rows.filter((r) => r.status === filter);

  const counts = {
    all: rows.length,
    queued: rows.filter((r) => r.status === "queued").length,
    submitted: rows.filter((r) => r.status === "submitted").length,
    confirmed: rows.filter((r) => r.status === "confirmed").length,
    needs_review: rows.filter((r) => r.status === "needs_review").length,
  };

  return (
    <ConsoleShell
      activePath="/applications"
      eyebrow=""
      title="Applications"
      description="Every application Instaply has queued, submitted, or confirmed on your behalf."
      actions={[
        { href: "/onboarding", label: "Add preferences" },
        { href: "/dashboard", label: "Back to overview", variant: "secondary" },
      ]}
    >
      {state.kind === "error" && (
        <section className="console-section">
          <div className="dashboard-error">Couldn&apos;t load applications — {state.message}</div>
        </section>
      )}

      {state.kind === "loading" && (
        <section className="console-section">
          <div className="dashboard-loading">Loading your applications…</div>
        </section>
      )}

      {state.kind === "live" && rows.length === 0 && (
        <section className="console-section">
          <article className="glass dashboard-empty-hero">
            <div className="dashboard-empty-icon" aria-hidden>
              <Sparkles size={22} />
            </div>
            <div className="dashboard-empty-copy">
              <span className="eyebrow">Nothing yet</span>
              <h2>No applications submitted so far.</h2>
              <p>
                Finish your profile and targets, then Instaply starts
                matching roles and queueing them here.
              </p>
            </div>
            <div className="dashboard-empty-actions">
              <Link href="/onboarding" className="btn-primary">
                Complete profile
              </Link>
              <Link href="/how-it-works" className="btn-secondary">
                How applications flow
              </Link>
            </div>
          </article>
        </section>
      )}

      {state.kind === "live" && rows.length > 0 && (
        <>
          <section className="console-section">
            <div className="app-summary-grid">
              <Stat label="Total" value={counts.all} />
              <Stat label="Queued" value={counts.queued} />
              <Stat label="Submitted" value={counts.submitted} />
              <Stat label="Confirmed" value={counts.confirmed} />
              <Stat label="Needs review" value={counts.needs_review} />
            </div>
          </section>

          <section className="console-section">
            <div className="app-filter-row">
              {(
                [
                  ["all", "All"],
                  ["queued", "Queued"],
                  ["submitted", "Submitted"],
                  ["confirmed", "Confirmed"],
                  ["needs_review", "Needs review"],
                  ["failed", "Failed"],
                ] as const
              ).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  className={`app-filter${filter === k ? " app-filter-active" : ""}`}
                  onClick={() => setFilter(k)}
                >
                  {label}
                </button>
              ))}
            </div>

            <article className="glass app-table-card">
              <div className="app-table-head">
                <span>Role</span>
                <span>Source</span>
                <span>Status</span>
                <span>Fit</span>
                <span>Applied</span>
                <span></span>
              </div>
              {filtered.length === 0 ? (
                <div className="workspace-empty">
                  No applications match this filter.
                </div>
              ) : (
                filtered.map((r) => (
                  <div className="app-table-row" key={r.id}>
                    <div className="app-table-cell-role">
                      <strong>{r.jobs?.title || "Untitled role"}</strong>
                      <span>
                        {r.jobs?.company_name || "—"}
                        {r.jobs?.location ? ` · ${r.jobs.location}` : ""}
                      </span>
                    </div>
                    <span className="app-table-cell-source">
                      {humanSource(r.jobs?.source ?? null)}
                    </span>
                    <span
                      className={`app-pill ${STATUS_CLASS[r.status] || "app-pill-muted"}`}
                    >
                      {STATUS_LABEL[r.status] || r.status}
                    </span>
                    <span className="app-table-cell-fit">
                      {r.fit_score != null ? `${Math.round(r.fit_score * 100)}%` : "—"}
                    </span>
                    <span className="app-table-cell-date">{fmtDate(r.confirmed_at || r.created_at)}</span>
                    {r.jobs?.apply_url ? (
                      <a
                        href={r.jobs.apply_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="app-open-link"
                        aria-label="Open job posting"
                      >
                        <ExternalLink size={14} />
                      </a>
                    ) : (
                      <span />
                    )}
                  </div>
                ))
              )}
            </article>
          </section>
        </>
      )}

      {state.kind === "demo" && (
        <>
          <section className="console-section">
            <div className="app-summary-grid">
              <Stat label="Tracked" value={83} />
              <Stat label="Packets ready" value={12} />
              <Stat label="Need input" value={4} />
              <Stat label="Ready to send" value={7} />
            </div>
          </section>

          <section className="console-section">
            <article className="glass app-table-card">
              <div className="app-table-head">
                <span>Role</span>
                <span>Source</span>
                <span>Status</span>
                <span>Fit</span>
                <span></span>
              </div>
              {demoRows.map((r, i) => (
                <div className="app-table-row" key={i}>
                  <div className="app-table-cell-role">
                    <strong>{r.role}</strong>
                    <span>{r.company}</span>
                  </div>
                  <span className="app-table-cell-source">{r.source}</span>
                  <span className="app-pill app-pill-info">{r.status}</span>
                  <span className="app-table-cell-fit">{r.fit}</span>
                  <span><Search size={14} /></span>
                </div>
              ))}
            </article>
          </section>
        </>
      )}
    </ConsoleShell>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <article className="app-summary-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
