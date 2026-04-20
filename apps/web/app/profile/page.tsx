"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Briefcase,
  FileText,
  Loader2,
  MapPin,
  Plus,
  Sparkles,
  UserRound,
  X,
} from "lucide-react";

import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type ProfileForm = {
  full_name: string;
  phone: string;
  linkedin_url: string;
  github_url: string;
  current_city: string;
  current_state: string;
  work_auth_status: string;
  needs_sponsorship: boolean;
  willing_to_relocate: boolean;
  gender: string;
  // Distinct from gender — pronouns are NEVER inferred from gender.
  // Empty string = not set; the worker will escalate pronouns questions
  // to needs_review until the user explicitly chooses.
  pronouns: string;
  race: string;
  hispanic_ethnicity: boolean | null;
  veteran_status: string;
  disability_status: string;
};

type PrefsForm = {
  target_titles: string[];
  target_locations: string[];
  auto_apply_keywords: string[];
  licenses_certifications: string[];
  years_of_experience: string;
  seniority: string;
  salary_min_usd: string;
  salary_max_usd: string;
  start_availability: string;
  willing_background_check: boolean;
};

const EMPTY_PROFILE: ProfileForm = {
  full_name: "",
  phone: "",
  linkedin_url: "",
  github_url: "",
  current_city: "",
  current_state: "",
  work_auth_status: "",
  needs_sponsorship: false,
  willing_to_relocate: true,
  gender: "",
  pronouns: "",
  race: "",
  hispanic_ethnicity: null,
  veteran_status: "",
  disability_status: "",
};

const EMPTY_PREFS: PrefsForm = {
  target_titles: [],
  target_locations: [],
  auto_apply_keywords: [],
  licenses_certifications: [],
  years_of_experience: "",
  seniority: "any",
  salary_min_usd: "",
  salary_max_usd: "",
  start_availability: "immediately",
  willing_background_check: true,
};

const VALID_WORK_AUTH = ["us_citizen", "green_card", "h1b", "f1_opt", "f1_cpt", "other"];

export default function ProfilePage() {
  const ready = isSupabaseConfigured();
  const [profile, setProfile] = useState<ProfileForm>(EMPTY_PROFILE);
  const [prefs, setPrefs] = useState<PrefsForm>(EMPTY_PREFS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved">("idle");
  const [resumeName, setResumeName] = useState<string | null>(null);
  // Track when the last save landed so the user can SEE that their
  // changes are persisted (was previously a 1.5s pulse only).
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  // Saved-answer vault rows for the new "Your saved answers" section.
  type SavedAnswer = { id: string; question_text: string; answer_text: string; times_used: number; last_used_at: string | null };
  const [savedAnswers, setSavedAnswers] = useState<SavedAnswer[]>([]);
  const [deletingAnswerId, setDeletingAnswerId] = useState<string | null>(null);

  const profileTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prefsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load all data
  useEffect(() => {
    if (!ready) {
      setLoading(false);
      return;
    }
    (async () => {
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

      const [{ data: prof }, { data: prefData }, { data: resumes }, { data: answers }] = await Promise.all([
        supabase.from("profiles").select("*").eq("id", user.id).maybeSingle(),
        supabase.from("preferences").select("*").eq("user_id", user.id).maybeSingle(),
        supabase.from("resumes").select("file_name").eq("user_id", user.id).eq("is_primary", true).limit(1),
        // Answer-vault rows for the new "Your saved answers" section.
        // Most-recent first; cap at 50 for the visible list.
        supabase.from("answers").select("id, question_text, answer_text, times_used, last_used_at").eq("user_id", user.id).order("created_at", { ascending: false }).limit(50),
      ]);
      if (answers) setSavedAnswers(answers as SavedAnswer[]);

      if (prof) {
        setProfile({
          full_name: prof.full_name || "",
          phone: prof.phone || "",
          linkedin_url: prof.linkedin_url || "",
          github_url: prof.github_url || "",
          current_city: prof.current_city || "",
          current_state: prof.current_state || "",
          work_auth_status: prof.work_auth_status || "",
          needs_sponsorship: prof.needs_sponsorship ?? false,
          willing_to_relocate: prof.willing_to_relocate ?? true,
          gender: prof.gender || "",
          pronouns: prof.pronouns || "",
          race: prof.race || "",
          hispanic_ethnicity: prof.hispanic_ethnicity ?? null,
          veteran_status: prof.veteran_status || "",
          disability_status: prof.disability_status || "",
        });
      }

      if (prefData) {
        setPrefs({
          target_titles: prefData.target_titles || [],
          target_locations: prefData.target_locations || [],
          auto_apply_keywords: prefData.auto_apply_keywords || [],
          licenses_certifications: prefData.licenses_certifications || [],
          years_of_experience: prefData.years_of_experience != null ? String(prefData.years_of_experience) : "",
          seniority: prefData.seniority || "any",
          salary_min_usd: prefData.salary_min_usd != null ? String(prefData.salary_min_usd) : "",
          salary_max_usd: prefData.salary_max_usd != null ? String(prefData.salary_max_usd) : "",
          start_availability: prefData.start_availability || "immediately",
          willing_background_check: prefData.willing_background_check ?? true,
        });
      }

      if (resumes && resumes.length > 0) {
        setResumeName(resumes[0].file_name);
      }

      setLoading(false);
    })();
  }, [ready]);

  // Auto-save profile (800ms debounce)
  const persistProfile = useCallback((next: ProfileForm) => {
    if (profileTimer.current) clearTimeout(profileTimer.current);
    profileTimer.current = setTimeout(async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      setSaving("saving");
      const update: Record<string, unknown> = {
        full_name: next.full_name || null,
        phone: next.phone || null,
        linkedin_url: next.linkedin_url || null,
        github_url: next.github_url || null,
        current_city: next.current_city || null,
        current_state: next.current_state || null,
        needs_sponsorship: next.needs_sponsorship,
        willing_to_relocate: next.willing_to_relocate,
        gender: next.gender || null,
        pronouns: next.pronouns || null,
        race: next.race || null,
        hispanic_ethnicity: next.hispanic_ethnicity,
        veteran_status: next.veteran_status || null,
        disability_status: next.disability_status || null,
        updated_at: new Date().toISOString(),
      };
      if (VALID_WORK_AUTH.includes(next.work_auth_status)) {
        update.work_auth_status = next.work_auth_status;
      }
      await supabase.from("profiles").update(update).eq("id", user.id);
      setSaving("saved");
      setLastSavedAt(new Date());
      setTimeout(() => setSaving((s) => s === "saved" ? "idle" : s), 1500);
    }, 800);
  }, []);

  const persistPrefs = useCallback((next: PrefsForm) => {
    if (prefsTimer.current) clearTimeout(prefsTimer.current);
    prefsTimer.current = setTimeout(async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      setSaving("saving");
      await supabase.from("preferences").upsert({
        user_id: user.id,
        target_titles: next.target_titles,
        target_locations: next.target_locations,
        auto_apply_keywords: next.auto_apply_keywords,
        licenses_certifications: next.licenses_certifications,
        years_of_experience: next.years_of_experience ? parseInt(next.years_of_experience, 10) : null,
        seniority: next.seniority || "any",
        salary_min_usd: next.salary_min_usd ? parseInt(next.salary_min_usd, 10) : null,
        salary_max_usd: next.salary_max_usd ? parseInt(next.salary_max_usd, 10) : null,
        start_availability: next.start_availability,
        willing_background_check: next.willing_background_check,
        updated_at: new Date().toISOString(),
      });
      setSaving("saved");
      setLastSavedAt(new Date());
      setTimeout(() => setSaving((s) => s === "saved" ? "idle" : s), 1500);
    }, 800);
  }, []);

  const updateProfile = (patch: Partial<ProfileForm>) => {
    setProfile((prev) => {
      const next = { ...prev, ...patch };
      persistProfile(next);
      return next;
    });
  };

  const updatePrefs = (patch: Partial<PrefsForm>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      persistPrefs(next);
      return next;
    });
  };

  // Chip helpers
  const [titleDraft, setTitleDraft] = useState("");
  const [locDraft, setLocDraft] = useState("");
  const [kwDraft, setKwDraft] = useState("");
  const [licDraft, setLicDraft] = useState("");

  const addChip = (key: keyof PrefsForm, value: string, setDraft: (s: string) => void) => {
    const v = value.trim();
    if (!v) return;
    const list = prefs[key] as string[];
    if (list.includes(v)) return;
    updatePrefs({ [key]: [...list, v] } as Partial<PrefsForm>);
    setDraft("");
  };
  const removeChip = (key: keyof PrefsForm, value: string) => {
    const list = prefs[key] as string[];
    updatePrefs({ [key]: list.filter((x) => x !== value) } as Partial<PrefsForm>);
  };

  // Flush any pending debounced save and persist immediately. Wired
  // to the new "Save now" button so users who don't want to wait the
  // 800 ms auto-save window get an explicit confirmation moment.
  const saveNow = async () => {
    if (profileTimer.current) clearTimeout(profileTimer.current);
    if (prefsTimer.current) clearTimeout(prefsTimer.current);
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    setSaving("saving");
    const profileUpdate: Record<string, unknown> = {
      full_name: profile.full_name || null,
      phone: profile.phone || null,
      linkedin_url: profile.linkedin_url || null,
      github_url: profile.github_url || null,
      current_city: profile.current_city || null,
      current_state: profile.current_state || null,
      needs_sponsorship: profile.needs_sponsorship,
      willing_to_relocate: profile.willing_to_relocate,
      gender: profile.gender || null,
      pronouns: profile.pronouns || null,
      race: profile.race || null,
      hispanic_ethnicity: profile.hispanic_ethnicity,
      veteran_status: profile.veteran_status || null,
      disability_status: profile.disability_status || null,
      updated_at: new Date().toISOString(),
    };
    if (VALID_WORK_AUTH.includes(profile.work_auth_status)) {
      profileUpdate.work_auth_status = profile.work_auth_status;
    }
    await Promise.all([
      supabase.from("profiles").update(profileUpdate).eq("id", user.id),
      supabase.from("preferences").upsert({
        user_id: user.id,
        target_titles: prefs.target_titles,
        target_locations: prefs.target_locations,
        auto_apply_keywords: prefs.auto_apply_keywords,
        licenses_certifications: prefs.licenses_certifications,
        years_of_experience: prefs.years_of_experience ? parseInt(prefs.years_of_experience, 10) : null,
        seniority: prefs.seniority || "any",
        salary_min_usd: prefs.salary_min_usd ? parseInt(prefs.salary_min_usd, 10) : null,
        salary_max_usd: prefs.salary_max_usd ? parseInt(prefs.salary_max_usd, 10) : null,
        start_availability: prefs.start_availability,
        willing_background_check: prefs.willing_background_check,
        updated_at: new Date().toISOString(),
      }),
    ]);
    setSaving("saved");
    setLastSavedAt(new Date());
    setTimeout(() => setSaving((s) => s === "saved" ? "idle" : s), 1500);
  };

  // Delete a saved-answer-vault row. The agent will re-ask the
  // question on the next application that surfaces it (and the user
  // can save a new answer then).
  const deleteSavedAnswer = async (answerId: string) => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    setDeletingAnswerId(answerId);
    try {
      await supabase.from("answers").delete().eq("id", answerId);
      setSavedAnswers((rows) => rows.filter((r) => r.id !== answerId));
    } finally {
      setDeletingAnswerId(null);
    }
  };

  // Compute which "high-impact" fields are missing — these are the
  // ones that historically broke real applications (LinkedIn URL on
  // Wealthfront, phone on most Greenhouse forms, work auth on every
  // EEO-aware ATS, current city for location-screened roles). Pronouns
  // is intentionally NOT in this list — empty pronouns is a valid
  // "prefer not to say" choice and the worker handles it correctly.
  const missingCritical: { label: string; field: string }[] = [];
  if (!profile.full_name?.trim()) missingCritical.push({ label: "Full name", field: "full_name" });
  if (!profile.phone?.trim()) missingCritical.push({ label: "Phone number", field: "phone" });
  if (!profile.linkedin_url?.trim()) missingCritical.push({ label: "LinkedIn URL", field: "linkedin_url" });
  if (!profile.current_city?.trim()) missingCritical.push({ label: "Current city", field: "current_city" });
  if (!profile.work_auth_status?.trim()) missingCritical.push({ label: "Work authorization status", field: "work_auth_status" });
  if (!resumeName) missingCritical.push({ label: "Resume", field: "resume" });

  const fmtRelative = (d: Date | null): string => {
    if (!d) return "";
    const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
    if (sec < 5) return "just now";
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    return d.toLocaleString();
  };

  if (loading) {
    return (
      <ConsoleShell activePath="/profile" eyebrow="Profile" title="Your profile" description="">
        <section className="console-section">
          <div className="dashboard-loading">
            <Loader2 size={16} className="spin" /> Loading…
          </div>
        </section>
      </ConsoleShell>
    );
  }

  return (
    <ConsoleShell
      activePath="/profile"
      eyebrow="Profile"
      title="Your profile"
      description={
        saving === "saving" ? "Saving…" :
        saving === "saved" ? "All changes saved" :
        "Edit any field — changes save automatically."
      }
      actions={[{ href: "/dashboard", label: "Back to dashboard", variant: "secondary" }]}
    >
      {/* MISSING-INFO WARNING — applications likely fail without these */}
      {missingCritical.length > 0 && (
        <section className="console-section">
          <article
            className="glass auto-card"
            style={{
              border: "1px solid rgba(255, 153, 51, 0.35)",
              background: "rgba(255, 153, 51, 0.06)",
            }}
          >
            <header className="auto-card-head">
              <div>
                <p className="eyebrow" style={{ color: "#ff9933" }}>Heads up</p>
                <h3 style={{ marginBottom: 6 }}>
                  Applications might fail without these {missingCritical.length === 1 ? "field" : "fields"}
                </h3>
                <p className="auto-card-sub">
                  Most employer forms ask for these directly. Fill them now so the agent can submit cleanly without stopping for review:
                </p>
                <ul style={{ margin: "10px 0 0", paddingLeft: 20, fontSize: 13.5, lineHeight: 1.7 }}>
                  {missingCritical.map((m) => (
                    <li key={m.field}><strong>{m.label}</strong></li>
                  ))}
                </ul>
              </div>
            </header>
          </article>
        </section>
      )}

      {/* SAVE STATUS BAR — explicit "Save now" + last-saved timestamp */}
      <section className="console-section">
        <article
          className="glass"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            padding: "10px 14px",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 12,
            background: "rgba(255,255,255,0.03)",
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
            <span
              style={{
                display: "inline-block",
                width: 9,
                height: 9,
                borderRadius: 99,
                background:
                  saving === "saving" ? "#7caee5"
                  : saving === "saved" ? "#7adfa3"
                  : lastSavedAt ? "#7adfa3"
                  : "rgba(255,255,255,0.25)",
              }}
            />
            <span style={{ color: "var(--muted)" }}>
              {saving === "saving" && "Saving…"}
              {saving === "saved" && "Saved just now"}
              {saving === "idle" && lastSavedAt && `Saved ${fmtRelative(lastSavedAt)}`}
              {saving === "idle" && !lastSavedAt && "Changes save automatically"}
            </span>
          </div>
          <button
            type="button"
            className="btn-secondary auto-btn-sm"
            onClick={saveNow}
            disabled={saving === "saving"}
            title="Flush any pending edits and save right now"
          >
            {saving === "saving" ? "Saving…" : "Save now"}
          </button>
        </article>
      </section>

      {/* RESUME */}
      <section className="console-section">
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">Resume</p>
              <h3>{resumeName || "No resume uploaded"}</h3>
              <p className="auto-card-sub">
                Your resume is used to autofill applications. Upload a new one or replace it from the Documents page.
              </p>
            </div>
            <FileText size={18} />
          </header>
          <a href="/documents" className="btn-secondary" style={{ marginTop: 12, display: "inline-block" }}>
            Manage documents
          </a>
        </article>
      </section>

      {/* BASICS */}
      <section className="console-section">
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">Basics</p>
              <h3>Personal info</h3>
            </div>
            <UserRound size={18} />
          </header>

          <div className="wiz-field-grid">
            <label className="wiz-label">
              <span>Full name</span>
              <input value={profile.full_name} onChange={(e) => updateProfile({ full_name: e.target.value })} placeholder="Your full name" />
            </label>
            <label className="wiz-label">
              <span>Phone</span>
              <input value={profile.phone} onChange={(e) => updateProfile({ phone: e.target.value })} placeholder="+1 555 555 5555" />
            </label>
            <label className="wiz-label">
              <span>LinkedIn URL</span>
              <input value={profile.linkedin_url} onChange={(e) => updateProfile({ linkedin_url: e.target.value })} placeholder="https://linkedin.com/in/you" />
            </label>
            <label className="wiz-label">
              <span>GitHub URL <em>(optional)</em></span>
              <input value={profile.github_url} onChange={(e) => updateProfile({ github_url: e.target.value })} placeholder="https://github.com/you" />
            </label>
            <label className="wiz-label">
              <span>Current city</span>
              <input value={profile.current_city} onChange={(e) => updateProfile({ current_city: e.target.value })} placeholder="New York" />
            </label>
            <label className="wiz-label">
              <span>State</span>
              <input value={profile.current_state} onChange={(e) => updateProfile({ current_state: e.target.value })} placeholder="NY" />
            </label>
            <label className="wiz-label">
              <span>Work authorization</span>
              <select value={profile.work_auth_status} onChange={(e) => updateProfile({ work_auth_status: e.target.value })}>
                <option value="">Select…</option>
                <option value="us_citizen">US Citizen</option>
                <option value="green_card">Green Card</option>
                <option value="h1b">H-1B</option>
                <option value="f1_opt">F-1 OPT</option>
                <option value="f1_cpt">F-1 CPT</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Need sponsorship?</span>
              <select value={profile.needs_sponsorship ? "yes" : "no"} onChange={(e) => updateProfile({ needs_sponsorship: e.target.value === "yes" })}>
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Willing to relocate?</span>
              <select value={profile.willing_to_relocate ? "yes" : "no"} onChange={(e) => updateProfile({ willing_to_relocate: e.target.value === "yes" })}>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
          </div>
        </article>
      </section>

      {/* TARGETS */}
      <section className="console-section">
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">What you want</p>
              <h3>Target roles & locations</h3>
              <p className="auto-card-sub">
                The agent uses these to find matching jobs. Be specific.
              </p>
            </div>
            <Briefcase size={18} />
          </header>

          <div className="auto-field">
            <label>Target job titles</label>
            <div className="auto-chip-list">
              {prefs.target_titles.map((t) => (
                <span className="auto-chip auto-chip-active" key={t}>
                  {t}
                  <button type="button" onClick={() => removeChip("target_titles", t)} aria-label={`Remove ${t}`}>
                    <X size={11} />
                  </button>
                </span>
              ))}
              <div className="auto-chip-input">
                <input
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addChip("target_titles", titleDraft, setTitleDraft))}
                  placeholder="+ Add title"
                />
              </div>
            </div>
          </div>

          <div className="auto-field">
            <label>Target locations</label>
            <div className="auto-chip-list">
              {prefs.target_locations.map((l) => (
                <span className="auto-chip auto-chip-active" key={l}>
                  <MapPin size={11} style={{ marginRight: 2 }} />
                  {l}
                  <button type="button" onClick={() => removeChip("target_locations", l)} aria-label={`Remove ${l}`}>
                    <X size={11} />
                  </button>
                </span>
              ))}
              <div className="auto-chip-input">
                <input
                  value={locDraft}
                  onChange={(e) => setLocDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addChip("target_locations", locDraft, setLocDraft))}
                  placeholder="+ Add location"
                />
              </div>
            </div>
          </div>

          <div className="auto-field">
            <label>Search keywords <em style={{ color: "var(--muted)", fontStyle: "normal", fontWeight: 400, fontSize: 12 }}>(refines what the agent looks for)</em></label>
            <div className="auto-chip-list">
              {prefs.auto_apply_keywords.map((k) => (
                <span className="auto-chip auto-chip-active" key={k}>
                  {k}
                  <button type="button" onClick={() => removeChip("auto_apply_keywords", k)} aria-label={`Remove ${k}`}>
                    <X size={11} />
                  </button>
                </span>
              ))}
              <div className="auto-chip-input">
                <input
                  value={kwDraft}
                  onChange={(e) => setKwDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addChip("auto_apply_keywords", kwDraft, setKwDraft))}
                  placeholder="+ Add keyword (e.g. remote, hospital, startup)"
                />
              </div>
            </div>
          </div>
        </article>
      </section>

      {/* SCREENING ANSWERS */}
      <section className="console-section">
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">Screening answers</p>
              <h3>Common application questions</h3>
              <p className="auto-card-sub">
                Answer these once — Instaply auto-fills them on every supported application form.
              </p>
            </div>
            <Sparkles size={18} />
          </header>

          <div className="wiz-field-grid">
            <label className="wiz-label">
              <span>Years of experience</span>
              <input type="number" min="0" max="50" value={prefs.years_of_experience} onChange={(e) => updatePrefs({ years_of_experience: e.target.value })} placeholder="e.g. 3" />
            </label>
            <label className="wiz-label">
              <span>Seniority level</span>
              <select value={prefs.seniority} onChange={(e) => updatePrefs({ seniority: e.target.value })}>
                <option value="any">Any level</option>
                <option value="entry">Entry level (0–2 yrs)</option>
                <option value="mid">Mid-career (3–6 yrs)</option>
                <option value="senior">Senior (7+ yrs)</option>
                <option value="staff_plus">Staff / Principal+</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Start availability</span>
              <select value={prefs.start_availability} onChange={(e) => updatePrefs({ start_availability: e.target.value })}>
                <option value="immediately">Immediately</option>
                <option value="2_weeks">In 2 weeks</option>
                <option value="1_month">In 1 month</option>
                <option value="flexible">Flexible</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Salary expectation — minimum ($)</span>
              <input type="number" min="0" value={prefs.salary_min_usd} onChange={(e) => updatePrefs({ salary_min_usd: e.target.value })} placeholder="80000" />
            </label>
            <label className="wiz-label">
              <span>Salary expectation — maximum ($)</span>
              <input type="number" min="0" value={prefs.salary_max_usd} onChange={(e) => updatePrefs({ salary_max_usd: e.target.value })} placeholder="120000" />
            </label>
            <label className="wiz-label">
              <span>Willing to undergo background check?</span>
              <select value={prefs.willing_background_check ? "yes" : "no"} onChange={(e) => updatePrefs({ willing_background_check: e.target.value === "yes" })}>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
          </div>

          <div className="auto-field" style={{ marginTop: 18 }}>
            <label>Licenses & certifications</label>
            <div className="auto-chip-list">
              {prefs.licenses_certifications.map((l) => (
                <span className="auto-chip auto-chip-active" key={l}>
                  {l}
                  <button type="button" onClick={() => removeChip("licenses_certifications", l)} aria-label={`Remove ${l}`}>
                    <X size={11} />
                  </button>
                </span>
              ))}
              <div className="auto-chip-input">
                <input
                  value={licDraft}
                  onChange={(e) => setLicDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addChip("licenses_certifications", licDraft, setLicDraft))}
                  placeholder="+ Add (e.g. CFA, PMP, RN)"
                />
              </div>
            </div>
          </div>
        </article>
      </section>

      {/* EEO */}
      <section className="console-section">
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">EEO information</p>
              <h3>Voluntary self-identification</h3>
              <p className="auto-card-sub">
                All optional. Stored securely. Submitted only when an application asks.
              </p>
            </div>
            <UserRound size={18} />
          </header>

          <div className="wiz-field-grid">
            <label className="wiz-label">
              <span>Gender <em>(optional)</em></span>
              <select value={profile.gender} onChange={(e) => updateProfile({ gender: e.target.value })}>
                <option value="">Prefer not to say</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="non_binary">Non-binary</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Pronouns <em>(optional, distinct from gender)</em></span>
              <select value={profile.pronouns} onChange={(e) => updateProfile({ pronouns: e.target.value })}>
                <option value="">Prefer not to say</option>
                <option value="she/her">she / her</option>
                <option value="he/him">he / him</option>
                <option value="they/them">they / them</option>
                <option value="she/they">she / they</option>
                <option value="he/they">he / they</option>
                <option value="any pronouns">any pronouns</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Race / ethnicity <em>(optional)</em></span>
              <select value={profile.race} onChange={(e) => updateProfile({ race: e.target.value })}>
                <option value="">Prefer not to say</option>
                <option value="asian">Asian</option>
                <option value="black">Black or African American</option>
                <option value="hispanic">Hispanic or Latino</option>
                <option value="native_american">Native American / Alaska Native</option>
                <option value="pacific_islander">Native Hawaiian / Pacific Islander</option>
                <option value="white">White</option>
                <option value="two_or_more">Two or more races</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Hispanic / Latino? <em>(optional)</em></span>
              <select
                value={profile.hispanic_ethnicity === null ? "" : profile.hispanic_ethnicity ? "yes" : "no"}
                onChange={(e) => updateProfile({ hispanic_ethnicity: e.target.value === "" ? null : e.target.value === "yes" })}
              >
                <option value="">Prefer not to say</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Veteran status <em>(optional)</em></span>
              <select value={profile.veteran_status} onChange={(e) => updateProfile({ veteran_status: e.target.value })}>
                <option value="">Prefer not to say</option>
                <option value="not_veteran">I am not a veteran</option>
                <option value="veteran">I am a veteran</option>
                <option value="active_duty">Active duty / National Guard</option>
              </select>
            </label>
            <label className="wiz-label">
              <span>Disability status <em>(optional)</em></span>
              <select value={profile.disability_status} onChange={(e) => updateProfile({ disability_status: e.target.value })}>
                <option value="">Prefer not to say</option>
                <option value="no_disability">I do not have a disability</option>
                <option value="has_disability">I have a disability</option>
              </select>
            </label>
          </div>
        </article>
      </section>

      {/* SAVED ANSWERS — read + delete the answer-vault rows the
          worker reuses across applications. New section so users can
          actually see what's been remembered (was previously
          invisible). Edits aren't supported here — to change an answer
          the user can delete the row, and the agent will re-ask the
          question on the next application that surfaces it. */}
      <section className="console-section">
        <article className="glass auto-card">
          <header className="auto-card-head">
            <div>
              <p className="eyebrow">Saved answers</p>
              <h3>What the agent remembers from past applications</h3>
              <p className="auto-card-sub">
                Every time you answer a screening question, we save it here so the agent can reuse it on future applications without asking you again. Delete a row to be re-asked next time.
              </p>
            </div>
          </header>
          {savedAnswers.length === 0 ? (
            <p style={{ margin: "16px 0 0", fontSize: 13, color: "var(--muted)" }}>
              No saved answers yet. They&apos;ll appear here as you answer review questions on the dashboard.
            </p>
          ) : (
            <ul style={{ margin: "16px 0 0", padding: 0, listStyle: "none", display: "grid", gap: 10 }}>
              {savedAnswers.map((a) => (
                <li
                  key={a.id}
                  style={{
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 10,
                    padding: 12,
                    background: "rgba(255,255,255,0.03)",
                    display: "flex",
                    gap: 12,
                    alignItems: "flex-start",
                    flexWrap: "wrap",
                  }}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 4 }}>
                      {a.question_text}
                    </div>
                    <div style={{ fontSize: 14, color: "#e9eaee", wordBreak: "break-word" }}>
                      {a.answer_text}
                    </div>
                    {(a.times_used > 0 || a.last_used_at) && (
                      <div style={{ marginTop: 4, fontSize: 11, color: "#7adfa3" }}>
                        Reused {a.times_used}× {a.last_used_at ? `· last ${fmtRelative(new Date(a.last_used_at))}` : ""}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    className="btn-secondary auto-btn-sm"
                    disabled={deletingAnswerId === a.id}
                    onClick={() => deleteSavedAnswer(a.id)}
                    style={{ flexShrink: 0 }}
                  >
                    {deletingAnswerId === a.id ? "Deleting…" : "Delete"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </article>
      </section>
    </ConsoleShell>
  );
}
