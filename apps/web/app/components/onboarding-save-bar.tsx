"use client";

import { FileUp, Save } from "lucide-react";
import { useState } from "react";
import type { CandidateWorkspaceProfile } from "@instaply/contracts";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type Props = {
  profile: CandidateWorkspaceProfile;
};

type Status =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

/**
 * Save-to-Supabase bar for the onboarding page. Lives above the form,
 * handles:
 *   1. Mapping the workspace profile shape into the flat `profiles`
 *      table columns,
 *   2. Uploading a resume file to the `resumes` storage bucket and
 *      inserting a row into the `resumes` table.
 *
 * Graceful: in demo mode (no Supabase env) the Save button shows a
 * notice and no request is sent.
 */
export function OnboardingSaveBar({ profile }: Props) {
  const ready = isSupabaseConfigured();
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [resume, setResume] = useState<File | null>(null);

  const onResumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    if (f && f.size > 10 * 1024 * 1024) {
      setStatus({ kind: "error", message: "Resume must be under 10 MB." });
      setResume(null);
      return;
    }
    setResume(f);
    setStatus({ kind: "idle" });
  };

  const save = async () => {
    setStatus({ kind: "saving" });

    if (!ready) {
      setStatus({
        kind: "error",
        message:
          "Preview mode — connect the Supabase backend to save your profile.",
      });
      return;
    }

    const supabase = getBrowserSupabase();
    if (!supabase) {
      setStatus({ kind: "error", message: "Auth service unavailable." });
      return;
    }

    try {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setStatus({ kind: "error", message: "Please sign in first." });
        return;
      }

      const identity = profile.identity;
      const auth = profile.authorization;

      const profileUpdate = {
        full_name:
          [identity.firstName, identity.lastName].filter(Boolean).join(" ") ||
          identity.legalFullName ||
          null,
        phone: identity.phoneNumber || null,
        linkedin_url: identity.linkedinUrl || null,
        github_url: identity.githubUrl || null,
        website_url: identity.portfolioUrl || null,
        current_city: identity.currentCity || null,
        current_state: identity.currentRegion || null,
        current_country: identity.currentCountry || "US",
        needs_sponsorship: auth.requiresSponsorship ?? false,
        willing_to_relocate: auth.willingToRelocate ?? true,
        updated_at: new Date().toISOString(),
      };

      const { error: profileErr } = await supabase
        .from("profiles")
        .update(profileUpdate)
        .eq("id", user.id);

      if (profileErr) throw profileErr;

      // Upload the resume (optional)
      if (resume) {
        const path = `${user.id}/${Date.now()}-${resume.name}`;
        const { error: uploadErr } = await supabase.storage
          .from("resumes")
          .upload(path, resume, { upsert: false, contentType: resume.type });
        if (uploadErr) throw uploadErr;

        const { error: rowErr } = await supabase.from("resumes").insert({
          user_id: user.id,
          storage_path: path,
          file_name: resume.name,
          file_size_bytes: resume.size,
          is_primary: false,
        });
        if (rowErr) throw rowErr;

        setResume(null);
      }

      setStatus({ kind: "saved" });
      setTimeout(() => setStatus({ kind: "idle" }), 2400);
    } catch (e) {
      setStatus({
        kind: "error",
        message: e instanceof Error ? e.message : "Save failed.",
      });
    }
  };

  return (
    <div className="onboarding-save-bar">
      <div className="onboarding-save-info">
        <strong>Save to your Instaply profile</strong>
        <span>
          Updates your profile row and optionally uploads a new resume.
          Your data is private and scoped to your account.
        </span>
      </div>

      <div className="onboarding-save-actions">
        <label className="onboarding-resume-pick">
          <FileUp size={14} />
          {resume ? resume.name.slice(0, 32) : "Choose resume (PDF / DOCX)"}
          <input
            type="file"
            accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={onResumeChange}
            hidden
          />
        </label>

        <button
          type="button"
          className="btn-primary"
          onClick={save}
          disabled={status.kind === "saving"}
        >
          <Save size={14} />
          {status.kind === "saving"
            ? "Saving…"
            : status.kind === "saved"
            ? "Saved ✓"
            : "Save profile"}
        </button>
      </div>

      {status.kind === "error" && (
        <div className="onboarding-save-error">{status.message}</div>
      )}

      {status.kind === "saved" && (
        <div className="onboarding-save-ok">
          Profile saved{resume ? " and resume uploaded" : ""}.
        </div>
      )}
    </div>
  );
}
