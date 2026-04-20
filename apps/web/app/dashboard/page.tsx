"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Bell,
  BellOff,
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
import { isExtensionInstalled, triggerExtensionFill } from "../lib/extension";

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
  started_at: string | null;
  error_message: string | null;
  submission_log: string | null;
  screenshot_url: string | null;
  jobs: { title: string; company_name: string; apply_url: string } | null;
};

// ─── Audio cues (Web Audio API, no asset files needed) ───────────
// playTone synthesizes a short envelope-shaped tone. Two sounds:
// "job"      = 2-note ascending chime (C5 → E5)
// "question" = 2-note attention bell (G4 → C5, slower)
function playTone(freqs: number[], dur: number, type: OscillatorType = "sine") {
  if (typeof window === "undefined") return;
  try {
    const Ctx = (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext);
    if (!Ctx) return;
    const ctx = new Ctx();
    const gain = ctx.createGain();
    gain.gain.value = 0;
    gain.connect(ctx.destination);
    const t0 = ctx.currentTime;
    freqs.forEach((f, i) => {
      const osc = ctx.createOscillator();
      osc.type = type;
      osc.frequency.value = f;
      osc.connect(gain);
      const start = t0 + i * dur;
      const end = start + dur;
      osc.start(start);
      osc.stop(end);
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.18, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, end);
    });
    setTimeout(() => ctx.close().catch(() => {}), (freqs.length * dur + 0.1) * 1000);
  } catch {
    /* audio blocked or unsupported — silent fail */
  }
}
// Junk-question filter (mirrors the server-side filter in cloud_submitter.py)
// so OLD submission_logs that predate the server filter render cleanly too.
const _JUNK_LABELS = new Set([
  "my information", "my experience", "my education",
  "create account/sign in", "sign in", "create account",
  "voluntary disclosures", "self identify",
  "review", "submit", "next", "previous", "continue", "back",
  "application", "application form", "application questions",
  "personal information", "contact information", "additional information",
  "name", "email", "phone", "address",
]);
const _JUNK_RE = [
  /^\s*(current\s+|completed\s+)?step\s+\d+\s+of\s+\d+\s*$/i,
  /^\s*page\s+\d+\s+of\s+\d+\s*$/i,
];
function isJunkQuestion(q: { question?: string }): boolean {
  const text = (q.question || "").trim();
  if (!text || text.length < 4) return true;
  if (_JUNK_LABELS.has(text.toLowerCase())) return true;
  return _JUNK_RE.some((p) => p.test(text));
}

// Detect questions that are too cryptic for a normal user to answer
// confidently in a text input. These are typically option labels that
// leaked from the worker's parser as the question text — e.g. a
// multi-checkbox group where each box's label ("Palo Alto", "Custom",
// "Not Interested") got captured as the question rather than the
// actual prompt above the group. Asking a user to type something into
// a box labelled just "Palo Alto" is a guess-game; better to surface
// an "Open & finish manually" CTA so the user solves it on the real
// form. The worker's auto-No / pronouns / EEO rules already cover the
// common cases — what reaches this branch is the residual that needs
// a human eyeball.
//
// Heuristic (deliberately conservative — false-positives downgrade
// the UX from "type an answer" to "open the form", which is annoying
// but not unsafe; false-negatives leave the existing input in place):
//   1. The agent's suggested value equals the question text — a
//      strong tell that the LLM treated an option label as both Q
//      and A (Wealthfront's "Palo Alto" / "Palo Alto" pattern).
//   2. Question is short (≤ 24 chars), has no terminal '?' or ':',
//      AND looks like a Title-Case option / proper noun / single
//      enum value (no whitespace, OR all words capitalized, OR
//      contains a slash like "He/him" — though pronoun rule should
//      have eaten those by now).
function isCrypticQuestion(q: { question?: string; suggested?: string | null }): boolean {
  const text = (q.question || "").trim();
  if (!text) return false;
  // Rule 1: question == suggested (LLM echoed an option label).
  const suggested = (q.suggested || "").trim();
  if (suggested && suggested.toLowerCase() === text.toLowerCase()) return true;
  // Rule 1b: worker prettifier output. When the worker's
  // _prettify_raw_name() in cache.py couldn't find a real label and
  // fell back to one of its generic stand-ins, the resulting text is
  // by-definition cryptic — there's nothing the user can confidently
  // type. Route to "Open form" instead. Patterns mirror the worker's
  // output formats (Custom question N / Custom question (Source) /
  // Survey question N). EEO-pretty labels like "Race (EEO)" are
  // intentionally NOT matched — those are meaningful enough to answer.
  if (/^Custom question(\s+\d+|\s+\([^)]+\))?$/i.test(text)) return true;
  if (/^Survey question(\s+\d+|\s+\([^)]+\))?$/i.test(text)) return true;
  // Rule 2: short + no question/colon + option-shaped.
  if (text.length > 24) return false;
  if (/[?:]/.test(text)) return false;
  // Looks like a single proper-noun option ("Custom", "Not Interested",
  // "Palo Alto", "She/her"). Two heuristics combine:
  //   (a) every space-separated token starts with an uppercase letter
  //       (Title Case enum value), AND
  //   (b) the text doesn't start with a verb-ish word that would
  //       indicate a real question phrasing (Are/Have/Do/Were/etc.)
  const tokens = text.split(/\s+/);
  const titleCased = tokens.every((t) => /^[A-Z][\w/'-]*$/.test(t));
  if (!titleCased) return false;
  const verbStart = /^(are|do|did|have|has|had|were|was|will|would|can|could|may|might|should|is|am|why|what|when|where|how|who|which)\b/i.test(text);
  if (verbStart) return false;
  return true;
}

// vibrate is best-effort — desktop browsers ignore it, mobile honors it.
function vibrate(pattern: number | number[]) {
  if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
    try { navigator.vibrate(pattern); } catch { /* ignore */ }
  }
}
const playJobFoundCue = () => {
  playTone([523.25, 659.25], 0.18, "sine");           // C5 → E5
  vibrate([60, 40, 60]);                               // short double-buzz
};
const playQuestionCue = () => {
  playTone([392, 523.25, 392], 0.22, "triangle");     // G4 → C5 → G4
  vibrate([120, 60, 120, 60, 200]);                   // longer "hey, look at this" pattern
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
  // Restore the spinner if the user navigated away during a discovery
  // and came back. Server-side work continues regardless; this just
  // keeps the UI accurate. Auto-clears after 90s in case the call
  // crashed or the response was lost.
  useEffect(() => {
    try {
      const startedAtRaw = sessionStorage.getItem("instaply_discovery_started");
      if (!startedAtRaw) return;
      const startedAt = Number(startedAtRaw);
      const elapsed = Date.now() - startedAt;
      if (Number.isFinite(startedAt) && elapsed < 90_000) {
        setDiscovering(true);
        const remaining = 90_000 - elapsed;
        const t = setTimeout(() => {
          setDiscovering(false);
          try { sessionStorage.removeItem("instaply_discovery_started"); } catch {}
          // Refresh to pick up anything that landed while we were away.
          loadAll();
        }, remaining);
        return () => clearTimeout(t);
      } else {
        sessionStorage.removeItem("instaply_discovery_started");
      }
    } catch { /* sessionStorage unavailable — skip silently */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [activityFilter, setActivityFilter] = useState<string>("all");
  const [expandedAppId, setExpandedAppId] = useState<string | null>(null);
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({});
  const [savingAnswer, setSavingAnswer] = useState<string | null>(null);
  // Per-card optimistic state for "I submitted this manually" — disable
  // the button + show "Marking…" while the PATCH is in flight, then the
  // row disappears from Needs attention on the next loadAll() refresh.
  const [markingManualIds, setMarkingManualIds] = useState<Set<string>>(() => new Set());
  // Whether the Instaply Chrome extension is installed AND alive.
  // Probed once on mount via lib/extension.isExtensionInstalled (which
  // pings via chrome.runtime.sendMessage with an 800 ms timeout). When
  // true, the Open & finish button on captcha/verification rows hands
  // the fill payload off to the extension instead of opening the raw
  // apply_url. When false (or NEXT_PUBLIC_EXTENSION_ID unset), behavior
  // is identical to before — plain open-in-new-tab fallback.
  const [extInstalled, setExtInstalled] = useState(false);
  const [openingViaExtId, setOpeningViaExtId] = useState<string | null>(null);
  // Brief inline acknowledgement after a manual mark succeeds. Cleared
  // after ~3s so the section feels responsive without bolting on a
  // toast library.
  const [manualMarkSuccessId, setManualMarkSuccessId] = useState<string | null>(null);
  const [audioCuesEnabled, setAudioCuesEnabled] = useState(true);

  // Track previously-seen IDs to detect new arrivals between polls.
  // First load seeds the baseline (no sound played) — only subsequent loads ding.
  const seenPendingIds = useRef<Set<string> | null>(null);
  const seenNeedsReviewAppIds = useRef<Set<string> | null>(null);

  const saveAnswer = async (appId: string, question: string, key: string) => {
    const answer = (answerDrafts[key] || "").trim();
    if (!answer) return;
    setSavingAnswer(key);
    try {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      await fetch(`${API_BASE}/answers/save`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          question,
          answer,
          application_id: appId,
        }),
      });
      // Clear the draft and refresh activity (re-queues the app on backend)
      setAnswerDrafts((d) => ({ ...d, [key]: "" }));
      await loadAll();
    } finally {
      setSavingAnswer(null);
    }
  };

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
      supabase.from("applications").select("id, status, queued_at, started_at, error_message, submission_log, screenshot_url, jobs(title, company_name, apply_url)").eq("user_id", user.id).order("queued_at", { ascending: false }).limit(6),
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

    const newPending = (pendingData ?? []) as unknown as PendingJob[];
    const newRecent = (recentData ?? []) as unknown as RecentApp[];

    // Detect new pending jobs since last poll → "job found" chime.
    if (audioCuesEnabled) {
      const currentPendingIds = new Set(newPending.map((p) => p.id));
      if (seenPendingIds.current === null) {
        seenPendingIds.current = currentPendingIds;
      } else {
        const fresh = [...currentPendingIds].filter((id) => !seenPendingIds.current!.has(id));
        if (fresh.length > 0) playJobFoundCue();
        seenPendingIds.current = currentPendingIds;
      }

      // Detect apps that just gained REAL needs_review questions → "question" bell.
      // Junk labels (Workday section headings, step counters) don't count —
      // we'd be pinging the user for nothing they can actually answer.
      const currentNeedsReview = new Set(
        newRecent
          .filter((a) => {
            try {
              const log = a.submission_log ? JSON.parse(a.submission_log) : null;
              if (!Array.isArray(log?.needs_review)) return false;
              return log.needs_review.some((q: { question?: string; kind?: string }) => !isJunkQuestion(q));
            } catch {
              return false;
            }
          })
          .map((a) => a.id),
      );
      if (seenNeedsReviewAppIds.current === null) {
        seenNeedsReviewAppIds.current = currentNeedsReview;
      } else {
        const fresh = [...currentNeedsReview].filter((id) => !seenNeedsReviewAppIds.current!.has(id));
        if (fresh.length > 0) playQuestionCue();
        seenNeedsReviewAppIds.current = currentNeedsReview;
      }
    }

    setPending(newPending);
    setRecent(newRecent);
    setLoading(false);
  }, [ready, audioCuesEnabled]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Auto-refresh recent activity every 10 seconds so users see status updates
  // (queued -> submitting -> submitted -> confirmed) without manual refresh.
  // Pauses when the tab is hidden — no point burning Supabase quota for a
  // user who's looking at another tab. Resumes immediately on visibility.
  useEffect(() => {
    if (!ready) return;
    let interval: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (interval) return;
      interval = setInterval(() => loadAll(), 10000);
    };
    const stop = () => {
      if (interval) {
        clearInterval(interval);
        interval = null;
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        loadAll();   // immediate refresh on return
        start();
      } else {
        stop();
      }
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [ready, loadAll]);

  // Tick every second to update live timers on in_progress applications
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const hasInProgress = recent.some((a) => a.status === "in_progress");
    if (!hasInProgress) return;
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, [recent]);

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
    // Persist the "discovery in flight" flag in sessionStorage so the
    // spinner survives a page refresh or quick navigation away and
    // back. The server-side discovery runs independently of the page
    // lifecycle either way — this just keeps the UI honest about what
    // Instaply is doing in the background. Cleared when the call
    // resolves OR after a hard timeout (90s — discovery never legitimately
    // takes longer than that).
    try { sessionStorage.setItem("instaply_discovery_started", String(Date.now())); } catch {}
    try {
      const res = await fetch(`${API_BASE}/auto-apply/run-now`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${accessToken}` },
      });
      if (!res.ok) throw new Error(await res.text());
      await loadAll();
    } catch (e) {
      console.error("Discovery failed:", e);
    } finally {
      setDiscovering(false);
      try { sessionStorage.removeItem("instaply_discovery_started"); } catch {}
    }
  };

  // The decideOne / decideAll approve/skip helpers were removed on
  // 2026-04-19 along with the user-approval surface. Discovery now
  // inserts directly into `applications` with status='queued' and the
  // worker picks them up. Any legacy pending_approval rows in the DB
  // are no longer rendered as a decision surface.

  const fmtRelative = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  };

  type NeedsReviewQuestion = {
    question: string;
    kind?: string;
    url?: string;
    suggested?: string | null;
  };

  // Parse submission_log JSON safely
  type SubLog = { status?: string; platform_detected?: string; filled_fields?: string[]; needs_review?: NeedsReviewQuestion[]; auto_answered?: string[]; submitted?: boolean; submit_reason?: string; action_required?: { kind?: string; url?: string; instructions?: string }; attempt_count?: number; stage?: string; in_flight?: boolean; stage_elapsed?: number };
  const parseLog = (raw: string | null): SubLog | null => {
    if (!raw) return null;
    try { return typeof raw === "string" ? JSON.parse(raw) : raw; } catch { return null; }
  };
  const getRealNeedsReview = (log: SubLog | null) => (log?.needs_review || []).filter((q) => !isJunkQuestion(q));

  const retryApplication = async (appId: string) => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    await supabase
      .from("applications")
      .update({
        status: "queued",
        error_message: null,
        started_at: null,
        submission_log: null,
      })
      .eq("id", appId);
    if (seenNeedsReviewAppIds.current) {
      seenNeedsReviewAppIds.current.delete(appId);
    }
    await loadAll();
  };

  // One-shot extension probe on mount. The probe is cheap (~800 ms
  // worst case, completes in a few ms when installed) and idempotent;
  // re-probing on every render would just churn the message channel.
  useEffect(() => {
    let cancelled = false;
    isExtensionInstalled().then((installed) => {
      if (!cancelled) setExtInstalled(installed);
    });
    return () => { cancelled = true; };
  }, []);

  // Assemble + ship the fill payload to the extension for one row.
  // The extension never touches Supabase directly — the dashboard
  // (which already holds the user's authenticated session) fetches
  // the profile + answer-vault rows and pushes them per request.
  // Conservative: if the extension reports an error or the user has
  // no apply_url, we silently fall back to the plain link behavior
  // by allowing the click to proceed normally.
  const handoffToExtension = async (
    appId: string,
    applyUrl: string,
  ): Promise<{ ok: boolean; error?: string }> => {
    const supabase = getBrowserSupabase();
    if (!supabase) return { ok: false, error: "no_supabase_client" };
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.user) return { ok: false, error: "no_user_session" };
    const user = session.user;
    // Fetch only the profile fields the extension's content scripts
    // can actually consume (matches lib/extension.ts FillRequest.profile).
    // Fewer round trips + no over-sharing PII into the extension's
    // session storage.
    const profilePromise = supabase
      .from("profiles")
      .select("first_name,last_name,full_name,email,phone_e164,phone_national,phone,linkedin_url,github_url,portfolio_url,website_url,city,current_city,state,current_state,country,current_country,postal_code,zip_code,current_company,current_title,school,major,degree")
      .eq("id", user.id)
      .single();
    const answersPromise = supabase
      .from("answers")
      .select("question_text,answer_text")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false })
      .limit(200);
    const [profileResult, answersResult] = await Promise.all([profilePromise, answersPromise]);
    const profile = (profileResult.data as Record<string, unknown> | null) || {};
    const answers = (answersResult.data as Array<{ question_text: string; answer_text: string }> | null) || [];
    // Pass the user's Supabase JWT + API base to the extension so the
    // content script can POST /applications/{id}/extension-finish on
    // the user's behalf after they complete verification + submit.
    // Without this the row would still need a manual "I submitted
    // this manually" click on the dashboard to close the loop.
    return triggerExtensionFill({
      applicationId: appId,
      applyUrl,
      accessToken: session.access_token,
      apiBase: API_BASE,
      profile: profile as never,
      answers,
    });
  };

  // Manual completion path for captcha-blocked / Needs attention rows.
  // The user clicked "Open & finish", solved the captcha on the
  // employer's site themselves, and confirmed the submission landed.
  // We mark the application as submitted via the 'manual' submitter_kind
  // (already in the CHECK constraint allow-list per migration 0014 —
  // documented there as "ops-issued / backfill", same semantics here).
  // Preserves submission_log / screenshot_url / error_message so the
  // audit trail of what the worker tried before the user took over
  // stays intact.
  const markManuallySubmitted = async (appId: string) => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    await supabase
      .from("applications")
      .update({
        status: "submitted",
        submitter_kind: "manual",
        completed_at: new Date().toISOString(),
        // intentionally NOT clearing submission_log / screenshot_url /
        // error_message — those record what the worker attempted before
        // the human took over and are useful for support diagnostics.
      })
      .eq("id", appId);
    if (seenNeedsReviewAppIds.current) {
      seenNeedsReviewAppIds.current.delete(appId);
    }
    await loadAll();
  };

  const renderNeedsReviewContent = (
    a: RecentApp,
    log: SubLog | null,
    opts?: { prominent?: boolean },
  ) => {
    const realQs = getRealNeedsReview(log);
    if (realQs.length === 0) return null;
    const attempts = log?.attempt_count || 0;
    const tooManyAttempts = attempts >= 3;
    const prominent = opts?.prominent ?? false;

    return (
      <div
        className="auto-detail-row auto-needs-answer"
        style={prominent ? { marginTop: 0, borderRadius: 18, padding: 18, background: "rgba(255, 214, 10, 0.08)", border: "1px solid rgba(255, 214, 10, 0.22)" } : undefined}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <strong style={prominent ? { fontSize: 16 } : undefined}>
            {prominent ? "Action needed now" : "The agent needs you to answer:"}
          </strong>
          {attempts > 1 && (
            <span
              className="auto-meta"
              style={{
                fontSize: 11,
                padding: "2px 8px",
                borderRadius: 999,
                background: tooManyAttempts ? "rgba(255,80,80,0.15)" : "rgba(255,200,80,0.12)",
                color: tooManyAttempts ? "#ff8080" : "var(--muted)",
                border: `1px solid ${tooManyAttempts ? "rgba(255,80,80,0.3)" : "rgba(255,255,255,0.12)"}`,
              }}
            >
              Tried {attempts} time{attempts === 1 ? "" : "s"}
            </span>
          )}
        </div>
        {prominent && (
          <div style={{ margin: "8px 0 12px" }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              {a.jobs?.title || "Job"} at {a.jobs?.company_name || "company"}
            </div>
            <p style={{ margin: "6px 0 0", fontSize: 12.5, color: "var(--muted)" }}>
              The agent is paused on this application until you answer these question{realQs.length === 1 ? "" : "s"}.
              Once you save one, we re-queue the application and keep going.
            </p>
          </div>
        )}
        {tooManyAttempts && (
          <p style={{ margin: "8px 0 12px", fontSize: 12.5, color: "#ff9090" }}>
            We&apos;ve tried {attempts} times and keep getting stuck. This form probably needs to be filled by hand. Open the link and finish it manually, or stop retrying.
            <button
              type="button"
              className="btn-secondary auto-btn-sm"
              style={{ marginLeft: 10 }}
              onClick={async (e) => {
                e.stopPropagation();
                const supabase = getBrowserSupabase();
                if (!supabase) return;
                if (!confirm("Stop retrying this application? It will be marked failed and won't be picked up again.")) return;
                await supabase
                  .from("applications")
                  .update({
                    status: "failed",
                    error_message: `Stopped retrying after ${attempts} attempts. Apply manually if you still want this role.`,
                  })
                  .eq("id", a.id);
                if (seenNeedsReviewAppIds.current) seenNeedsReviewAppIds.current.delete(a.id);
                await loadAll();
              }}
            >
              Stop retrying
            </button>
          </p>
        )}
        <p style={{ margin: "4px 0 12px", fontSize: 12, color: "var(--muted)" }}>
          Type your answer below — we&apos;ll save it and reuse it for similar questions on future applications. Answer once, never again.
        </p>
        {realQs.slice(0, 5).map((q, i) => {
          const key = `${a.id}-${i}`;
          const draft = answerDrafts[key] || "";
          const isSaving = savingAnswer === key;
          if (q.kind === "verification") {
            const url = q.url || a.jobs?.apply_url || "";
            return (
              <div className="auto-question-block" key={i}>
                <label className="auto-question-label">{q.question}</label>
                <div className="auto-question-input-row">
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-primary auto-btn-sm"
                    onClick={(e) => e.stopPropagation()}
                    style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 6 }}
                  >
                    <ExternalLink size={12} /> Open & finish step
                  </a>
                  <button
                    type="button"
                    className="btn-secondary auto-btn-sm"
                    onClick={async (e) => {
                      e.stopPropagation();
                      await retryApplication(a.id);
                    }}
                  >
                    I&apos;m done — retry
                  </button>
                </div>
              </div>
            );
          }
          // Cryptic question — too thin to safely answer in a text box
          // (e.g. an option label that leaked as the question text). Show
          // an "Open the form manually" CTA instead of a guess-and-pray
          // input. Same visual shell as the `verification` branch above
          // so the dashboard's UX vocabulary stays consistent.
          if (isCrypticQuestion(q)) {
            const url = q.url || a.jobs?.apply_url || "";
            const suggested = (q.suggested || "").trim();
            return (
              <div className="auto-question-block" key={i}>
                <label className="auto-question-label">
                  {q.question}
                  <span style={{ marginLeft: 8, fontSize: 11, color: "var(--muted)", fontWeight: "normal" }}>
                    (needs manual review)
                  </span>
                </label>
                <p style={{ margin: "2px 0 8px", fontSize: 12, color: "var(--muted)" }}>
                  This field doesn&apos;t give us enough context to ask you safely.
                  {suggested ? (
                    <> The agent guessed <strong>{suggested}</strong> — open the form to confirm or fix it.</>
                  ) : (
                    <> Open the form to handle it.</>
                  )}
                </p>
                <div className="auto-question-input-row">
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-primary auto-btn-sm"
                    onClick={(e) => e.stopPropagation()}
                    style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 6 }}
                  >
                    <ExternalLink size={12} /> Open form
                  </a>
                  <button
                    type="button"
                    className="btn-secondary auto-btn-sm"
                    onClick={async (e) => {
                      e.stopPropagation();
                      await retryApplication(a.id);
                    }}
                  >
                    I&apos;m done — retry
                  </button>
                </div>
              </div>
            );
          }
          return (
            <div className="auto-question-block" key={i}>
              <label className="auto-question-label">{q.question}</label>
              <div className="auto-question-input-row">
                <input
                  type="text"
                  value={draft}
                  onChange={(e) => setAnswerDrafts((d) => ({ ...d, [key]: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && saveAnswer(a.id, q.question, key)}
                  placeholder={q.suggested ? `Agent suggests: ${q.suggested}` : "Your answer..."}
                  onClick={(e) => e.stopPropagation()}
                />
                <button
                  type="button"
                  className="btn-primary auto-btn-sm"
                  onClick={(e) => { e.stopPropagation(); saveAnswer(a.id, q.question, key); }}
                  disabled={!draft.trim() || isSaving}
                >
                  {isSaving ? "Saving..." : "Save & Retry"}
                </button>
              </div>
              {/* For verify_suggested entries (the agent already filled
                  a value but flagged it for review), expose the
                  suggestion as a one-click "Use this" so the user
                  doesn't have to retype the agent's grounded answer.
                  Cryptic items hit a different render branch above; this
                  only fires on real-label questions. */}
              {q.suggested && q.suggested.trim() && !draft && (
                <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--muted)" }}>
                  Agent suggests:{" "}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setAnswerDrafts((d) => ({ ...d, [key]: q.suggested || "" }));
                    }}
                    style={{
                      background: "none",
                      border: "none",
                      color: "#7adfa3",
                      cursor: "pointer",
                      padding: 0,
                      textDecoration: "underline",
                      font: "inherit",
                    }}
                  >
                    {q.suggested}
                  </button>{" "}
                  — click to use, or type your own above.
                </p>
              )}
            </div>
          );
        })}
        {realQs.length > 5 && (
          <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
            + {realQs.length - 5} more questions. Answer the first 5 and we&apos;ll re-run the agent.
          </p>
        )}
      </div>
    );
  };

  // Live elapsed timer for in-progress submissions (uses `tick` to re-render)
  const fmtElapsed = (iso: string | null) => {
    if (!iso) return "0s";
    void tick; // keep linter happy — we depend on tick for re-renders
    const diff = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
    const mins = Math.floor(diff / 60);
    const secs = diff % 60;
    if (mins === 0) return `${secs}s`;
    return `${mins}m ${secs}s`;
  };

  const matchClass = (s: number) => (s >= 70 ? "auto-match-high" : s >= 40 ? "auto-match-mid" : "auto-match-low");

  const isPaused = snap.auto_apply_paused_until && new Date(snap.auto_apply_paused_until) > new Date();
  const agentOn = snap.auto_apply_enabled && !isPaused;
  const firstName = snap.full_name?.split(" ")[0] || "there";
  const needsReviewApps = recent
    .map((a) => ({ app: a, log: parseLog(a.submission_log) }))
    .filter(({ log }) => getRealNeedsReview(log).length > 0);

  // Failed-but-actionable rows surface in a separate "Needs attention"
  // section so the user can either retry or finish manually without
  // hunting for the row in the activity feed. Inclusion rule is
  // intentionally narrow (per 2026-04-19 UX spec):
  //   - status === "failed"
  //   - submission_log.submit_reason is set (proves the run actually
  //     executed — distinguishes from generic queue failures)
  //   - failure looks user-resolvable: matches one of the allow-list
  //     keywords OR a screenshot was captured (which strongly
  //     correlates with a real attempt the user can finish manually)
  //   - excludes clearly permanent/non-actionable failure reasons
  //
  // Also excludes rows that are already in needsReviewApps — those
  // belong in "Action required" with the answer-input UX, not here.
  const _ATTN_RESOLVABLE_RX = /(no_confirmation_signal|submit_click_failed|Submission exceeded|captcha_required|verification_required)/i;
  const _ATTN_PERMANENT_RX = /(Workday support is temporarily disabled|no_application_form_found)/i;
  const isAttentionEligible = (a: RecentApp, log: SubLog | null): boolean => {
    if (a.status !== "failed") return false;
    const reason = log?.submit_reason || "";
    if (!reason) return false;
    if (_ATTN_PERMANENT_RX.test(reason)) return false;
    return _ATTN_RESOLVABLE_RX.test(reason) || Boolean(a.screenshot_url);
  };
  const needsReviewIds = new Set(needsReviewApps.map(({ app }) => app.id));
  const needsAttentionApps = recent
    .map((a) => ({ app: a, log: parseLog(a.submission_log) }))
    .filter(({ app, log }) => !needsReviewIds.has(app.id) && isAttentionEligible(app, log));

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
                <strong>Instaply applies automatically.</strong>
                <p>You only step in for review questions or verification walls.</p>
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
      description={agentOn ? "Your agent is active and applying automatically." : "Your agent is paused. Turn it on to start finding jobs."}
      actions={[{ href: "/applications", label: "View activity", variant: "secondary" }]}
    >
      {/* MASTER SWITCH */}
      <section className="console-section">
        <article className="glass auto-master-card">
          <div className="auto-master-copy">
            <h2>{agentOn ? "Agent is active" : "Start your agent"}</h2>
            <p>
              {agentOn
                ? `Searching daily for: ${snap.target_titles.slice(0, 3).join(", ")}${snap.target_titles.length > 3 ? "..." : ""}. Each submission takes 1-3 minutes because the agent imitates a human (clicks, scrolls, types) so forms don't block it.`
                : "Turn on the agent and we'll find jobs matching your profile, queue them automatically, and only pull you in when something needs attention."}
            </p>
            {agentOn && (
              <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
                Greenhouse and Lever applications are submitted automatically. Other portals (Workday, LinkedIn, Indeed) need to be applied to manually for now — we&apos;ll surface those clearly so you can open them in a new tab.
              </p>
            )}
            {agentOn && (
              <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
                <strong style={{ color: "var(--text)" }}>Canary note:</strong> applications stop at <em>Submitted</em> or <em>Needs review</em> for now — you won&apos;t see <em>Confirmed</em> until our email-verification worker ships. <strong>You are not charged for any application during the canary.</strong>
              </p>
            )}
            <div className="auto-master-status">
              <span className={`auto-pill ${agentOn ? "auto-pill-active" : "auto-pill-paused"}`}>
                {agentOn ? "Active" : isPaused ? "Paused" : "Off"}
              </span>
              {snap.auto_apply_last_run_at && (
                <span className="auto-meta">Last run · {fmtRelative(snap.auto_apply_last_run_at)}</span>
              )}
              <span className="auto-meta">{credits} credits</span>
              <button
                type="button"
                className="auto-meta auto-cue-toggle"
                title={audioCuesEnabled ? "Mute audio cues" : "Unmute audio cues"}
                aria-label={audioCuesEnabled ? "Mute audio cues for new jobs and questions" : "Unmute audio cues for new jobs and questions"}
                aria-pressed={audioCuesEnabled}
                onClick={() => {
                  setAudioCuesEnabled((v) => {
                    const next = !v;
                    // Play a sample chime when re-enabling so the user knows it works
                    if (next) playJobFoundCue();
                    return next;
                  });
                }}
                style={{
                  background: "transparent",
                  border: "1px solid var(--border, rgba(255,255,255,0.12))",
                  borderRadius: 999,
                  padding: "4px 10px",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  cursor: "pointer",
                }}
              >
                {audioCuesEnabled ? <Bell size={12} /> : <BellOff size={12} />}
                {audioCuesEnabled ? "Sounds on" : "Sounds off"}
              </button>
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

      {needsReviewApps.length > 0 && (
        <section className="console-section">
          <article className="glass auto-card" style={{ border: "1px solid rgba(255, 214, 10, 0.24)", boxShadow: "0 18px 60px rgba(0,0,0,0.22)" }}>
            <header className="auto-card-head">
              <div>
                <p className="eyebrow" style={{ color: "#ffd65a" }}>Action required</p>
                <h3 style={{ marginBottom: 4 }}>Finish these before anything else</h3>
                <p className="auto-card-sub">
                  Your agent is waiting on you. Answer these questions and we&apos;ll immediately re-queue the application.
                </p>
              </div>
              <span className="auto-pill auto-pill-paused">
                {needsReviewApps.length} waiting
              </span>
            </header>
            <div style={{ display: "grid", gap: 16 }}>
              {needsReviewApps.map(({ app, log }) => (
                <div key={app.id}>
                  {renderNeedsReviewContent(app, log, { prominent: true })}
                </div>
              ))}
            </div>
          </article>
        </section>
      )}

      {/* "Needs attention" — failed-but-actionable rows. Distinct from
          "Action required" both visually (amber instead of yellow) and
          semantically: there are no questions to answer, the agent
          tried and hit a wall (usually captcha or a transient submit
          error). One click to retry or open the form. See the
          isAttentionEligible() helper above for the inclusion rule. */}
      {needsAttentionApps.length > 0 && (
        <section className="console-section">
          <article className="glass auto-card" style={{ border: "1px solid rgba(255, 153, 51, 0.24)", boxShadow: "0 18px 60px rgba(0,0,0,0.18)" }}>
            <header className="auto-card-head">
              <div>
                <p className="eyebrow" style={{ color: "#ff9933" }}>Needs attention</p>
                <h3 style={{ marginBottom: 4 }}>The agent tried but couldn&apos;t finish</h3>
                <p className="auto-card-sub">
                  Form was filled, but the submit didn&apos;t go through (often a captcha or a temporary block).
                  Retry to let the agent try again, or open the form to finish manually.
                </p>
              </div>
              <span className="auto-pill auto-pill-paused" style={{ background: "rgba(255, 153, 51, 0.16)", color: "#ffb766", borderColor: "rgba(255, 153, 51, 0.3)" }}>
                {needsAttentionApps.length} waiting
              </span>
            </header>
            <div style={{ display: "grid", gap: 12 }}>
              {needsAttentionApps.map(({ app, log }) => {
                const url = app.jobs?.apply_url || "";
                const reason = log?.submit_reason || app.error_message || "";
                // Map worker-side submit_reason taxonomy to plain-English
                // user-facing explanations. The captcha_required and
                // verification_required reasons are emitted when the
                // worker's _classify_post_submit_block() detects an
                // hCaptcha or reCAPTCHA wall in the post-click DOM —
                // both mean "form was filled, the wall stops us, you
                // need to finish in your own browser." Retry against
                // the same wall is futile, so we de-emphasize that
                // button for these two reasons specifically.
                const isCaptcha = /captcha_required/i.test(reason);
                const isVerification = /verification_required/i.test(reason);
                const isWallBlocked = isCaptcha || isVerification;
                const reasonShort =
                  isCaptcha ? "Form was filled. A captcha (hCaptcha) blocked submit — finish it in your browser."
                  : isVerification ? "Form was filled. A verification check (reCAPTCHA) blocked submit — finish it in your browser."
                  : /no_confirmation_signal/i.test(reason) ? "Submit click landed but no confirmation page was detected (often a silent verification check)."
                  : /submit_click_failed/i.test(reason) ? "Submit button found but the click couldn't complete."
                  : /Submission exceeded/i.test(reason) ? "Submission timed out before confirmation."
                  : "Run finished without confirmation.";
                return (
                  <div
                    key={app.id}
                    className="auto-detail-row"
                    style={{ marginTop: 0, borderRadius: 16, padding: 16, background: "rgba(255, 153, 51, 0.06)", border: "1px solid rgba(255, 153, 51, 0.18)" }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <strong style={{ fontSize: 15 }}>
                          {app.jobs?.company_name || "Unknown company"} — {app.jobs?.title || "Untitled role"}
                        </strong>
                        <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--muted)" }}>
                          {reasonShort}
                        </p>
                      </div>
                      <div style={{ display: "flex", gap: 8, flexShrink: 0, flexWrap: "wrap", justifyContent: "flex-end" }}>
                        {url && (
                          // When the extension is installed AND this is a
                          // captcha/verification row, hand the fill payload
                          // off to the extension instead of opening the raw
                          // URL — the extension opens the tab itself, fills
                          // from the user's profile + saved answers in
                          // their real browser at their real IP, and
                          // surfaces a "solve verification manually" banner
                          // when a captcha widget appears. Honest contract:
                          // we never bypass captchas, the user solves them.
                          //
                          // For everyone else (no extension OR non-wall
                          // failures) keep the original plain anchor: open
                          // apply_url in a new tab, no special handling.
                          extInstalled && isWallBlocked ? (
                            <button
                              type="button"
                              className={`${isWallBlocked ? "btn-primary" : "btn-secondary"} auto-btn-sm`}
                              disabled={openingViaExtId === app.id}
                              onClick={async (e) => {
                                e.stopPropagation();
                                setOpeningViaExtId(app.id);
                                try {
                                  const r = await handoffToExtension(app.id, url);
                                  if (!r.ok) {
                                    // Fallback: extension said no — open
                                    // the raw URL ourselves so the user
                                    // isn't stuck. window.open from a user
                                    // gesture works without popup blocker
                                    // issues.
                                    window.open(url, "_blank", "noopener,noreferrer");
                                  }
                                } finally {
                                  setOpeningViaExtId(null);
                                }
                              }}
                              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                              title="Opens the form in your browser via the Instaply extension and pre-fills it. You'll still solve the captcha manually."
                            >
                              <ExternalLink size={12} />
                              {openingViaExtId === app.id ? "Opening…" : "Open & finish (extension)"}
                            </button>
                          ) : (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={`${isWallBlocked ? "btn-primary" : "btn-secondary"} auto-btn-sm`}
                              onClick={(e) => e.stopPropagation()}
                              style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 6 }}
                            >
                              <ExternalLink size={12} /> Open &amp; finish
                            </a>
                          )
                        )}
                        <button
                          type="button"
                          className="btn-secondary auto-btn-sm"
                          disabled={markingManualIds.has(app.id)}
                          onClick={async (e) => {
                            e.stopPropagation();
                            setMarkingManualIds((s) => {
                              const n = new Set(s); n.add(app.id); return n;
                            });
                            try {
                              await markManuallySubmitted(app.id);
                              setManualMarkSuccessId(app.id);
                              setTimeout(() => {
                                setManualMarkSuccessId((curr) => (curr === app.id ? null : curr));
                              }, 3000);
                            } finally {
                              setMarkingManualIds((s) => {
                                const n = new Set(s); n.delete(app.id); return n;
                              });
                            }
                          }}
                        >
                          {markingManualIds.has(app.id) ? "Marking…" : "I submitted this manually"}
                        </button>
                        <button
                          type="button"
                          // For wall-blocked rows, retry is futile so we
                          // demote it to a tertiary text button (still
                          // available, just visually de-emphasized).
                          className={`${isWallBlocked ? "btn-secondary" : "btn-primary"} auto-btn-sm`}
                          onClick={async (e) => {
                            e.stopPropagation();
                            await retryApplication(app.id);
                          }}
                          title={isWallBlocked ? "Retry will likely hit the same verification wall — Open & finish is recommended." : undefined}
                          style={isWallBlocked ? { opacity: 0.7 } : undefined}
                        >
                          Retry
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
              {manualMarkSuccessId && (
                <p
                  style={{
                    margin: "4px 0 0",
                    fontSize: 12.5,
                    color: "#7adfa3",
                    background: "rgba(122, 223, 163, 0.08)",
                    border: "1px solid rgba(122, 223, 163, 0.22)",
                    padding: "8px 12px",
                    borderRadius: 10,
                  }}
                >
                  ✓ Marked as submitted manually. The row now lives in your activity feed under <strong>submitted</strong>.
                </p>
              )}
            </div>
          </article>
        </section>
      )}

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
              <span style={{ fontSize: 13, color: "var(--muted)" }}>
                Usually 10–15 seconds. You can navigate away — Instaply keeps working in the background and new jobs appear here when they&apos;re ready.
              </span>
            </div>
          </article>
        </section>
      )}

      {/* PENDING APPROVAL */}
      {/* Autonomous-mode status panel. Replaced the prior
          "Approve / Skip" surface (2026-04-19): matching jobs now go
          straight into `applications` with status='queued' and the
          worker picks them up. The user only sees what's currently
          applying or what needs attention afterward. The `pending`
          state is still fetched for backward compat with any legacy
          pending_approval rows in the DB but no longer rendered as a
          decision surface. */}
      {agentOn && (
        <section className="console-section">
          <article className="glass auto-card">
            <header className="auto-card-head">
              <div>
                <p className="eyebrow" style={{ color: "var(--accent)" }}>Auto-apply</p>
                <h3>Instaply applies to matching jobs automatically</h3>
                <p className="auto-card-sub">
                  When the agent finds a match, it queues the application and submits it for you.
                  You only get pulled in for rows under <strong>Needs attention</strong> (review questions
                  or verification walls). One blocked application doesn&apos;t pause the others —
                  the queue keeps moving. You can close this tab; Instaply keeps applying in the background.
                </p>
              </div>
            </header>
          </article>
        </section>
      )}

      {/* No-recent-activity nudge. Replaces the prior "no new matches"
          block keyed on `pending` (which is no longer the product
          model). Now keyed on the actual queued/in-progress count. */}
      {recent.filter((a) => ["queued", "in_progress"].includes(a.status)).length === 0 &&
       agentOn && !discovering && (
        <section className="console-section">
          <article className="glass auto-card" style={{ textAlign: "center", padding: 36 }}>
            <Sparkles size={28} style={{ color: "var(--accent)", margin: "0 auto 12px" }} />
            <h3 style={{ fontSize: 16, margin: "0 0 6px" }}>Nothing in flight right now</h3>
            <p style={{ fontSize: 13.5, color: "var(--muted)", margin: "0 auto 16px", maxWidth: 480 }}>
              The agent runs on a schedule. Trigger a fresh search now if you want it to look immediately.
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

            <div className="auto-activity-filter">
              {(["all", "queued", "in_progress", "needs_review", "submitted", "confirmed", "failed"] as const).map((f) => {
                const count = f === "all" ? recent.length : recent.filter((r) => r.status === f).length;
                if (f !== "all" && count === 0) return null;
                return (
                  <button
                    key={f}
                    type="button"
                    className={`auto-activity-chip ${activityFilter === f ? "auto-activity-chip-active" : ""}`}
                    onClick={() => setActivityFilter(f)}
                  >
                    {f === "all"
                      ? "All"
                      : f === "in_progress"
                        ? "Submitting"
                        : f === "needs_review"
                          ? "Needs review"
                          : f.charAt(0).toUpperCase() + f.slice(1)} <span>{count}</span>
                  </button>
                );
              })}
            </div>

            <div className="auto-activity">
              {recent.filter((a) => activityFilter === "all" || a.status === activityFilter).map((a) => {
                const log = parseLog(a.submission_log);
                const isExpanded = expandedAppId === a.id;
                const hasDetails = !!(log || a.error_message);
                return (
                  <div key={a.id}>
                    <div
                      className={`auto-activity-row ${hasDetails ? "auto-activity-row-clickable" : ""}`}
                      onClick={() => hasDetails && setExpandedAppId(isExpanded ? null : a.id)}
                    >
                      <span className="auto-activity-time">{fmtRelative(a.queued_at)}</span>
                      <span className={`auto-status-pill auto-status-${a.status}`}>
                        {a.status === "in_progress" ? "Submitting" : a.status.charAt(0).toUpperCase() + a.status.slice(1)}
                      </span>
                      {a.status === "in_progress" && a.started_at && (
                        <span
                          className="auto-elapsed-timer"
                          title="The agent imitates a human filling out the form (clicks, scrolls, types) so it doesn't get blocked. Submission usually takes 1-3 minutes."
                        >
                          <Loader2 size={11} className="spin" />
                          {fmtElapsed(a.started_at)}
                        </span>
                      )}
                      <span className="auto-activity-text">
                        Applied to <strong>{a.jobs?.title || "job"}</strong> at <strong>{a.jobs?.company_name || "company"}</strong>
                        {a.status === "in_progress" && log?.in_flight && log.stage && (
                          <span
                            style={{
                              display: "block",
                              fontSize: 12,
                              color: "var(--muted)",
                              marginTop: 2,
                              fontStyle: "italic",
                            }}
                          >
                            {log.stage}
                          </span>
                        )}
                      </span>
                      {hasDetails && (
                        <span className="auto-activity-toggle">{isExpanded ? "−" : "▾ Details"}</span>
                      )}
                      {a.jobs?.apply_url && (
                        <a
                          href={a.jobs.apply_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="auto-activity-link"
                          onClick={(e) => e.stopPropagation()}
                          aria-label={`Open ${a.jobs.title || "job"} at ${a.jobs.company_name || "company"} in a new tab`}
                          title="Open job posting"
                        >
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                    {isExpanded && (
                      <div className="auto-activity-details">
                        {log?.platform_detected && (
                          <div className="auto-detail-row">
                            <strong>Platform:</strong> {log.platform_detected}
                          </div>
                        )}
                        {log?.filled_fields && log.filled_fields.length > 0 && (
                          <div className="auto-detail-row">
                            <strong>Fields filled ({log.filled_fields.length}):</strong>
                            <div className="auto-detail-chips">
                              {log.filled_fields.map((f, i) => (
                                <span className="auto-detail-chip auto-detail-chip-ok" key={i}>✓ {f}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {log?.auto_answered && log.auto_answered.length > 0 && (
                          <div className="auto-detail-row">
                            <strong>AI-answered:</strong>
                            <div className="auto-detail-chips">
                              {log.auto_answered.map((q, i) => (
                                <span className="auto-detail-chip" key={i}>{q}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {renderNeedsReviewContent(a, log)}
                        {a.error_message && (
                          <div className="auto-detail-row auto-detail-error">
                            <strong>What happened:</strong>
                            <p>{a.error_message}</p>
                          </div>
                        )}
                        {log && !log.submitted && a.status === "failed" && (
                          <div className="auto-detail-row" style={{ color: "var(--muted)", fontSize: 12 }}>
                            <em>Click Retry on the Applications page to try again.</em>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
              {recent.filter((a) => activityFilter === "all" || a.status === activityFilter).length === 0 && (
                <div style={{ fontSize: 13, color: "var(--muted)", textAlign: "center", padding: 16 }}>
                  No applications with this status.
                </div>
              )}
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
              <strong>Instaply applies automatically.</strong>
              <p>You only get pulled in for review questions or verification walls.</p>
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
