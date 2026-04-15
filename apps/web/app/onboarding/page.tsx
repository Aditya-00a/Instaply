"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Briefcase,
  Check,
  CircleAlert,
  CircleCheck,
  CircleX,
  FileUp,
  Loader2,
  MapPin,
  Sparkles,
  Upload,
  UserRound,
  X,
} from "lucide-react";

import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";
import { extractPdfText, scoreResumeText, type AtsReport } from "../lib/ats-score";

type Step = 1 | 2 | 3;

type WorkAuth = "citizen" | "green_card" | "h1b" | "opt" | "other";

type Identity = {
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  linkedinUrl: string;
  githubUrl: string;
  city: string;
  state: string;
  workAuth: WorkAuth;
  needsSponsorship: boolean;
};

const SUGGESTED_ROLES = [
  "Software Engineer",
  "Product Manager",
  "Data Analyst",
  "Business Analyst",
  "Risk Analyst",
  "Marketing Manager",
  "Operations Associate",
  "Strategy Analyst",
  "Designer",
];

const SUGGESTED_LOCATIONS = [
  "New York, NY",
  "San Francisco, CA",
  "Remote",
  "Los Angeles, CA",
  "Chicago, IL",
  "Boston, MA",
  "Austin, TX",
  "Seattle, WA",
];

const EMPTY_IDENTITY: Identity = {
  firstName: "",
  lastName: "",
  email: "",
  phone: "",
  linkedinUrl: "",
  githubUrl: "",
  city: "",
  state: "",
  workAuth: "citizen",
  needsSponsorship: false,
};

export default function OnboardingPage() {
  const router = useRouter();
  const ready = isSupabaseConfigured();
  const [step, setStep] = useState<Step>(1);

  // Step 1 state
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [report, setReport] = useState<AtsReport | null>(null);
  const [scoring, setScoring] = useState(false);

  // Step 2 state
  const [identity, setIdentity] = useState<Identity>(EMPTY_IDENTITY);

  // Step 3 state
  const [targetRoles, setTargetRoles] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [roleDraft, setRoleDraft] = useState("");
  const [locDraft, setLocDraft] = useState("");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [doneBanner, setDoneBanner] = useState(false);

  // Pre-hydrate from Supabase profile (if user has saved before)
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return;

      const { data } = await supabase
        .from("profiles")
        .select(
          "full_name, phone, linkedin_url, github_url, current_city, current_state, work_auth_status, needs_sponsorship, email"
        )
        .eq("id", user.id)
        .single();
      if (!data || cancelled) return;

      const parts = (data.full_name || "").split(" ");
      setIdentity((prev) => ({
        ...prev,
        firstName: parts[0] || "",
        lastName: parts.slice(1).join(" ") || "",
        email: data.email || user.email || "",
        phone: data.phone || "",
        linkedinUrl: data.linkedin_url || "",
        githubUrl: data.github_url || "",
        city: data.current_city || "",
        state: data.current_state || "",
        workAuth: (data.work_auth_status as WorkAuth) || "citizen",
        needsSponsorship: !!data.needs_sponsorship,
      }));
    })();
    return () => {
      cancelled = true;
    };
  }, [ready]);

  // Resume upload + parse
  const uploadAndParse = async (file: File) => {
    setUploadError(null);
    if (file.size > 10 * 1024 * 1024) {
      setUploadError("Resume must be under 10 MB.");
      return;
    }
    setResumeFile(file);

    // Parse client-side for auto-fill even when not signed in
    if (file.type === "application/pdf") {
      setScoring(true);
      try {
        const { text, pageCount } = await extractPdfText(file);
        const ats = scoreResumeText(text, pageCount);
        setReport(ats);
        autoFillFromText(text);
      } catch (e) {
        console.warn("parse failed", e);
      } finally {
        setScoring(false);
      }
    }

    // Upload to Supabase if signed in
    if (!ready) return;
    const supabase = getBrowserSupabase();
    if (!supabase) return;

    setUploading(true);
    try {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setUploadError("Please sign in first.");
        return;
      }

      const path = `${user.id}/${Date.now()}-${file.name}`;
      const { error: uploadErr } = await supabase.storage
        .from("resumes")
        .upload(path, file, { upsert: false, contentType: file.type });
      if (uploadErr) throw uploadErr;

      await supabase.from("resumes").insert({
        user_id: user.id,
        storage_path: path,
        file_name: file.name,
        file_size_bytes: file.size,
        is_primary: true,
      });
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const autoFillFromText = (text: string) => {
    // Email
    const emailMatch = text.match(/[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/i);
    // Phone
    const phoneMatch = text.match(
      /(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}/
    );
    // LinkedIn
    const liMatch = text.match(/linkedin\.com\/in\/[a-z0-9_-]+/i);
    // Name — first two capitalized words at top of resume
    const firstLine = text.split("\n").find((l) => l.trim().length > 0) || "";
    const nameMatch = firstLine.match(/^([A-Z][a-z]+)\s+([A-Z][a-z]+)/);

    setIdentity((prev) => ({
      ...prev,
      email: prev.email || emailMatch?.[0] || "",
      phone: prev.phone || phoneMatch?.[0] || "",
      linkedinUrl:
        prev.linkedinUrl ||
        (liMatch ? `https://${liMatch[0]}` : ""),
      firstName: prev.firstName || nameMatch?.[1] || "",
      lastName: prev.lastName || nameMatch?.[2] || "",
    }));
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) uploadAndParse(f);
    e.target.value = "";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f) uploadAndParse(f);
  };

  const addRole = (v: string) => {
    const s = v.trim();
    if (!s) return;
    if (targetRoles.includes(s)) return;
    setTargetRoles([...targetRoles, s]);
    setRoleDraft("");
  };

  const addLocation = (v: string) => {
    const s = v.trim();
    if (!s) return;
    if (locations.includes(s)) return;
    setLocations([...locations, s]);
    setLocDraft("");
  };

  const canAdvance1 = !!resumeFile || !ready; // resume optional in demo
  const canAdvance2 =
    identity.firstName.trim().length > 0 && identity.email.trim().length > 0;

  const finish = async () => {
    setSaveError(null);
    setSaving(true);

    if (!ready) {
      setDoneBanner(true);
      setTimeout(() => router.push("/dashboard"), 1400);
      return;
    }

    const supabase = getBrowserSupabase();
    if (!supabase) {
      setSaveError("Auth unavailable.");
      setSaving(false);
      return;
    }

    try {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) throw new Error("Not signed in.");

      const fullName =
        [identity.firstName, identity.lastName].filter(Boolean).join(" ") ||
        null;

      const { error: pErr } = await supabase
        .from("profiles")
        .update({
          full_name: fullName,
          phone: identity.phone || null,
          linkedin_url: identity.linkedinUrl || null,
          github_url: identity.githubUrl || null,
          current_city: identity.city || null,
          current_state: identity.state || null,
          current_country: "US",
          work_auth_status: identity.workAuth,
          needs_sponsorship: identity.needsSponsorship,
          updated_at: new Date().toISOString(),
        })
        .eq("id", user.id);
      if (pErr) throw pErr;

      // Upsert preferences row
      await supabase
        .from("preferences")
        .upsert({
          user_id: user.id,
          target_titles: targetRoles,
          target_locations: locations,
          updated_at: new Date().toISOString(),
        });

      setDoneBanner(true);
      setTimeout(() => router.push("/dashboard"), 1400);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed.");
      setSaving(false);
    }
  };

  return (
    <ConsoleShell
      activePath="/onboarding"
      eyebrow="Setup"
      title="Welcome to Instaply"
      description="Three quick steps. Under two minutes. You can refine everything later from Settings."
      actions={[{ href: "/settings", label: "Advanced settings", variant: "secondary" }]}
    >
      <section className="console-section">
        {/* Progress bar */}
        <div className="wiz-progress">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className={`wiz-step${step === n ? " wiz-step-active" : ""}${step > n ? " wiz-step-done" : ""}`}
            >
              <span className="wiz-step-num">{step > n ? <Check size={14} /> : n}</span>
              <span className="wiz-step-label">
                {n === 1 ? "Upload resume" : n === 2 ? "Confirm basics" : "Targets"}
              </span>
            </div>
          ))}
        </div>

        <article className="wiz-card">
          {step === 1 && (
            <>
              <header className="wiz-head">
                <div className="wiz-head-ico"><FileUp size={22} /></div>
                <div>
                  <h2>Upload your resume</h2>
                  <p>
                    We&apos;ll auto-fill your basics in the next step and
                    score it for ATS-friendliness.
                  </p>
                </div>
              </header>

              <label
                className={`wiz-drop${uploading ? " wiz-drop-busy" : ""}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={onDrop}
              >
                <input
                  type="file"
                  accept=".pdf,.doc,.docx,application/pdf"
                  onChange={onFileChange}
                  hidden
                  disabled={uploading}
                />
                <div className="wiz-drop-ico">
                  {uploading || scoring ? <Loader2 size={26} className="spin" /> : <Upload size={26} />}
                </div>
                <div>
                  <strong>
                    {uploading
                      ? "Uploading…"
                      : scoring
                      ? "Analyzing…"
                      : resumeFile
                      ? resumeFile.name
                      : "Drop your resume here or click to select"}
                  </strong>
                  <span>PDF or DOCX, max 10 MB</span>
                </div>
              </label>

              {uploadError && <div className="wiz-error">{uploadError}</div>}

              {report && (
                <div className="wiz-ats-summary">
                  <div
                    className={`wiz-ats-badge${
                      report.grade === "A" || report.grade === "B"
                        ? " wiz-ats-good"
                        : report.grade === "C"
                        ? " wiz-ats-ok"
                        : " wiz-ats-bad"
                    }`}
                  >
                    <span className="wiz-ats-num">{report.score}</span>
                    <span className="wiz-ats-label">ATS score</span>
                  </div>
                  <div className="wiz-ats-checks">
                    {report.checks.slice(0, 4).map((c) => (
                      <div key={c.id} className={`wiz-ats-check wiz-ats-check-${c.status}`}>
                        {c.status === "pass" ? (
                          <CircleCheck size={14} />
                        ) : c.status === "warn" ? (
                          <CircleAlert size={14} />
                        ) : (
                          <CircleX size={14} />
                        )}
                        <span>{c.title}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <footer className="wiz-foot">
                <div />
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => setStep(2)}
                  disabled={!canAdvance1 || uploading}
                >
                  Continue
                  <ArrowRight size={14} />
                </button>
              </footer>

              <p className="wiz-skip">
                <button type="button" onClick={() => setStep(2)}>
                  Skip for now
                </button>
                {" · "}You can always upload later from Settings.
              </p>
            </>
          )}

          {step === 2 && (
            <>
              <header className="wiz-head">
                <div className="wiz-head-ico"><UserRound size={22} /></div>
                <div>
                  <h2>Confirm your basics</h2>
                  <p>We pre-filled what we could. Tweak anything that looks off.</p>
                </div>
              </header>

              <div className="wiz-form-grid">
                <label className="wiz-field">
                  <span>First name</span>
                  <input
                    value={identity.firstName}
                    onChange={(e) => setIdentity({ ...identity, firstName: e.target.value })}
                    required
                  />
                </label>
                <label className="wiz-field">
                  <span>Last name</span>
                  <input
                    value={identity.lastName}
                    onChange={(e) => setIdentity({ ...identity, lastName: e.target.value })}
                  />
                </label>
                <label className="wiz-field wiz-field-span-2">
                  <span>Email</span>
                  <input
                    type="email"
                    value={identity.email}
                    onChange={(e) => setIdentity({ ...identity, email: e.target.value })}
                    required
                  />
                </label>
                <label className="wiz-field">
                  <span>Phone</span>
                  <input
                    value={identity.phone}
                    onChange={(e) => setIdentity({ ...identity, phone: e.target.value })}
                    placeholder="+1 (555) 555-5555"
                  />
                </label>
                <label className="wiz-field">
                  <span>LinkedIn</span>
                  <input
                    value={identity.linkedinUrl}
                    onChange={(e) => setIdentity({ ...identity, linkedinUrl: e.target.value })}
                    placeholder="https://linkedin.com/in/..."
                  />
                </label>
                <label className="wiz-field">
                  <span>City</span>
                  <input
                    value={identity.city}
                    onChange={(e) => setIdentity({ ...identity, city: e.target.value })}
                    placeholder="New York"
                  />
                </label>
                <label className="wiz-field">
                  <span>State</span>
                  <input
                    value={identity.state}
                    onChange={(e) => setIdentity({ ...identity, state: e.target.value })}
                    placeholder="NY"
                  />
                </label>
                <div className="wiz-field wiz-field-span-2">
                  <span>Work authorization</span>
                  <div className="wiz-radio-row">
                    {[
                      { v: "citizen", l: "US Citizen" },
                      { v: "green_card", l: "Green card" },
                      { v: "h1b", l: "H-1B" },
                      { v: "opt", l: "OPT / CPT" },
                      { v: "other", l: "Other" },
                    ].map((o) => (
                      <button
                        type="button"
                        key={o.v}
                        className={`wiz-radio${identity.workAuth === o.v ? " wiz-radio-active" : ""}`}
                        onClick={() =>
                          setIdentity({
                            ...identity,
                            workAuth: o.v as WorkAuth,
                            needsSponsorship: o.v === "h1b" || o.v === "opt",
                          })
                        }
                      >
                        {o.l}
                      </button>
                    ))}
                  </div>
                </div>
                <label className="wiz-checkbox wiz-field-span-2">
                  <input
                    type="checkbox"
                    checked={identity.needsSponsorship}
                    onChange={(e) => setIdentity({ ...identity, needsSponsorship: e.target.checked })}
                  />
                  <span>I&apos;ll need visa sponsorship for long-term employment</span>
                </label>
              </div>

              <footer className="wiz-foot">
                <button type="button" className="btn-secondary" onClick={() => setStep(1)}>
                  <ArrowLeft size={14} />
                  Back
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => setStep(3)}
                  disabled={!canAdvance2}
                >
                  Continue
                  <ArrowRight size={14} />
                </button>
              </footer>
            </>
          )}

          {step === 3 && (
            <>
              <header className="wiz-head">
                <div className="wiz-head-ico"><Sparkles size={22} /></div>
                <div>
                  <h2>Where do you want to work?</h2>
                  <p>
                    Add target roles and locations. We&apos;ll match open
                    positions against these and surface strong fits.
                  </p>
                </div>
              </header>

              <div className="wiz-tag-block">
                <div className="wiz-tag-label">
                  <Briefcase size={14} />
                  Target roles
                </div>
                <div className="wiz-tag-list">
                  {targetRoles.map((r) => (
                    <span className="wiz-tag" key={r}>
                      {r}
                      <button
                        type="button"
                        onClick={() => setTargetRoles(targetRoles.filter((x) => x !== r))}
                        aria-label={`Remove ${r}`}
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="wiz-tag-input-row">
                  <input
                    value={roleDraft}
                    onChange={(e) => setRoleDraft(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addRole(roleDraft))}
                    placeholder="e.g. Software Engineer"
                  />
                  <button type="button" className="btn-secondary" onClick={() => addRole(roleDraft)}>
                    Add
                  </button>
                </div>
                <div className="wiz-suggestion-row">
                  {SUGGESTED_ROLES.filter((r) => !targetRoles.includes(r)).slice(0, 6).map((r) => (
                    <button type="button" key={r} className="wiz-suggestion" onClick={() => addRole(r)}>
                      + {r}
                    </button>
                  ))}
                </div>
              </div>

              <div className="wiz-tag-block">
                <div className="wiz-tag-label">
                  <MapPin size={14} />
                  Locations
                </div>
                <div className="wiz-tag-list">
                  {locations.map((l) => (
                    <span className="wiz-tag" key={l}>
                      {l}
                      <button
                        type="button"
                        onClick={() => setLocations(locations.filter((x) => x !== l))}
                        aria-label={`Remove ${l}`}
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="wiz-tag-input-row">
                  <input
                    value={locDraft}
                    onChange={(e) => setLocDraft(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addLocation(locDraft))}
                    placeholder="e.g. New York, NY or Remote"
                  />
                  <button type="button" className="btn-secondary" onClick={() => addLocation(locDraft)}>
                    Add
                  </button>
                </div>
                <div className="wiz-suggestion-row">
                  {SUGGESTED_LOCATIONS.filter((l) => !locations.includes(l)).slice(0, 6).map((l) => (
                    <button type="button" key={l} className="wiz-suggestion" onClick={() => addLocation(l)}>
                      + {l}
                    </button>
                  ))}
                </div>
              </div>

              {saveError && <div className="wiz-error">{saveError}</div>}
              {doneBanner && (
                <div className="wiz-done">
                  <Check size={16} />
                  All set — redirecting to your dashboard…
                </div>
              )}

              <footer className="wiz-foot">
                <button type="button" className="btn-secondary" onClick={() => setStep(2)}>
                  <ArrowLeft size={14} />
                  Back
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={finish}
                  disabled={saving}
                >
                  {saving ? "Saving…" : "Finish setup"}
                  <ArrowRight size={14} />
                </button>
              </footer>
            </>
          )}
        </article>

        <p className="wiz-hint">
          Need to tweak something deeper — resume templates, cover letter
          tone, automation rules? <Link href="/settings">Open advanced
          settings</Link>.
        </p>
      </section>
    </ConsoleShell>
  );
}
