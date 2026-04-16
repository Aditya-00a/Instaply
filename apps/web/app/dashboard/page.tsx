"use client";

import Link from "next/link";
import { ArrowUpRight, Sparkles, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";

import { ConsoleShell } from "../components/console-shell";
import { blockedQuestions, generatedDocuments, overviewMetrics, queueRows } from "../console-data";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type AppRow = {
  id: string;
  status: string;
  queued_at: string;
  jobs: {
    title: string | null;
    company_name: string | null;
  } | null;
};

type LiveData = {
  mode: "live";
  balance: number;
  searchesToday: number;
  counts: {
    queued: number;
    submitted: number;
    confirmed: number;
    needs_review: number;
  };
  recent: AppRow[];
  email: string | null;
};

const DAILY_SEARCH_QUOTA = 10;

type State =
  | { kind: "demo" }
  | { kind: "loading" }
  | { kind: "live"; data: LiveData }
  | { kind: "error"; message: string };

const recentUpdatesDemo = [
  { label: "Packet ready", title: "Risk Analyst", meta: "Interactive Brokers", state: "Ready" },
  { label: "Answer needed", title: "AML Operations Analyst", meta: "Ramp", state: "Waiting" },
  { label: "Fresh match", title: "Strategy Analyst", meta: "Apollo", state: "New" },
];

export default function DashboardPage() {
  const [state, setState] = useState<State>(
    isSupabaseConfigured() ? { kind: "loading" } : { kind: "demo" }
  );

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

        // Credit balance via RPC (function added in 0001_init.sql)
        const [{ data: balanceData }, { data: searchData }] = await Promise.all([
          supabase.rpc("get_credit_balance", { p_user_id: user.id }),
          supabase.rpc("get_search_usage_today", { p_user_id: user.id }),
        ]);
        const balance = typeof balanceData === "number" ? balanceData : 0;
        const searchesToday = typeof searchData === "number" ? searchData : 0;

        // Applications summary
        const { data: apps, error: appsErr } = await supabase
          .from("applications")
          .select("id, status, queued_at, jobs(title, company_name)")
          .order("queued_at", { ascending: false });

        if (appsErr) {
          if (!cancelled)
            setState({ kind: "error", message: appsErr.message });
          return;
        }

        const all = (apps ?? []) as unknown as AppRow[];
        const counts = {
          queued: all.filter((a) => a.status === "queued").length,
          submitted: all.filter((a) => a.status === "submitted").length,
          confirmed: all.filter((a) => a.status === "confirmed").length,
          needs_review: all.filter((a) => a.status === "needs_review").length,
        };

        if (!cancelled) {
          setState({
            kind: "live",
            data: {
              mode: "live",
              balance,
              searchesToday,
              counts,
              recent: all.slice(0, 3),
              email: user.email ?? null,
            },
          });
        }
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

  return (
    <ConsoleShell
      activePath="/dashboard"
      eyebrow=""
      title="Overview"
      description=""
      actions={[
        { href: "/applications", label: "View applications" },
        { href: "/review", label: "Open answers", variant: "secondary" },
      ]}
    >
      {state.kind === "loading" && (
        <section className="console-section">
          <div className="dashboard-loading">Loading your workspace…</div>
        </section>
      )}

      {state.kind === "error" && (
        <section className="console-section">
          <div className="dashboard-error">
            Couldn&apos;t load your workspace — {state.message}
          </div>
        </section>
      )}

      {state.kind === "live" && state.data.counts.queued +
        state.data.counts.submitted +
        state.data.counts.confirmed +
        state.data.counts.needs_review === 0 && (
        <EmptyState balance={state.data.balance} />
      )}

      {state.kind === "live" && state.data.counts.queued > 0 && (
        <section className="console-section">
          <div className="auto-apply-banner">
            <span className="auto-apply-banner-dot" />
            <div>
              <strong>{state.data.counts.queued} application{state.data.counts.queued === 1 ? "" : "s"} in queue</strong>
              <p>
                You queued these from the Search page. We&apos;ll fill out
                and submit each form within a few minutes. You can cancel
                any queued application from the Applications page.
              </p>
            </div>
          </div>
        </section>
      )}

      {(state.kind === "demo" ||
        (state.kind === "live" &&
          state.data.counts.queued +
            state.data.counts.submitted +
            state.data.counts.confirmed +
            state.data.counts.needs_review > 0)) && (
        <section className="console-section">
          <div className="section-intro">
            <div>
              <p className="eyebrow">Workspace</p>
              <h2>Everything important in one place</h2>
            </div>
          </div>

          <div className="pricing-plan-grid workspace-metric-grid">
            {state.kind === "live"
              ? [
                  { label: "Credits", value: String(state.data.balance) },
                  {
                    label: "Searches today",
                    value: `${state.data.searchesToday}/${DAILY_SEARCH_QUOTA}`,
                  },
                  { label: "Submitted", value: String(state.data.counts.submitted) },
                  { label: "Confirmed", value: String(state.data.counts.confirmed) },
                ].map((m) => (
                  <article className="workspace-metric-card" key={m.label}>
                    <span className="workspace-metric-label">{m.label}</span>
                    <strong className="workspace-metric-value">{m.value}</strong>
                  </article>
                ))
              : overviewMetrics.map((metric) => (
                  <article className="workspace-metric-card" key={metric.label}>
                    <span className="workspace-metric-label">{metric.label}</span>
                    <strong className="workspace-metric-value">{metric.value}</strong>
                  </article>
                ))}
          </div>
        </section>
      )}

      {state.kind === "demo" && blockedQuestions.length > 0 ? (
        <section className="console-section">
          <article className="glass blocker-banner blocker-banner-product">
            <div className="blocker-banner-copy">
              <span className="blocker-banner-kicker">Needs review</span>
              <strong>{blockedQuestions.length} answers are waiting on you</strong>
              <p>Answer them once and Instaply can reuse them safely across supported applications.</p>
            </div>
            <a className="button-secondary" href="/review">
              Open answers
            </a>
          </article>
        </section>
      ) : null}

      {state.kind === "live" && state.data.counts.needs_review > 0 && (
        <section className="console-section">
          <article className="glass blocker-banner blocker-banner-product">
            <div className="blocker-banner-copy">
              <span className="blocker-banner-kicker">Needs review</span>
              <strong>
                {state.data.counts.needs_review} application
                {state.data.counts.needs_review === 1 ? "" : "s"} need
                {state.data.counts.needs_review === 1 ? "s" : ""} your attention
              </strong>
              <p>
                These applications hit a screening question or issue that
                requires your input before we can submit.
              </p>
            </div>
            <Link className="button-secondary" href="/applications">
              View applications
            </Link>
          </article>
        </section>
      )}

      {(state.kind === "demo" || state.kind === "live") && (
        <section className="console-section workspace-grid-two">
          <article className="glass workspace-card">
            <div className="console-card-header">
              <div>
                <div className="panel-kicker">Activity</div>
                <h3>Latest progress</h3>
              </div>
              <ArrowUpRight size={18} />
            </div>

            <div className="workspace-list">
              {state.kind === "live" && state.data.recent.length > 0 ? (
                state.data.recent.map((app) => (
                  <div className="workspace-list-row" key={app.id}>
                    <div>
                      <span className="workspace-list-kicker">{app.status.replace("_", " ")}</span>
                      <strong>{app.jobs?.title || "Untitled role"}</strong>
                      <p>{app.jobs?.company_name || "—"}</p>
                    </div>
                    <span className="workspace-inline-pill">
                      {new Date(app.queued_at).toLocaleDateString()}
                    </span>
                  </div>
                ))
              ) : state.kind === "live" ? (
                <div className="workspace-empty">
                  Nothing here yet. Complete your profile to get matches.
                </div>
              ) : (
                recentUpdatesDemo.map((item) => (
                  <div className="workspace-list-row" key={`${item.label}-${item.title}`}>
                    <div>
                      <span className="workspace-list-kicker">{item.label}</span>
                      <strong>{item.title}</strong>
                      <p>{item.meta}</p>
                    </div>
                    <span className="workspace-inline-pill">{item.state}</span>
                  </div>
                ))
              )}
            </div>
          </article>

          <article className="glass workspace-card">
            <div className="console-card-header">
              <div>
                <div className="panel-kicker">Documents</div>
                <h3>Recent files</h3>
              </div>
            </div>

            <div className="workspace-list">
              {state.kind === "live" ? (
                <div className="workspace-empty">
                  Upload a resume from the Profile page to see it here.
                </div>
              ) : (
                generatedDocuments.map((document) => (
                  <div className="workspace-list-row" key={`${document.company}-${document.role}`}>
                    <div>
                      <strong>{document.role}</strong>
                      <p>{document.company}</p>
                      <div className="workspace-tag-row">
                        <span className="workspace-tag">Resume: {document.resume}</span>
                        <span className="workspace-tag">Letter: {document.coverLetter}</span>
                      </div>
                    </div>
                    <span className="workspace-inline-note">{document.updated}</span>
                  </div>
                ))
              )}
            </div>
          </article>
        </section>
      )}

      {state.kind === "demo" && (
        <section className="console-section">
          <article className="glass workspace-table-card">
            <div className="console-card-header">
              <div>
                <div className="panel-kicker">Queue</div>
                <h3>Open roles</h3>
              </div>
            </div>

            <div className="workspace-list">
              {queueRows.map((row) => (
                <div className="workspace-list-row" key={row.role}>
                  <strong>{row.role}</strong>
                  <span className="workspace-inline-pill">{row.rating}</span>
                </div>
              ))}
            </div>
          </article>
        </section>
      )}
    </ConsoleShell>
  );
}

function EmptyState({ balance }: { balance: number }) {
  return (
    <section className="console-section">
      <article className="glass dashboard-empty-hero">
        <div className="dashboard-empty-icon" aria-hidden>
          <Sparkles size={22} />
        </div>
        <div className="dashboard-empty-copy">
          <span className="eyebrow">Welcome to Instaply</span>
          <h2>You&apos;re all set — let&apos;s get your first application out.</h2>
          <p>
            You have <strong>{balance} free application credits</strong> ready
            to use. The first step is to upload your resume and tell us the
            kinds of roles you&apos;re looking for.
          </p>
        </div>
        <div className="dashboard-empty-actions">
          <Link href="/onboarding" className="btn-primary">
            <UserPlus size={16} />
            Complete your profile
          </Link>
          <Link href="/how-it-works" className="btn-secondary">
            See how it works
          </Link>
        </div>
      </article>
    </section>
  );
}
