"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Calendar,
  Check,
  ExternalLink,
  Loader2,
  Lock,
  Pause,
  Plus,
  Shield,
  Sparkles,
  Wallet,
  X,
} from "lucide-react";

import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "https://api.asion.ai";

type AutoApplyConfig = {
  auto_apply_enabled: boolean;
  auto_apply_daily_cap: number;
  auto_apply_min_match: number;
  auto_apply_visa_only: boolean;
  auto_apply_quiet_start: string;
  auto_apply_quiet_end: string;
  auto_apply_paused_until: string | null;
  auto_apply_last_run_at: string | null;
  target_titles: string[];
  target_locations: string[];
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

const DEFAULT_CONFIG: AutoApplyConfig = {
  auto_apply_enabled: false,
  auto_apply_daily_cap: 5,
  auto_apply_min_match: 70,
  auto_apply_visa_only: false,
  auto_apply_quiet_start: "23:00",
  auto_apply_quiet_end: "08:00",
  auto_apply_paused_until: null,
  auto_apply_last_run_at: null,
  target_titles: [],
  target_locations: [],
};

const SUGGESTED_LOCATIONS = ["New York", "Remote", "San Francisco", "Boston", "Chicago", "Austin"];

export default function AutoApplyPage() {
  const ready = isSupabaseConfigured();
  const [config, setConfig] = useState<AutoApplyConfig>(DEFAULT_CONFIG);
  const [credits, setCredits] = useState<number>(0);
  const [pending, setPending] = useState<PendingJob[]>([]);
  const [recent, setRecent] = useState<RecentApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved">("idle");
  const [titleDraft, setTitleDraft] = useState("");
  const [locDraft, setLocDraft] = useState("");
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load all data on mount
  useEffect(() => {
    if (!ready) return;
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      const [{ data: prefs }, balResp, { data: pendingData }, { data: recentData }] = await Promise.all([
        supabase.from("preferences").select("*").eq("user_id", user.id).maybeSingle(),
        supabase.rpc("get_credit_balance", { p_user_id: user.id }),
        supabase
          .from("pending_approval")
          .select("id, match_score, found_at, jobs(id, title, company_name, location, apply_url, source)")
          .eq("user_id", user.id)
          .eq("status", "pending")
          .order("match_score", { ascending: false })
          .limit(50),
        supabase
          .from("applications")
          .select("id, status, queued_at, jobs(title, company_name, apply_url)")
          .eq("user_id", user.id)
          .order("queued_at", { ascending: false })
          .limit(8),
      ]);

      if (prefs) setConfig({ ...DEFAULT_CONFIG, ...prefs });
      setCredits(typeof balResp.data === "number" ? balResp.data : 0);
      setPending((pendingData ?? []) as unknown as PendingJob[]);
      setRecent((recentData ?? []) as unknown as RecentApp[]);
      setLoading(false);
    })();
  }, [ready]);

  // Auto-save with 800ms debounce
  const persist = useCallback((next: AutoApplyConfig) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      setSaving("saving");
      const { error } = await supabase.from("preferences").upsert({
        user_id: user.id,
        auto_apply_enabled: next.auto_apply_enabled,
        auto_apply_daily_cap: next.auto_apply_daily_cap,
        auto_apply_min_match: next.auto_apply_min_match,
        auto_apply_visa_only: next.auto_apply_visa_only,
        auto_apply_quiet_start: next.auto_apply_quiet_start,
        auto_apply_quiet_end: next.auto_apply_quiet_end,
        auto_apply_paused_until: next.auto_apply_paused_until,
        target_titles: next.target_titles,
        target_locations: next.target_locations,
        updated_at: new Date().toISOString(),
      });
      if (!error) {
        setSaving("saved");
        setTimeout(() => setSaving("idle"), 1500);
      } else {
        setSaving("idle");
      }
    }, 800);
  }, []);

  const update = useCallback(
    (patch: Partial<AutoApplyConfig>) => {
      setConfig((prev) => {
        const next = { ...prev, ...patch };
        persist(next);
        return next;
      });
    },
    [persist]
  );

  const addTitle = (t: string) => {
    const v = t.trim();
    if (!v || config.target_titles.includes(v)) return;
    update({ target_titles: [...config.target_titles, v] });
    setTitleDraft("");
  };
  const removeTitle = (t: string) => update({ target_titles: config.target_titles.filter((x) => x !== t) });
  const addLoc = (l: string) => {
    const v = l.trim();
    if (!v || config.target_locations.includes(v)) return;
    update({ target_locations: [...config.target_locations, v] });
    setLocDraft("");
  };
  const removeLoc = (l: string) => update({ target_locations: config.target_locations.filter((x) => x !== l) });

  const decideOne = async (pendingId: string, decision: "approved" | "skipped") => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    await supabase
      .from("pending_approval")
      .update({ status: decision, decided_at: new Date().toISOString() })
      .eq("id", pendingId);

    if (decision === "approved") {
      const item = pending.find((p) => p.id === pendingId);
      if (item) {
        const { data: { user } } = await supabase.auth.getUser();
        if (user) {
          await supabase.from("applications").insert({
            user_id: user.id,
            job_id: item.jobs.id,
            status: "queued",
          });
        }
      }
    }
    setPending((prev) => prev.filter((p) => p.id !== pendingId));
  };

  const decideAll = async (decision: "approved" | "skipped") => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    if (decision === "approved" && !confirm(`Queue ${pending.length} applications? About $${pending.length} if all confirm.`)) return;

    const ids = pending.map((p) => p.id);
    await supabase.from("pending_approval").update({ status: decision, decided_at: new Date().toISOString() }).in("id", ids);

    if (decision === "approved") {
      const { data: { user } } = await supabase.auth.getUser();
      if (user) {
        const rows = pending.map((p) => ({ user_id: user.id, job_id: p.jobs.id, status: "queued" as const }));
        await supabase.from("applications").insert(rows);
      }
    }
    setPending([]);
  };

  const pause7Days = () => {
    const until = new Date();
    until.setDate(until.getDate() + 7);
    update({ auto_apply_paused_until: until.toISOString(), auto_apply_enabled: false });
  };

  const isPaused = config.auto_apply_paused_until && new Date(config.auto_apply_paused_until) > new Date();
  const enabled = config.auto_apply_enabled && !isPaused;

  const fmtRelative = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime();
    const hours = Math.floor(diff / 3600000);
    if (hours < 1) return `${Math.floor(diff / 60000)}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  const matchClass = (score: number) =>
    score >= 70 ? "auto-match-high" : score >= 40 ? "auto-match-mid" : "auto-match-low";

  return (
    <ConsoleShell
      activePath="/auto-apply"
      eyebrow="AI Agent"
      title="Auto-Apply"
      description={
        saving === "saving"
          ? "Saving…"
          : saving === "saved"
          ? "All changes saved"
          : "Set your targets. Approve the matches. We submit the rest."
      }
      actions={[{ href: "/applications", label: "View activity", variant: "secondary" }]}
    >
      {/* MASTER SWITCH */}
      <section className="console-section">
        <article className="glass auto-master-card">
          <div className="auto-master-copy">
            <h2>Enable Auto-Apply</h2>
            <p>
              When on, the agent searches Indeed, LinkedIn, and ZipRecruiter
              daily for jobs matching your profile.
            </p>
            <div className="auto-master-status">
              <span className={`auto-pill ${enabled ? "auto-pill-active" : "auto-pill-paused"}`}>
                {enabled ? "Active" : isPaused ? "Paused" : "Off"}
              </span>
              {config.auto_apply_last_run_at && (
                <span className="auto-meta">Last run · {fmtRelative(config.auto_apply_last_run_at)}</span>
              )}
            </div>
          </div>
          <button
            type="button"
            className={`auto-toggle ${enabled ? "auto-toggle-on" : ""}`}
            onClick={() => update({ auto_apply_enabled: !config.auto_apply_enabled, auto_apply_paused_until: null })}
            aria-label="Toggle auto-apply"
          >
            <span className="auto-toggle-knob" />
          </button>
        </article>
      </section>

      {/* TARGETS + LIMITS */}
      <section className="console-section auto-grid-2">
        {/* Targets */}
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">Targets</p>
              <h3>What to apply to</h3>
            </div>
            <Sparkles size={18} />
          </header>

          <div className="auto-field">
            <label>Job titles</label>
            <div className="auto-chip-list">
              {config.target_titles.map((t) => (
                <span className="auto-chip auto-chip-active" key={t}>
                  {t}
                  <button type="button" onClick={() => removeTitle(t)} aria-label={`Remove ${t}`}>
                    <X size={11} />
                  </button>
                </span>
              ))}
              <div className="auto-chip-input">
                <input
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addTitle(titleDraft))}
                  placeholder="+ Add title"
                />
              </div>
            </div>
          </div>

          <div className="auto-field">
            <label>Locations</label>
            <div className="auto-chip-list">
              {config.target_locations.map((l) => (
                <span className="auto-chip auto-chip-active" key={l}>
                  {l}
                  <button type="button" onClick={() => removeLoc(l)} aria-label={`Remove ${l}`}>
                    <X size={11} />
                  </button>
                </span>
              ))}
              <div className="auto-chip-input">
                <input
                  value={locDraft}
                  onChange={(e) => setLocDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addLoc(locDraft))}
                  placeholder="+ Add location"
                />
              </div>
            </div>
            <div className="auto-suggestions">
              {SUGGESTED_LOCATIONS.filter((l) => !config.target_locations.includes(l))
                .slice(0, 4)
                .map((l) => (
                  <button type="button" className="auto-chip" key={l} onClick={() => addLoc(l)}>
                    + {l}
                  </button>
                ))}
            </div>
          </div>

          <div className="auto-field">
            <label>
              Minimum match score <strong>{config.auto_apply_min_match}%</strong>
            </label>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={config.auto_apply_min_match}
              onChange={(e) => update({ auto_apply_min_match: parseInt(e.target.value) })}
              className="auto-slider"
            />
            <span className="auto-helper">Only apply to jobs scoring {config.auto_apply_min_match}% or higher against your resume</span>
          </div>

          <div className="auto-field auto-field-row">
            <div>
              <label>Visa sponsorship</label>
              <span className="auto-helper">Only show companies that sponsor H-1B/visa</span>
            </div>
            <button
              type="button"
              className={`auto-toggle auto-toggle-sm ${config.auto_apply_visa_only ? "auto-toggle-on" : ""}`}
              onClick={() => update({ auto_apply_visa_only: !config.auto_apply_visa_only })}
              aria-label="Toggle visa filter"
            >
              <span className="auto-toggle-knob" />
            </button>
          </div>
        </article>

        {/* Limits */}
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">Limits</p>
              <h3>How much, how often</h3>
            </div>
            <Wallet size={18} />
          </header>

          <div className="auto-field">
            <label>Applications per day</label>
            <div className="auto-stepper">
              <button type="button" onClick={() => update({ auto_apply_daily_cap: Math.max(1, config.auto_apply_daily_cap - 1) })}>
                −
              </button>
              <span>{config.auto_apply_daily_cap}</span>
              <button type="button" onClick={() => update({ auto_apply_daily_cap: Math.min(50, config.auto_apply_daily_cap + 1) })}>
                +
              </button>
            </div>
            <span className="auto-helper">Stops once we hit {config.auto_apply_daily_cap} confirmed applies</span>
          </div>

          <div className="auto-field auto-field-row">
            <div>
              <label>Credits available</label>
              <div className="auto-credits-num">{credits}</div>
              <span className="auto-helper">credits remaining</span>
            </div>
            <Link href="/billing" className="auto-link">Top up</Link>
          </div>

          <div className="auto-field">
            <label>Quiet hours</label>
            <div className="auto-time-row">
              <input
                type="time"
                value={config.auto_apply_quiet_start}
                onChange={(e) => update({ auto_apply_quiet_start: e.target.value })}
              />
              <span>to</span>
              <input
                type="time"
                value={config.auto_apply_quiet_end}
                onChange={(e) => update({ auto_apply_quiet_end: e.target.value })}
              />
            </div>
            <span className="auto-helper">Agent won&apos;t submit during these hours</span>
          </div>

          <button type="button" className="btn-secondary auto-pause-btn" onClick={pause7Days}>
            <Pause size={14} /> Pause for 7 days
          </button>
        </article>
      </section>

      {/* PENDING APPROVAL */}
      {pending.length > 0 && (
        <section className="console-section">
          <article className="glass auto-pending-card">
            <header className="auto-card-head">
              <div>
                <p className="eyebrow">Awaiting your approval</p>
                <h3>
                  {pending.length} job{pending.length === 1 ? "" : "s"} the agent wants to apply to
                </h3>
                <p className="auto-card-sub">
                  These match your targets. Approve the ones you actually want — the agent only applies to approved jobs.
                </p>
              </div>
            </header>

            <div className="auto-pending-list">
              {pending.slice(0, 5).map((p) => (
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
              {pending.length > 5 && (
                <div className="auto-pending-more">+ {pending.length - 5} more</div>
              )}
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
            <Shield size={16} />
            <div>
              <strong>Pause anytime.</strong>
              <p>Cancel queued applications with one click.</p>
            </div>
          </div>
        </div>
      </section>

      {loading && (
        <section className="console-section">
          <div className="dashboard-loading">
            <Loader2 size={16} className="spin" /> Loading your settings…
          </div>
        </section>
      )}
    </ConsoleShell>
  );
}
