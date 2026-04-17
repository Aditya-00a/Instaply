"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  ExternalLink,
  Loader2,
  Lock,
  Pause,
  Shield,
  Sparkles,
  Wallet,
  X,
} from "lucide-react";

import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "https://api.asion.ai";

type ProfileSnapshot = {
  full_name: string | null;
  has_resume: boolean;
  has_skills: boolean;
  target_titles: string[];
  target_locations: string[];
  auto_apply_keywords: string[];
  auto_apply_enabled: boolean;
  auto_apply_paused_until: string | null;
  auto_apply_last_run_at: string | null;
  auto_apply_daily_cap: number;
};

type PendingJob = {
  id: string;
  match_score: number;
  found_at: string;
  jobs: {
    id: string;
    title: string;
    company_name: string;
    location: string | null;
    apply_url: string;
    source: string;
  };
};

type RecentApp = {
  id: string;
  status: string;
  queued_at: string;
  jobs: { title: string; company_name: string; apply_url: string } | null;
};

const DEFAULT_SNAPSHOT: ProfileSnapshot = {
  full_name: null,
  has_resume: false,
  has_skills: false,
  target_titles: [],
  target_locations: [],
  auto_apply_keywords: [],
  auto_apply_enabled: false,
  auto_apply_paused_until: null,
  auto_apply_last_run_at: null,
  auto_apply_daily_cap: 5,
};

export default function DashboardPage() {
  const ready = isSupabaseConfigured();
  const [snap, setSnap] = useState<ProfileSnapshot>(DEFAULT_SNAPSHOT);
  const [credits, setCredits] = useState(0);
  const [pending, setPending] = useState<PendingJob[]>([]);
  const [recent, setRecent] = useState<RecentApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [recentlyApproved, setRecentlyApproved] = useState<{ title: string; company: string; at: number }[]>([]);

  const loadAll = useCallback(async () => {
    if (!ready) {
      setLoading(false);
      return;
    }
    const supabase = getBrowserSupabase();
    if (!supabase) {
      setLoading(false);
      return;
    }
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) {
      setLoading(false);
      return;
    }
    const { data: { session } } = await supabase.auth.getSession();
    if (session) setAccessToken(session.access_token);

    const [{ data: prof }, { data: prefs }, { data: resumes }, balResp, { data: pendingData }, { data: recentData }] = await Promise.all([
      supabase.from("profiles").select("full_name, extracted_skills").eq("id", user.id).maybeSingle(),
      supabase.from("preferences").select("target_titles, target_locations, auto_apply_keywords, auto_apply_enabled, auto_apply_paused_until, auto_apply_last_run_at, auto_apply_daily_cap").eq("user_id", user.id).maybeSingle(),
      supabase.from("resumes").select("id").eq("user_id", user.id).limit(1),
      supabase.rpc("get_credit_balance", { p_user_id: user.id }),
      supabase.from("pending_approval").select("id, match_score, found_at, jobs(id, title, company_name, location, apply_url, source)").eq("user_id", user.id).eq("status", "pending").order("match_score", { ascending: false }).limit(10),
      supabase.from("applications").select("id, status, queued_at, jobs(title, company_name, apply_url)").eq("user_id", user.id).order("queued_at", { ascending: false }).limit(6),
    ]);

    const skills = (prof?.extracted_skills as Record<string, unknown>) || {};
    setSnap({
      full_name: prof?.full_name || null,
      has_resume: (resumes && resumes.length > 0) || false,
      has_skills: Object.keys(skills).length > 0 && Array.isArray((skills as { skills?: unknown[] }).skills) && ((skills as { skills?: unknown[] }).skills?.length ?? 0) > 0,
      target_titles: prefs?.target_titles || [],
      target_locations: prefs?.target_locations || [],
      auto_apply_keywords: prefs?.auto_apply_keywords || [],
      auto_apply_enabled: prefs?.auto_apply_enabled || false,
      auto_apply_paused_until: prefs?.auto_apply_paused_until || null,
      auto_apply_last_run_at: prefs?.auto_apply_last_run_at || null,
      auto_apply_daily_cap: prefs?.auto_apply_daily_cap || 5,
    });
    setCredits(typeof balResp.data === "number" ? balResp.data : 0);
    setPending((pendingData ?? []) as unknown as PendingJob[]);
    setRecent((recentData ?? []) as unknown as RecentApp[]);
    setLoading(false);
  }, [ready]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Auto-refresh recent activity every 10 seconds so users see status updates
  // (queued -> submitting -> submitted -> confirmed) without manual refresh
  useEffect(() => {
    if (!ready) return;
    const interval = setInterval(() => {
      loadAll();
    }, 10000);
    return () => clearInterval(interval);
  }, [ready, loadAll]);

  // Onboarding completeness
  const profileComplete = snap.has_resume && snap.target_titles.length > 0;

  // Keyword editor state
  const [kwDraft, setKwDraft] = useState("");

  const updateKeywords = async (next: string[]) => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    await supabase.from("preferences").upsert({
      user_id: user.id,
      auto_apply_keywords: next,
      updated_at: new Date().toISOString(),
    });
    setSnap((s) => ({ ...s, auto_apply_keywords: next }));
  };
  const addKeyword = (kw: string) => {
    const v = kw.trim();
    if (!v || snap.auto_apply_keywords.includes(v)) return;
    updateKeywords([...snap.auto_apply_keywords, v]);
    setKwDraft("");
  };
  const removeKeyword = (kw: string) => updateKeywords(snap.auto_apply_keywords.filter((k) => k !== kw));

  // Toggle auto-apply
  const toggleAgent = async (on: boolean) => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    await supabase.from("preferences").upsert({
      user_id: user.id,
      auto_apply_enabled: on,
      auto_apply_paused_until: on ? null : snap.auto_apply_paused_until,
      updated_at: new Date().toISOString(),
    });
    setSnap((s) => ({ ...s, auto_apply_enabled: on, auto_apply_paused_until: on ? null : s.auto_apply_paused_until }));
    if (on && pending.length === 0) {
      // First time enabling — kick off discovery now
      runDiscovery();
    }
  };

  // Trigger discovery now
  const runDiscovery = async () => {
    if (!accessToken) return;
    setDiscovering(true);
    try {
      const res = await fetch(`${API_BASE}/auto-apply/run-now`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${accessToken}` },
      });
      if (!res.ok) throw new Error(await res.text());
      // Reload to show new pending jobs
      await loadAll();
    } catch (e) {
      console.error("Discovery failed:", e);
    } finally {
      setDiscovering(false);
    }
  };

  const decideOne = async (pendingId: string, decision: "approved" | "skipped") => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    await supabase.from("pending_approval").update({ status: decision, decided_at: new Date().toISOString() }).eq("id", pendingId);
    const item = pending.find((p) => p.id === pendingId);
    if (decision === "approved") {
      if (item) {
        const { data: { user } } = await supabase.auth.getUser();
        if (user) {
          await supabase.from("applications").insert({ user_id: user.id, job_id: item.jobs.id, status: "queued" });
        }
        setRecentlyApproved((prev) => [
          { title: item.jobs.title, company: item.jobs.company_name, at: Date.now() },
          ...prev,
        ].slice(0, 10));
      }
    }
    setPending((prev) => prev.filter((p) => p.id !== pendingId));
  };

  const decideAll = async (decision: "approved" | "skipped") => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    if (decision === "approved" && !confirm(`Queue ${pending.length} applications?\nUp to $${pending.length} if all confirm.`)) return;
    const ids = pending.map((p) => p.id);
    await supabase.from("pending_approval").update({ status: decision, decided_at: new Date().toISOString() }).in("id", ids);
    if (decision === "approved") {
      const { data: { user } } = await supabase.auth.getUser();
      if (user) {
        const rows = pending.map((p) => ({ user_id: user.id, job_id: p.jobs.id, status: "queued" as const }));
        await supabase.from("applications").insert(rows);
      }
      setRecentlyApproved((prev) => [
        ...pending.map((p) => ({ title: p.jobs.title, company: p.jobs.company_name, at: Date.now() })),
        ...prev,
      ].slice(0, 10));
    }
    setPending([]);
    loadAll();
  };

  const fmtRelative = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  };

  const matchClass = (s: number) => (s >= 70 ? "auto-match-high" : s >= 40 ? "auto-match-mid" : "auto-match-low");

  const isPaused = snap.auto_apply_paused_until && new Date(snap.auto_apply_paused_until) > new Date();
  const agentOn = snap.auto_apply_enabled && !isPaused;
  const firstName = snap.full_name?.split(" ")[0] || "there";

  if (loading) {
    return (
      <ConsoleShell activePath="/dashboard" eyebrow="" title="Overview" description="">
        <section className="console-section">
          <div className="dashboard-loading">
            <Loader2 size={16} className="spin" /> Loading…
          </div>
        </section>
      </ConsoleShell>
    );
  }

  // ─── ONBOARDING NEEDED ───
  if (!profileComplete) {
    return (
      <ConsoleShell
        activePath="/dashboard"
        eyebrow="Welcome"
        title={`Hey ${firstName}`}
        description="Let's get your AI agent ready. Two quick steps and it starts working."
      >
        <section className="console-section">
          <article className="glass auto-master-card">
            <div className="auto-master-copy">
              <h2>Set up your agent</h2>
              <p>Upload your resume and tell us what kind of role you want. We&apos;ll find matching jobs and apply on your behalf.</p>
            </div>
            <Link href="/onboarding" className="btn-primary">
              Get started <ArrowRight size={14} />
            </Link>
          </article>
        </section>

        <section className="console-section">
          <div className="auto-grid-2">
            <article className={`glass auto-card ${snap.has_resume ? "" : "auto-step-todo"}`}>
              <header className="auto-card-head">
                <div>
                  <p className="eyebrow">Step 1</p>
                  <h3>Upload your resume</h3>
                </div>
                {snap.has_resume ? <Check size={18} color="#10b981" /> : null}
              </header>
              <p style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>
                We&apos;ll scan it with AI to extract your skills, experience, and education.
              </p>
            </article>

            <article className={`glass auto-card ${snap.target_titles.length > 0 ? "" : "auto-step-todo"}`}>
              <header className="auto-card-head">
                <div>
                  <p className="eyebrow">Step 2</p>
                  <h3>Tell us what you want</h3>
                </div>
                {snap.target_titles.length > 0 ? <Check size={18} color="#10b981" /> : null}
              </header>
              <p style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>
                Pick the job titles and locations you&apos;re targeting. The agent uses these to find matches.
              </p>
            </article>
          </div>
        </section>

        <section className="console-section">
          <div className="auto-trust">
            <div className="auto-trust-item">
              <Lock size={16} />
              <div>
                <strong>You approve every application.</strong>
                <p>Nothing goes out without your click.</p>
              </div>
            </div>
            <div className="auto-trust-item">
              <Wallet size={16} />
              <div>
                <strong>$1 per confirmed application.</strong>
                <p>Charged only after the employer email lands.</p>
              </div>
            </div>
            <div className="auto-trust-item">
              <Shield size={16} />
              <div>
                <strong>3 free credits to start.</strong>
                <p>Try it before you pay anything.</p>
              </div>
            </div>
          </div>
        </section>
      </ConsoleShell>
    );
  }

  // ─── PROFILE COMPLETE — AGENT VIEW ───
  return (
    <ConsoleShell
      activePath="/dashboard"
      eyebrow="AI Agent"
      title={`Hey ${firstName}`}
      description={agentOn ? "Your agent is active. Approve matches below to apply." : "Your agent is paused. Turn it on to start finding jobs."}
      actions={[{ href: "/applications", label: "View activity", variant: "secondary" }]}
    >
      {/* MASTER SWITCH */}
      <section className="console-section">
        <article className="glass auto-master-card">
          <div className="auto-master-copy">
            <h2>{agentOn ? "Agent is active" : "Start your agent"}</h2>
            <p>
              {agentOn
                ? `Searching daily for: ${snap.target_titles.slice(0, 3).join(", ")}${snap.target_titles.length > 3 ? "..." : ""}`
                : "Turn on the agent and we'll find jobs matching your profile. You approve each one before it gets sent."}
            </p>
            <div className="auto-master-status">
              <span className={`auto-pill ${agentOn ? "auto-pill-active" : "auto-pill-paused"}`}>
                {agentOn ? "Active" : isPaused ? "Paused" : "Off"}
              </span>
              {snap.auto_apply_last_run_at && (
                <span className="auto-meta">Last run · {fmtRelative(snap.auto_apply_last_run_at)}</span>
              )}
              <span className="auto-meta">{credits} credits</span>
            </div>
          </div>
          <button
            type="button"
            className={`auto-toggle ${agentOn ? "auto-toggle-on" : ""}`}
            onClick={() => toggleAgent(!agentOn)}
            aria-label="Toggle agent"
          >
            <span className="auto-toggle-knob" />
          </button>
        </article>
      </section>

      {/* AGENT TARGETS — let users tune what the agent searches for */}
      <section className="console-section">
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">Agent search terms</p>
              <h3>What the agent looks for</h3>
              <p className="auto-card-sub">
                Keywords like &quot;remote&quot;, &quot;startup&quot;, &quot;hospital&quot;, &quot;senior&quot;
                expand the search. Combined with your target titles, more keywords means more matches.
              </p>
            </div>
          </header>

          <div className="auto-field">
            <label>Target titles</label>
            <div className="auto-chip-list">
              {snap.target_titles.length === 0 ? (
                <span style={{ fontSize: 12.5, color: "var(--muted)" }}>None set — </span>
              ) : null}
              {snap.target_titles.map((t) => (
                <span className="auto-chip auto-chip-active" key={t}>{t}</span>
              ))}
              <Link href="/profile" style={{ fontSize: 12.5, color: "var(--accent)", marginLeft: 4 }}>Edit</Link>
            </div>
          </div>

          <div className="auto-field">
            <label>Search keywords</label>
            <div className="auto-chip-list">
              {snap.auto_apply_keywords.map((k) => (
                <span className="auto-chip auto-chip-active" key={k}>
                  {k}
                  <button type="button" onClick={() => removeKeyword(k)} aria-label={`Remove ${k}`}>
                    <X size={11} />
                  </button>
                </span>
              ))}
              <div className="auto-chip-input">
                <input
                  value={kwDraft}
                  onChange={(e) => setKwDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addKeyword(kwDraft))}
                  placeholder="+ Add keyword"
                />
              </div>
            </div>
            <span className="auto-helper">Press Enter to add. Try: &quot;remote&quot;, &quot;hospital&quot;, &quot;startup&quot;, &quot;entry level&quot;, &quot;junior&quot;.</span>
          </div>
        </article>
      </section>

      {/* DISCOVERING STATE */}
      {discovering && (
        <section className="console-section">
          <article className="glass auto-card" style={{ display: "flex", alignItems: "center", gap: 12, padding: 20 }}>
            <Loader2 size={18} className="spin" style={{ color: "var(--accent)" }} />
            <div>
              <strong style={{ display: "block", fontSize: 14 }}>Searching for matching jobs...</strong>
              <span style={{ fontSize: 13, color: "var(--muted)" }}>This usually takes 10-15 seconds.</span>
            </div>
          </article>
        </section>
      )}

      {/* JUST APPROVED — confirmation banner shows above pending list */}
      {recentlyApproved.length > 0 && (
        <section className="console-section">
          <article className="glass auto-card auto-just-approved">
            <header className="auto-card-head">
              <div>
                <p className="eyebrow auto-just-approved-eyebrow">
                  <Check size={12} style={{ verticalAlign: "middle", marginRight: 4 }} />
                  Queued · {recentlyApproved.length}
                </p>
                <h3>Approved & sent to the agent</h3>
                <p className="auto-card-sub">
                  Applications are now in the submission queue. They&apos;ll show up under Recent activity once submitted.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setRecentlyApproved([])}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", fontSize: 12 }}
              >
                Dismiss
              </button>
            </header>
            <div className="auto-just-approved-list">
              {recentlyApproved.map((r, i) => (
                <div className="auto-just-approved-row" key={i}>
                  <Check size={14} style={{ color: "#10b981", flexShrink: 0 }} />
                  <span><strong>{r.title}</strong> at {r.company}</span>
                </div>
              ))}
            </div>
          </article>
        </section>
      )}

      {/* PENDING APPROVAL */}
      {pending.length > 0 && (
        <section className="console-section">
          <article className="glass auto-pending-card">
            <header className="auto-card-head">
              <div>
                <p className="eyebrow">Awaiting your approval</p>
                <h3>
                  {pending.length} job{pending.length === 1 ? "" : "s"} matched your profile
                </h3>
                <p className="auto-card-sub">
                  Approve the ones you want to apply to. The agent only submits with your OK.
                </p>
              </div>
            </header>

            <div className="auto-pending-list">
              {pending.map((p) => (
                <div className="auto-pending-row" key={p.id}>
                  <div className="auto-pending-main">
                    <strong>{p.jobs.title}</strong>
                    <span>
                      {p.jobs.company_name}
                      {p.jobs.location ? ` · ${p.jobs.location}` : ""}
                    </span>
                  </div>
                  <span className={`auto-match-badge ${matchClass(p.match_score)}`}>
                    {p.match_score}% match
                  </span>
                  <div className="auto-pending-actions">
                    <button type="button" className="btn-primary auto-btn-sm" onClick={() => decideOne(p.id, "approved")}>
                      Approve
                    </button>
                    <button type="button" className="btn-secondary auto-btn-sm" onClick={() => decideOne(p.id, "skipped")}>
                      Skip
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <footer className="auto-pending-footer">
              <button type="button" className="auto-btn-danger" onClick={() => decideAll("skipped")}>
                Skip all {pending.length}
              </button>
              <button type="button" className="btn-primary" onClick={() => decideAll("approved")}>
                Approve all {pending.length}
              </button>
            </footer>
          </article>
        </section>
      )}

      {/* EMPTY PENDING — show "find more" CTA */}
      {pending.length === 0 && agentOn && !discovering && (
        <section className="console-section">
          <article className="glass auto-card" style={{ textAlign: "center", padding: 36 }}>
            <Sparkles size={28} style={{ color: "var(--accent)", margin: "0 auto 12px" }} />
            <h3 style={{ fontSize: 16, margin: "0 0 6px" }}>No new matches right now</h3>
            <p style={{ fontSize: 13.5, color: "var(--muted)", margin: "0 auto 16px", maxWidth: 480 }}>
              The agent runs daily. Check back tomorrow or trigger a fresh search now.
            </p>
            <button type="button" className="btn-primary" onClick={runDiscovery} disabled={discovering}>
              {discovering ? "Searching..." : "Find jobs now"}
            </button>
          </article>
        </section>
      )}

      {/* RECENT ACTIVITY */}
      {recent.length > 0 && (
        <section className="console-section">
          <article className="glass auto-card">
            <header className="auto-card-head">
              <div>
                <p className="eyebrow">Activity</p>
                <h3>Recent applications</h3>
              </div>
            </header>
            <div className="auto-activity">
              {recent.map((a) => (
                <div className="auto-activity-row" key={a.id}>
                  <span className="auto-activity-time">{fmtRelative(a.queued_at)}</span>
                  <span className={`auto-status-pill auto-status-${a.status}`}>
                    {a.status === "in_progress" ? "In progress" : a.status.charAt(0).toUpperCase() + a.status.slice(1)}
                  </span>
                  <span className="auto-activity-text">
                    Applied to <strong>{a.jobs?.title || "job"}</strong> at <strong>{a.jobs?.company_name || "company"}</strong>
                  </span>
                  {a.jobs?.apply_url && (
                    <a href={a.jobs.apply_url} target="_blank" rel="noopener noreferrer" className="auto-activity-link">
                      <ExternalLink size={12} />
                    </a>
                  )}
                </div>
              ))}
            </div>
            <Link href="/applications" className="auto-view-all">View all applications →</Link>
          </article>
        </section>
      )}

      {/* TRUST FOOTER */}
      <section className="console-section">
        <div className="auto-trust">
          <div className="auto-trust-item">
            <Lock size={16} />
            <div>
              <strong>You approve every application.</strong>
              <p>Nothing goes out without your click.</p>
            </div>
          </div>
          <div className="auto-trust-item">
            <Wallet size={16} />
            <div>
              <strong>$1 per confirmed application.</strong>
              <p>Charged only after the employer email lands.</p>
            </div>
          </div>
          <div className="auto-trust-item">
            <Pause size={16} />
            <div>
              <strong>Pause anytime.</strong>
              <p>Cancel queued applications with one click.</p>
            </div>
          </div>
        </div>
      </section>
    </ConsoleShell>
  );
}
