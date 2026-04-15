"use client";

import { Save } from "lucide-react";
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
          Updates your profile row. Your data is private and scoped to
          your account.
        </span>
      </div>

      <div className="onboarding-save-actions">
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
        <div className="onboarding-save-ok">Profile saved.</div>
      )}
    </div>
  );
}
