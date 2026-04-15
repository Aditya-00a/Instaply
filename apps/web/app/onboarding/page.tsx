"use client";

import { useEffect, useMemo, useState } from "react";
import { BriefcaseBusiness, Mail, MapPin, Phone, ShieldCheck, Sparkles, UserRound, X } from "lucide-react";
import { emptyCandidateWorkspaceProfile } from "../lib/empty-profile";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

import {
  instaplyCoverLetterFormats,
  instaplyExperienceLevels,
  instaplyPortals,
  instaplyResumeFormats,
  instaplyWorkModes,
  starterCandidateWorkspaceProfile,
  type CandidateWorkspaceProfile,
  type CoverLetterFormatId,
  type ExperienceLevel,
  type PortalId,
  type ResumeFormatId,
  type WorkMode
} from "@instaply/contracts";

import { ConsoleShell } from "../components/console-shell";
import { OnboardingSaveBar } from "../components/onboarding-save-bar";
import { ResumeUploadCard } from "../components/resume-upload-card";

const humanize = (value: string) => value.replaceAll("_", " ");

const cloneProfile = (): CandidateWorkspaceProfile => JSON.parse(JSON.stringify(starterCandidateWorkspaceProfile));
const cloneEmpty = (): CandidateWorkspaceProfile => JSON.parse(JSON.stringify(emptyCandidateWorkspaceProfile));

type ArrayEditorProps = {
  label: string;
  icon: typeof Sparkles;
  values: string[];
  placeholder: string;
  onChange: (values: string[]) => void;
};

function ArrayEditor({ label, icon: Icon, values, placeholder, onChange }: ArrayEditorProps) {
  const [draft, setDraft] = useState("");

  const addValue = () => {
    const next = draft.trim();
    if (!next) return;
    if (values.some((value) => value.toLowerCase() === next.toLowerCase())) {
      setDraft("");
      return;
    }
    onChange([...values, next]);
    setDraft("");
  };

  const removeValue = (target: string) => onChange(values.filter((value) => value !== target));

  return (
    <div className="profile-field profile-field-span-2">
      <label>{label}</label>
      <div className="profile-array-input">
        <div className="profile-input-shell">
          <Icon size={16} />
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addValue();
              }
            }}
            placeholder={placeholder}
          />
        </div>
        <button className="profile-chip-button" onClick={addValue} type="button">
          Add
        </button>
      </div>
      <div className="profile-option-row">
        {values.map((value) => (
          <button className="profile-option-chip profile-option-chip-active" key={`${label}-${value}`} onClick={() => removeValue(value)} type="button">
            {value}
            <X size={12} />
          </button>
        ))}
      </div>
    </div>
  );
}

type SelectChipProps<T extends string> = {
  label: string;
  icon: typeof Sparkles;
  selected: T;
  options: readonly T[];
  onChange: (value: T) => void;
};

function SelectChipGroup<T extends string>({ label, icon: Icon, selected, options, onChange }: SelectChipProps<T>) {
  return (
    <div className="profile-field profile-field-span-2">
      <label>{label}</label>
      <div className="profile-field-value profile-field-value-static">
        <Icon size={16} />
        <span>{humanize(selected)}</span>
      </div>
      <div className="profile-option-row">
        {options.map((option) => (
          <button
            className={option === selected ? "profile-option-chip profile-option-chip-active" : "profile-option-chip"}
            key={`${label}-${option}`}
            onClick={() => onChange(option)}
            type="button"
          >
            {humanize(option)}
          </button>
        ))}
      </div>
    </div>
  );
}

type ToggleChipProps<T extends string> = {
  label: string;
  icon: typeof Sparkles;
  selected: T[];
  options: readonly T[];
  onChange: (values: T[]) => void;
};

function ToggleChipGroup<T extends string>({ label, icon: Icon, selected, options, onChange }: ToggleChipProps<T>) {
  const toggle = (value: T) => {
    onChange(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]);
  };

  return (
    <div className="profile-field profile-field-span-2">
      <label>{label}</label>
      <div className="profile-field-value profile-field-value-static">
        <Icon size={16} />
        <span>{selected.map(humanize).join(", ") || "Select options"}</span>
      </div>
      <div className="profile-option-row">
        {options.map((option) => (
          <button
            className={selected.includes(option) ? "profile-option-chip profile-option-chip-active" : "profile-option-chip"}
            key={`${label}-${option}`}
            onClick={() => toggle(option)}
            type="button"
          >
            {humanize(option)}
          </button>
        ))}
      </div>
    </div>
  );
}

type TextFieldProps = {
  label: string;
  icon: typeof UserRound;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
  textarea?: boolean;
  span?: 1 | 2;
};

function TextField({ label, icon: Icon, value, placeholder, onChange, textarea = false, span = 1 }: TextFieldProps) {
  return (
    <div className={span === 2 ? "profile-field profile-field-span-2" : "profile-field"}>
      <label>{label}</label>
      {textarea ? (
        <div className="profile-textarea-shell">
          <Icon size={16} />
          <textarea placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} rows={4} />
        </div>
      ) : (
        <div className="profile-input-shell">
          <Icon size={16} />
          <input placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} />
        </div>
      )}
    </div>
  );
}

export default function OnboardingPage() {
  // Signed-in users start with an empty profile and hydrate from
  // Supabase if they have saved data. Preview/demo users see the
  // fixture starter profile so the marketing shell stays alive.
  const [profile, setProfile] = useState<CandidateWorkspaceProfile>(
    isSupabaseConfigured() ? cloneEmpty : cloneProfile
  );

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    let cancelled = false;
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return;
      const { data, error } = await supabase
        .from("profiles")
        .select(
          "full_name, phone, linkedin_url, github_url, website_url, current_city, current_state, current_country, needs_sponsorship, willing_to_relocate, email"
        )
        .eq("id", user.id)
        .single();
      if (error || !data || cancelled) return;

      setProfile((prev) => {
        const next = cloneEmpty();
        const parts = (data.full_name || "").split(" ");
        next.identity.firstName = parts[0] || "";
        next.identity.lastName = parts.slice(1).join(" ") || "";
        next.identity.legalFullName = data.full_name || "";
        next.identity.primaryEmail = data.email || user.email || "";
        next.identity.phoneNumber = data.phone || "";
        next.identity.linkedinUrl = data.linkedin_url || "";
        next.identity.githubUrl = data.github_url || "";
        next.identity.portfolioUrl = data.website_url || "";
        next.identity.currentCity = data.current_city || "";
        next.identity.currentRegion = data.current_state || "";
        next.identity.currentCountry = data.current_country || "United States";
        next.authorization.requiresSponsorship = !!data.needs_sponsorship;
        next.authorization.willingToRelocate = data.willing_to_relocate ?? true;
        return next;
      });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const initials = useMemo(
    () => `${profile.identity.firstName.slice(0, 1)}${profile.identity.lastName.slice(0, 1)}`,
    [profile.identity.firstName, profile.identity.lastName]
  );

  return (
    <ConsoleShell
      activePath="/onboarding"
      eyebrow="Profile"
      title="My Profile"
      description=""
      actions={[
        { href: "/settings", label: "Profile settings" },
        { href: "/review", label: "Review answers", variant: "secondary" }
      ]}
    >
      <section className="console-section">
        <OnboardingSaveBar profile={profile} />
      </section>

      <section className="console-section onboarding-uploads-grid">
        <ResumeUploadCard kind="resume" />
        <ResumeUploadCard kind="cover_letter" />
      </section>

      <section className="console-section">
        <article className="glass profile-hero-card">
          <div className="profile-hero-banner">
            <div className="profile-avatar">
              <span>{initials}</span>
            </div>

            <div className="profile-hero-copy">
              <h2>{profile.identity.legalFullName || "Candidate profile"}</h2>
              <p>{profile.application.currentTitle || "Add your current role"}</p>
              <div className="profile-hero-meta">
                <span>
                  <Mail size={14} />
                  {profile.identity.primaryEmail || "Add email"}
                </span>
                <span>
                  <MapPin size={14} />
                  {[profile.identity.currentCity, profile.identity.currentRegion].filter(Boolean).join(", ") || "Add location"}
                </span>
              </div>
            </div>
          </div>
        </article>
      </section>

      <section className="console-section">
        <article className="glass profile-section-card">
          <div className="profile-section-header">
            <div>
              <div className="panel-kicker">Profile</div>
              <h3>Personal information</h3>
            </div>
          </div>

          <div className="profile-field-grid">
            <TextField label="First name" icon={UserRound} value={profile.identity.firstName} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, firstName: value } }))} />
            <TextField label="Last name" icon={UserRound} value={profile.identity.lastName} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, lastName: value } }))} />
            <TextField label="Legal full name" icon={UserRound} value={profile.identity.legalFullName} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, legalFullName: value } }))} />
            <TextField label="Current title" icon={BriefcaseBusiness} value={profile.application.currentTitle} onChange={(value) => setProfile((current) => ({ ...current, application: { ...current.application, currentTitle: value } }))} />
            <TextField label="Primary email" icon={Mail} value={profile.identity.primaryEmail} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, primaryEmail: value } }))} />
            <TextField label="School email" icon={Mail} value={profile.identity.secondaryEmail ?? ""} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, secondaryEmail: value } }))} />
            <TextField label="Phone number" icon={Phone} value={profile.identity.phoneNumber} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, phoneNumber: value } }))} />
            <TextField label="City" icon={MapPin} value={profile.identity.currentCity} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, currentCity: value } }))} />
            <TextField label="Region / state" icon={MapPin} value={profile.identity.currentRegion} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, currentRegion: value } }))} />
            <TextField label="Country" icon={MapPin} value={profile.identity.currentCountry} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, currentCountry: value } }))} />
            <TextField label="LinkedIn" icon={Sparkles} value={profile.identity.linkedinUrl ?? ""} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, linkedinUrl: value } }))} />
            <TextField label="Website link" icon={Sparkles} value={profile.identity.portfolioUrl ?? ""} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, portfolioUrl: value } }))} />
            <TextField label="GitHub / portfolio" icon={Sparkles} value={profile.identity.githubUrl ?? profile.identity.portfolioUrl ?? ""} onChange={(value) => setProfile((current) => ({ ...current, identity: { ...current.identity, githubUrl: value } }))} />
            <TextField
              label="Work authorization"
              icon={ShieldCheck}
              value={profile.authorization.workAuthorizationSummary}
              onChange={(value) => setProfile((current) => ({ ...current, authorization: { ...current.authorization, workAuthorizationSummary: value } }))}
              textarea
              span={2}
            />
          </div>
        </article>
      </section>

      <section className="console-section">
        <article className="glass profile-section-card">
          <div className="profile-section-header">
            <div>
              <div className="panel-kicker">Search</div>
              <h3>Job preferences</h3>
            </div>
          </div>

          <div className="profile-field-grid">
            <SelectChipGroup
              label="Experience level"
              icon={Sparkles}
              selected={profile.jobSearch.experienceLevel}
              options={instaplyExperienceLevels}
              onChange={(value: ExperienceLevel) => setProfile((current) => ({ ...current, jobSearch: { ...current.jobSearch, experienceLevel: value } }))}
            />
            <ToggleChipGroup
              label="Work modes"
              icon={Sparkles}
              selected={profile.jobSearch.workModes}
              options={instaplyWorkModes}
              onChange={(values: WorkMode[]) => setProfile((current) => ({ ...current, jobSearch: { ...current.jobSearch, workModes: values } }))}
            />
            <ToggleChipGroup
              label="Portals"
              icon={Sparkles}
              selected={profile.jobSearch.portalSelections}
              options={instaplyPortals}
              onChange={(values: PortalId[]) => setProfile((current) => ({ ...current, jobSearch: { ...current.jobSearch, portalSelections: values } }))}
            />
            <ArrayEditor
              label="Target roles"
              icon={BriefcaseBusiness}
              values={profile.jobSearch.targetRoles}
              placeholder="Add a role you want on search and resume targeting"
              onChange={(values) => setProfile((current) => ({ ...current, jobSearch: { ...current.jobSearch, targetRoles: values } }))}
            />
            <ArrayEditor
              label="Preferred locations"
              icon={MapPin}
              values={profile.jobSearch.preferredLocations}
              placeholder="Add a city, region, or remote preference"
              onChange={(values) => setProfile((current) => ({ ...current, jobSearch: { ...current.jobSearch, preferredLocations: values } }))}
            />
            <ArrayEditor
              label="Preferred companies"
              icon={BriefcaseBusiness}
              values={[...profile.jobSearch.suggestedCompanies, ...profile.jobSearch.userAddedCompanies]}
              placeholder="Add companies you want the agent to prioritize"
              onChange={(values) =>
                setProfile((current) => ({
                  ...current,
                  jobSearch: {
                    ...current.jobSearch,
                    suggestedCompanies: values.slice(0, Math.min(6, values.length)),
                    userAddedCompanies: values.slice(Math.min(6, values.length))
                  }
                }))
              }
            />
          </div>
        </article>
      </section>

      <section className="console-section">
        <article className="glass profile-section-card">
          <div className="profile-section-header">
            <div>
              <div className="panel-kicker">Documents</div>
              <h3>Document preferences</h3>
            </div>
          </div>

          <div className="profile-field-grid">
            <SelectChipGroup
              label="Resume format"
              icon={Sparkles}
              selected={profile.resume.format}
              options={instaplyResumeFormats}
              onChange={(value: ResumeFormatId) => setProfile((current) => ({ ...current, resume: { ...current.resume, format: value } }))}
            />
            <SelectChipGroup
              label="Cover letter format"
              icon={Sparkles}
              selected={profile.coverLetter.format}
              options={instaplyCoverLetterFormats}
              onChange={(value: CoverLetterFormatId) => setProfile((current) => ({ ...current, coverLetter: { ...current.coverLetter, format: value } }))}
            />
            <SelectChipGroup
              label="Resume length"
              icon={Sparkles}
              selected={profile.resume.pageTarget}
              options={["one_page", "flex"] as const}
              onChange={(value: "one_page" | "flex") => setProfile((current) => ({ ...current, resume: { ...current.resume, pageTarget: value } }))}
            />
            <SelectChipGroup
              label="Cover letter length"
              icon={Sparkles}
              selected={`${profile.coverLetter.maxParagraphs}_paragraphs` as "2_paragraphs" | "3_paragraphs" | "4_paragraphs"}
              options={["2_paragraphs", "3_paragraphs", "4_paragraphs"] as const}
              onChange={(value: "2_paragraphs" | "3_paragraphs" | "4_paragraphs") =>
                setProfile((current) => ({
                  ...current,
                  coverLetter: { ...current.coverLetter, maxParagraphs: Number(value.slice(0, 1)) as 2 | 3 | 4 }
                }))
              }
            />
            <TextField
              label="Voice notes"
              icon={Sparkles}
              value={profile.resume.voiceNotes}
              onChange={(value) => setProfile((current) => ({ ...current, resume: { ...current.resume, voiceNotes: value } }))}
              textarea
              span={2}
            />
            <ArrayEditor
              label="Tone tags"
              icon={Sparkles}
              values={profile.coverLetter.toneTags}
              placeholder="Add tone tags like analytical, direct, warm"
              onChange={(values) => setProfile((current) => ({ ...current, coverLetter: { ...current.coverLetter, toneTags: values } }))}
            />
            <ArrayEditor
              label="Emphasis tracks"
              icon={Sparkles}
              values={profile.resume.emphasizeTracks}
              placeholder="Add tracks like analytics, strategy, operations"
              onChange={(values) => setProfile((current) => ({ ...current, resume: { ...current.resume, emphasizeTracks: values } }))}
            />
          </div>
        </article>
      </section>

      <section className="console-section">
        <article className="glass profile-section-card">
          <div className="profile-section-header">
            <div>
              <div className="panel-kicker">Resume inputs</div>
              <h3>Anything that can go into the packet</h3>
            </div>
          </div>

          <div className="profile-field-grid">
            <TextField
              label="Education summary"
              icon={UserRound}
              value={profile.application.educationSummary}
              onChange={(value) => setProfile((current) => ({ ...current, application: { ...current.application, educationSummary: value } }))}
              textarea
              span={2}
            />
            <ArrayEditor
              label="Education"
              icon={UserRound}
              values={profile.application.educationEntries}
              placeholder="Add a degree, school, award, or academic highlight"
              onChange={(values) => setProfile((current) => ({ ...current, application: { ...current.application, educationEntries: values } }))}
            />
            <ArrayEditor
              label="Work experience"
              icon={BriefcaseBusiness}
              values={profile.application.workExperienceEntries}
              placeholder="Add a role, company, and what should show up on the resume"
              onChange={(values) => setProfile((current) => ({ ...current, application: { ...current.application, workExperienceEntries: values } }))}
            />
            <ArrayEditor
              label="Projects"
              icon={Sparkles}
              values={profile.application.projectEntries}
              placeholder="Add a project with impact, stack, or outcome"
              onChange={(values) => setProfile((current) => ({ ...current, application: { ...current.application, projectEntries: values } }))}
            />
            <ArrayEditor
              label="Research papers"
              icon={Sparkles}
              values={profile.application.researchPaperEntries}
              placeholder="Add a paper title, venue, or publication status"
              onChange={(values) => setProfile((current) => ({ ...current, application: { ...current.application, researchPaperEntries: values } }))}
            />
            <TextField label="Signature" icon={ShieldCheck} value={profile.application.signatureDefault} onChange={(value) => setProfile((current) => ({ ...current, application: { ...current.application, signatureDefault: value } }))} />
            <TextField label="Compensation note" icon={BriefcaseBusiness} value={profile.application.compensationNotes} onChange={(value) => setProfile((current) => ({ ...current, application: { ...current.application, compensationNotes: value } }))} />
            <ArrayEditor
              label="Core skills"
              icon={Sparkles}
              values={profile.application.coreSkills}
              placeholder="Add a skill that may appear on the resume"
              onChange={(values) => setProfile((current) => ({ ...current, application: { ...current.application, coreSkills: values } }))}
            />
            <ArrayEditor
              label="Experience highlights"
              icon={BriefcaseBusiness}
              values={profile.application.experienceHighlights}
              placeholder="Add an experience bullet or accomplishment"
              onChange={(values) => setProfile((current) => ({ ...current, application: { ...current.application, experienceHighlights: values } }))}
            />
            <ArrayEditor
              label="Project highlights"
              icon={Sparkles}
              values={profile.application.projectHighlights}
              placeholder="Add a project, result, or technical achievement"
              onChange={(values) => setProfile((current) => ({ ...current, application: { ...current.application, projectHighlights: values } }))}
            />
          </div>
        </article>
      </section>
    </ConsoleShell>
  );
}
