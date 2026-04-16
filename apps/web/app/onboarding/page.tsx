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
import { extractPdfText, extractDocxText, scoreResumeText, type AtsReport } from "../lib/ats-score";

type Step = 1 | 2 | 3 | 4;

type WorkAuth = "us_citizen" | "green_card" | "h1b" | "f1_opt" | "other";

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
  workAuth: "us_citizen",
  needsSponsorship: false,
};

export default function OnboardingPage() {
  const router = useRouter();
  const ready = isSupabaseConfigured();
  const [step, setStep] = useState<Step>(1);

  // Step 1 state
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [existingResume, setExistingResume] = useState<string | null>(null);
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

  // Step 4 state — EEO + screening
  const [gender, setGender] = useState("");
  const [race, setRace] = useState("");
  const [hispanicEthnicity, setHispanicEthnicity] = useState<boolean | null>(null);
  const [veteranStatus, setVeteranStatus] = useState("");
  const [disabilityStatus, setDisabilityStatus] = useState("");
  const [licenseCerts, setLicenseCerts] = useState("");
  const [yearsExp, setYearsExp] = useState("");
  const [salaryMin, setSalaryMin] = useState("");
  const [salaryMax, setSalaryMax] = useState("");
  const [startAvailability, setStartAvailability] = useState("immediately");
  const [willingBackgroundCheck, setWillingBackgroundCheck] = useState(true);
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

      const [{ data }, { data: resumeData }] = await Promise.all([
        supabase
          .from("profiles")
          .select(
            "full_name, phone, linkedin_url, github_url, current_city, current_state, work_auth_status, needs_sponsorship, email"
          )
          .eq("id", user.id)
          .single(),
        supabase
          .from("resumes")
          .select("file_name")
          .eq("user_id", user.id)
          .order("created_at", { ascending: false })
          .limit(1),
      ]);
      if (cancelled) return;

      // Show existing resume if one exists
      if (resumeData && resumeData.length > 0) {
        setExistingResume(resumeData[0].file_name);
      }

      if (!data) return;

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

    // Parse client-side for auto-fill + ATS scoring (PDF and DOCX)
    const isPdf = file.type === "application/pdf" || file.name.endsWith(".pdf");
    const isDocx =
      file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
      file.name.endsWith(".docx") ||
      file.name.endsWith(".doc");

    if (isPdf || isDocx) {
      setScoring(true);
      try {
        let text: string;
        let pageCount: number | null = null;

        if (isPdf) {
          const result = await extractPdfText(file);
          text = result.text;
          pageCount = result.pageCount;
        } else {
          const result = await extractDocxText(file);
          text = result.text;
        }

        const ats = scoreResumeText(text, pageCount);
        setReport(ats);
        autoFillFromText(text);
      } catch (e) {
        console.warn("Resume parsing failed:", e);
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

      // Clear existing primary so the unique index doesn't conflict
      await supabase
        .from("resumes")
        .update({ is_primary: false })
        .eq("user_id", user.id)
        .eq("is_primary", true);

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

  const canAdvance1 = !!resumeFile || !!existingResume || !ready;
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

      // Only include work_auth_status if it's a valid enum value
      const validWorkAuth = ["us_citizen", "green_card", "h1b", "f1_opt", "f1_cpt", "other"];
      const profileUpdate: Record<string, unknown> = {
        full_name: fullName,
        phone: identity.phone || null,
        linkedin_url: identity.linkedinUrl || null,
        github_url: identity.githubUrl || null,
        current_city: identity.city || null,
        current_state: identity.state || null,
        current_country: "US",
        needs_sponsorship: identity.needsSponsorship,
        updated_at: new Date().toISOString(),
      };
      if (validWorkAuth.includes(identity.workAuth)) {
        profileUpdate.work_auth_status = identity.workAuth;
      }

      // Add EEO fields (only if user filled them in)
      if (gender) profileUpdate.gender = gender;
      if (race) profileUpdate.race = race;
      if (hispanicEthnicity !== null) profileUpdate.hispanic_ethnicity = hispanicEthnicity;
      if (veteranStatus) profileUpdate.veteran_status = veteranStatus;
      if (disabilityStatus) profileUpdate.disability_status = disabilityStatus;

      const { error: pErr } = await supabase
        .from("profiles")
        .update(profileUpdate)
        .eq("id", user.id);
      if (pErr) throw pErr;

      // Upsert preferences row (includes screening question answers)
      const prefData: Record<string, unknown> = {
          user_id: user.id,
          target_titles: targetRoles,
          target_locations: locations,
          start_availability: startAvailability,
          willing_background_check: willingBackgroundCheck,
          updated_at: new Date().toISOString(),
      };
      if (licenseCerts.trim()) prefData.licenses_certifications = licenseCerts.split(",").map((s: string) => s.trim()).filter(Boolean);
      if (yearsExp) prefData.years_of_experience = parseInt(yearsExp, 10);
      if (salaryMin) prefData.salary_min_usd = parseInt(salaryMin, 10);
      if (salaryMax) prefData.salary_max_usd = parseInt(salaryMax, 10);

      await supabase
        .from("preferences")
        .upsert(prefData);

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
      description="Four quick steps. Under three minutes. You can refine everything later from Settings."
      actions={[{ href: "/settings", label: "Advanced settings", variant: "secondary" }]}
    >
      <section className="console-section">
        {/* Progress bar */}
        <div className="wiz-progress">
          {[1, 2, 3, 4].map((n) => (
            <div
              key={n}
              className={`wiz-step${step === n ? " wiz-step-active" : ""}${step > n ? " wiz-step-done" : ""}`}
            >
              <span className="wiz-step-num">{step > n ? <Check size={14} /> : n}</span>
              <span className="wiz-step-label">
                {n === 1 ? "Upload resume" : n === 2 ? "Confirm basics" : n === 3 ? "Targets" : "EEO & screening"}
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

              {existingResume && !resumeFile && (
                <div className="wiz-existing-resume">
                  <FileUp size={18} />
                  <div>
                    <strong>Resume on file: {existingResume}</strong>
                    <span>Already uploaded. Drop a new one below to replace it, or continue.</span>
                  </div>
                </div>
              )}

              <label
                className={`wiz-drop${uploading ? " wiz-drop-busy" : ""}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={onDrop}
              >
                <input
                  type="file"
                  accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
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
                      : existingResume
                      ? "Drop a new resume to replace"
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
                      { v: "us_citizen", l: "US Citizen" },
                      { v: "green_card", l: "Green card" },
                      { v: "h1b", l: "H-1B" },
                      { v: "f1_opt", l: "OPT / CPT" },
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
                            needsSponsorship: o.v === "h1b" || o.v === "f1_opt",
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
                  onClick={() => setStep(4)}
                >
                  Next
                  <ArrowRight size={14} />
                </button>
              </footer>
            </>
          )}

          {step === 4 && (
            <>
              <header className="wiz-head">
                <div className="wiz-head-ico"><UserRound size={22} /></div>
                <div>
                  <h2>EEO & screening questions</h2>
                  <p>
                    Optional but saves time — these answers auto-fill across every
                    application so you never re-type them.
                  </p>
                </div>
              </header>

              <div className="wiz-field-grid">
                <label className="wiz-label">
                  <span>Gender <em>(optional)</em></span>
                  <select value={gender} onChange={(e) => setGender(e.target.value)}>
                    <option value="">Prefer not to say</option>
                    <option value="male">Male</option>
                    <option value="female">Female</option>
                    <option value="non_binary">Non-binary</option>
                    <option value="other">Other</option>
                  </select>
                </label>

                <label className="wiz-label">
                  <span>Race / ethnicity <em>(optional)</em></span>
                  <select value={race} onChange={(e) => setRace(e.target.value)}>
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
                  <select value={hispanicEthnicity === null ? "" : hispanicEthnicity ? "yes" : "no"} onChange={(e) => setHispanicEthnicity(e.target.value === "" ? null : e.target.value === "yes")}>
                    <option value="">Prefer not to say</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </label>

                <label className="wiz-label">
                  <span>Veteran status <em>(optional)</em></span>
                  <select value={veteranStatus} onChange={(e) => setVeteranStatus(e.target.value)}>
                    <option value="">Prefer not to say</option>
                    <option value="not_veteran">I am not a veteran</option>
                    <option value="veteran">I am a veteran</option>
                    <option value="active_duty">Active duty / National Guard</option>
                  </select>
                </label>

                <label className="wiz-label">
                  <span>Disability status <em>(optional)</em></span>
                  <select value={disabilityStatus} onChange={(e) => setDisabilityStatus(e.target.value)}>
                    <option value="">Prefer not to say</option>
                    <option value="no_disability">I do not have a disability</option>
                    <option value="has_disability">I have a disability</option>
                  </select>
                </label>
              </div>

              <hr className="wiz-divider" />

              <h3 className="wiz-sub-heading">Common screening questions</h3>
              <p className="wiz-sub-desc">
                Answer these once — Instaply fills them in automatically on
                every supported application form.
              </p>

              <div className="wiz-field-grid">
                <label className="wiz-label">
                  <span>Years of professional experience</span>
                  <input type="number" min="0" max="50" value={yearsExp} onChange={(e) => setYearsExp(e.target.value)} placeholder="e.g. 3" />
                </label>

                <label className="wiz-label">
                  <span>Licenses or certifications</span>
                  <input value={licenseCerts} onChange={(e) => setLicenseCerts(e.target.value)} placeholder="e.g. CFA, PMP, CPA, Series 7 (or leave blank)" />
                </label>

                <label className="wiz-label">
                  <span>Salary expectation — minimum ($)</span>
                  <input type="number" min="0" value={salaryMin} onChange={(e) => setSalaryMin(e.target.value)} placeholder="e.g. 80000" />
                </label>

                <label className="wiz-label">
                  <span>Salary expectation — maximum ($)</span>
                  <input type="number" min="0" value={salaryMax} onChange={(e) => setSalaryMax(e.target.value)} placeholder="e.g. 120000" />
                </label>

                <label className="wiz-label">
                  <span>When can you start?</span>
                  <select value={startAvailability} onChange={(e) => setStartAvailability(e.target.value)}>
                    <option value="immediately">Immediately</option>
                    <option value="2_weeks">In 2 weeks</option>
                    <option value="1_month">In 1 month</option>
                    <option value="flexible">Flexible</option>
                  </select>
                </label>

                <label className="wiz-label">
                  <span>Willing to undergo a background check?</span>
                  <select value={willingBackgroundCheck ? "yes" : "no"} onChange={(e) => setWillingBackgroundCheck(e.target.value === "yes")}>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </label>
              </div>

              {saveError && <div className="wiz-error">{saveError}</div>}
              {doneBanner && (
                <div className="wiz-done">
                  <Check size={16} />
                  All set — redirecting to your dashboard…
                </div>
              )}

              <footer className="wiz-foot">
                <button type="button" className="btn-secondary" onClick={() => setStep(3)}>
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
