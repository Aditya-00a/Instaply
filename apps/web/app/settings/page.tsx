"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, LockKeyhole, Loader2, Minus, Plus, Save, SlidersHorizontal, Sparkles } from "lucide-react";

import {
  instaplyExperienceLevels,
  instaplyPortals,
  instaplyRunModes,
  starterCandidateWorkspaceProfile,
  type CandidateWorkspaceProfile,
  type ExperienceLevel,
  type PortalId,
  type RunMode
} from "@instaply/contracts";

import { ConsoleShell } from "../components/console-shell";
import { McpTokensCard } from "../components/mcp-tokens-card";
import { MfaSetupCard } from "../components/mfa-setup-card";
import { AccountSettingsCard } from "../components/account-settings-card";
import { InviteCodeCard } from "../components/invite-code-card";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

const STORAGE_KEY = "instaply_workspace_settings";

const cloneProfile = (): CandidateWorkspaceProfile => {
  // Load from localStorage first
  if (typeof window !== "undefined") {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved);
    } catch {}
  }
  return JSON.parse(JSON.stringify(starterCandidateWorkspaceProfile));
};
const humanize = (value: string) => value.replaceAll("_", " ");
const companyModes = ["agent_recommended", "user_curated", "hybrid"] as const;
const suggestedLocations = ["New York", "Remote", "San Francisco", "Chicago", "Boston"] as const;

function Stepper({
  value,
  min = 0,
  onChange
}: {
  value: number;
  min?: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="settings-stepper">
      <button className="settings-stepper-button" onClick={() => onChange(Math.max(min, value - 1))} type="button">
        <Minus size={14} />
      </button>
      <div className="settings-stepper-value">{value}</div>
      <button className="settings-stepper-button" onClick={() => onChange(value + 1)} type="button">
        <Plus size={14} />
      </button>
    </div>
  );
}

function SwitchRow({
  checked,
  label,
  onToggle
}: {
  checked: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button className="settings-switch-row" onClick={onToggle} type="button">
      <span>{label}</span>
      <span className={checked ? "settings-switch settings-switch-active" : "settings-switch"}>
        <span className="settings-switch-knob" />
      </span>
    </button>
  );
}

export default function SettingsPage() {
  const [profile, setProfile] = useState<CandidateWorkspaceProfile>(cloneProfile);
  const [locationDraft, setLocationDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saved" | "error">("idle");
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-save to localStorage + Supabase on every change
  const persistSettings = useCallback(async (p: CandidateWorkspaceProfile) => {
    // Save to localStorage immediately
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(p)); } catch {}

    // Debounced save to Supabase
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      if (!isSupabaseConfigured()) return;
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      setSaving(true);
      try {
        await supabase.from("preferences").upsert({
          user_id: user.id,
          target_locations: p.jobSearch.preferredLocations,
          per_company_cap: p.automation.maxApplicationsPerRun,
          updated_at: new Date().toISOString(),
        });
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } catch {
        setSaveStatus("error");
      } finally {
        setSaving(false);
      }
    }, 1000);
  }, []);

  // Wrap setProfile to auto-save
  const updateProfile = useCallback((updater: (p: CandidateWorkspaceProfile) => CandidateWorkspaceProfile) => {
    setProfile((prev) => {
      const next = updater(prev);
      persistSettings(next);
      return next;
    });
  }, [persistSettings]);

  const settingsStats = [
    { label: "Selected portals", value: String(profile.jobSearch.portalSelections.length) },
    { label: "Preferred locations", value: String(profile.jobSearch.preferredLocations.length) },
    { label: "Daily apply cap", value: String(profile.automation.dailyApplyCap) },
    { label: "Default run mode", value: humanize(profile.automation.preferredRunMode) }
  ];

  const togglePortal = (portal: PortalId) => {
    updateProfile((current) => ({
      ...current,
      jobSearch: {
        ...current.jobSearch,
        portalSelections: current.jobSearch.portalSelections.includes(portal)
          ? current.jobSearch.portalSelections.filter((value) => value !== portal)
          : [...current.jobSearch.portalSelections, portal]
      }
    }));
  };

  const addLocation = (value: string) => {
    const next = value.trim();
    if (!next) return;
    setProfile((current) => {
      if (current.jobSearch.preferredLocations.some((item) => item.toLowerCase() === next.toLowerCase())) {
        return current;
      }
      return {
        ...current,
        jobSearch: {
          ...current.jobSearch,
          preferredLocations: [...current.jobSearch.preferredLocations, next]
        }
      };
    });
    setLocationDraft("");
  };

  return (
    <ConsoleShell
      activePath="/settings"
      eyebrow="Settings"
      title="Workspace settings"
      description={saving ? "Saving..." : saveStatus === "saved" ? "All changes saved" : "Changes auto-save as you go"}
      actions={[
        { href: "/onboarding", label: "Edit profile" },
        { href: "/billing", label: "View billing", variant: "secondary" }
      ]}
    >
      <section className="console-section">
        <div className="applications-summary-grid">
          {settingsStats.map((card) => (
            <article className="glass applications-summary-card" key={card.label}>
              <span>{card.label}</span>
              <strong>{card.value}</strong>
            </article>
          ))}
        </div>
      </section>

      <section className="console-section settings-grid">
        <article className="glass settings-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">Search controls</div>
              <h3>Portal and location policy</h3>
            </div>
            <SlidersHorizontal size={18} />
          </div>

          <div className="settings-field-grid">
            <div className="settings-field settings-field-span-2">
              <label>Selected portals</label>
              <div className="settings-portal-grid">
                {instaplyPortals.map((portal) => {
                  const active = profile.jobSearch.portalSelections.includes(portal);
                  return (
                    <button
                      className={active ? "settings-portal-card settings-portal-card-active" : "settings-portal-card"}
                      key={portal}
                      onClick={() => togglePortal(portal)}
                      type="button"
                    >
                      <span className={active ? "settings-check settings-check-active" : "settings-check"}>
                        {active ? <Check size={12} /> : null}
                      </span>
                      <span>{humanize(portal)}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="settings-field settings-field-span-2">
              <label>Preferred locations</label>
              <div className="profile-array-input">
                <div className="profile-input-shell">
                  <Sparkles size={16} />
                  <input
                    placeholder="Add a city, metro, or remote location"
                    value={locationDraft}
                    onChange={(event) => setLocationDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        addLocation(locationDraft);
                      }
                    }}
                  />
                </div>
                <button className="profile-chip-button" onClick={() => addLocation(locationDraft)} type="button">
                  Add
                </button>
              </div>
              <div className="profile-option-row">
                {suggestedLocations
                  .filter((location) => !profile.jobSearch.preferredLocations.includes(location))
                  .map((location) => (
                    <button className="profile-option-chip" key={location} onClick={() => addLocation(location)} type="button">
                      + {location}
                    </button>
                  ))}
              </div>
              <div className="profile-option-row">
                {profile.jobSearch.preferredLocations.map((location) => (
                  <button
                    className="profile-option-chip profile-option-chip-active"
                    key={location}
                    onClick={() =>
                      updateProfile((current) => ({
                        ...current,
                        jobSearch: {
                          ...current.jobSearch,
                          preferredLocations: current.jobSearch.preferredLocations.filter((value) => value !== location)
                        }
                      }))
                    }
                    type="button"
                  >
                    {location}
                  </button>
                ))}
              </div>
            </div>

            <div className="settings-field">
              <label>Experience level</label>
              <div className="settings-select-shell">
                <select
                  value={profile.jobSearch.experienceLevel}
                  onChange={(event) =>
                    updateProfile((current) => ({
                      ...current,
                      jobSearch: { ...current.jobSearch, experienceLevel: event.target.value as ExperienceLevel }
                    }))
                  }
                >
                  {instaplyExperienceLevels.map((level) => (
                    <option key={level} value={level}>
                      {humanize(level)}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="settings-field">
              <label>Company mode</label>
              <div className="settings-select-shell">
                <select
                  value={profile.jobSearch.companyRecommendationMode}
                  onChange={(event) =>
                    updateProfile((current) => ({
                      ...current,
                      jobSearch: {
                        ...current.jobSearch,
                        companyRecommendationMode: event.target.value as (typeof companyModes)[number]
                      }
                    }))
                  }
                >
                  {companyModes.map((mode) => (
                    <option key={mode} value={mode}>
                      {humanize(mode)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </article>

        <article className="glass settings-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">Automation policy</div>
              <h3>Agent behavior defaults</h3>
            </div>
            <LockKeyhole size={18} />
          </div>

          <div className="settings-field-grid">
            <div className="settings-field settings-field-span-2">
              <label>Preferred run mode</label>
              <div className="settings-select-shell">
                <select
                  value={profile.automation.preferredRunMode}
                  onChange={(event) =>
                    updateProfile((current) => ({
                      ...current,
                      automation: { ...current.automation, preferredRunMode: event.target.value as RunMode }
                    }))
                  }
                >
                  {instaplyRunModes.map((mode) => (
                    <option key={mode} value={mode}>
                      {humanize(mode)}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="settings-field">
              <label>Daily apply cap</label>
              <Stepper
                value={profile.automation.dailyApplyCap}
                min={0}
                onChange={(value) =>
                  updateProfile((current) => ({
                    ...current,
                    automation: { ...current.automation, dailyApplyCap: value }
                  }))
                }
              />
            </div>

            <div className="settings-field">
              <label>Max applications per run</label>
              <Stepper
                value={profile.automation.maxApplicationsPerRun}
                min={0}
                onChange={(value) =>
                  updateProfile((current) => ({
                    ...current,
                    automation: { ...current.automation, maxApplicationsPerRun: value }
                  }))
                }
              />
            </div>

            <div className="settings-field settings-field-span-2">
              <label>Automation</label>
              <div className="settings-switch-stack">
                <SwitchRow
                  checked={profile.automation.autoApplyEnabled}
                  label="Automation enabled"
                  onToggle={() =>
                    updateProfile((current) => ({
                      ...current,
                      automation: { ...current.automation, autoApplyEnabled: !current.automation.autoApplyEnabled }
                    }))
                  }
                />
              </div>
            </div>
          </div>
        </article>
      </section>

      <section className="console-section">
        <InviteCodeCard />
      </section>

      <section className="console-section">
        <MfaSetupCard />
      </section>

      <section className="console-section">
        <McpTokensCard />
      </section>

      <section className="console-section">
        <AccountSettingsCard />
      </section>
    </ConsoleShell>
  );
}
