"use client";

import Link from "next/link";
import { ExternalLink, Loader2, Search, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type JobResult = {
  id: string;
  title: string;
  company_name: string;
  source: string;
  location: string | null;
  remote: boolean;
  apply_url: string;
  matchScore?: number;
};

type ExtractedSkills = {
  skills?: string[];
  titles_held?: string[];
  industries?: string[];
  experience_years?: number;
  summary?: string;
};

function scoreJob(job: JobResult, skills: ExtractedSkills, targetLocations: string[]): number {
  const title = (job.title || "").toLowerCase();
  const loc = (job.location || "").toLowerCase();
  let score = 0;
  let factors = 0;

  // Skill match (40% weight) — how many of the user's skills appear in the job title
  const userSkills = (skills.skills || []).map((s) => s.toLowerCase());
  if (userSkills.length > 0) {
    const titleWords = title.split(/[\s,\-\/()]+/);
    let matched = 0;
    for (const skill of userSkills) {
      const skillWords = skill.split(/\s+/);
      if (skillWords.every((w) => titleWords.some((tw) => tw.includes(w) || w.includes(tw)))) {
        matched++;
      }
    }
    score += 0.4 * Math.min(matched / Math.min(userSkills.length, 5), 1);
    factors += 0.4;
  }

  // Title match (35% weight) — does the job title match titles the user has held?
  const heldTitles = (skills.titles_held || []).map((t) => t.toLowerCase());
  if (heldTitles.length > 0) {
    let bestTitleMatch = 0;
    for (const held of heldTitles) {
      const heldWords = held.split(/\s+/);
      const matchedWords = heldWords.filter((w) =>
        title.includes(w) && w.length > 2
      ).length;
      const ratio = matchedWords / heldWords.length;
      if (ratio > bestTitleMatch) bestTitleMatch = ratio;
    }
    score += 0.35 * bestTitleMatch;
    factors += 0.35;
  }

  // Location match (15% weight)
  if (targetLocations.length > 0) {
    const locMatch = targetLocations.some(
      (tl) => loc.includes(tl.toLowerCase()) || (tl.toLowerCase() === "remote" && job.remote)
    );
    score += locMatch ? 0.15 : 0;
    factors += 0.15;
  }

  // Industry match (10% weight)
  const industries = (skills.industries || []).map((i) => i.toLowerCase());
  if (industries.length > 0) {
    const companyLower = (job.company_name || "").toLowerCase();
    const indMatch = industries.some((ind) => title.includes(ind) || companyLower.includes(ind));
    score += indMatch ? 0.1 : 0;
    factors += 0.1;
  }

  // Normalize to 0-100
  return factors > 0 ? Math.round((score / factors) * 100) : 0;
}

const SOURCES: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  smartrecruiters: "SmartRecruiters",
  workday: "Workday",
};

export default function SearchPage() {
  const ready = isSupabaseConfigured();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<JobResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedIds, setQueuedIds] = useState<Set<string>>(new Set());
  const [queueing, setQueueing] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [suggested, setSuggested] = useState<JobResult[] | null>(null);
  const [targetTitles, setTargetTitles] = useState<string[]>([]);
  const [extractedSkills, setExtractedSkills] = useState<ExtractedSkills>({});
  const [targetLocations, setTargetLocations] = useState<string[]>([]);
  const [analyzing, setAnalyzing] = useState(false);

  // Load applied IDs + preferences on mount; show recommended jobs automatically
  useEffect(() => {
    if (!ready) return;
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      // Load applied job IDs
      const { data: apps } = await supabase
        .from("applications")
        .select("job_id")
        .eq("user_id", user.id);
      if (apps) {
        setQueuedIds(new Set(apps.map((r: { job_id: string }) => r.job_id)));
      }

      // Load profile skills + preferences
      const { data: profile } = await supabase
        .from("profiles")
        .select("extracted_skills")
        .eq("id", user.id)
        .single();
      if (profile?.extracted_skills && Object.keys(profile.extracted_skills).length > 0) {
        setExtractedSkills(profile.extracted_skills as ExtractedSkills);
      }

      const { data: prefs } = await supabase
        .from("preferences")
        .select("target_titles, target_locations")
        .eq("user_id", user.id)
        .limit(1);

      if (prefs && prefs[0]) {
        const titles = (prefs[0].target_titles as string[]) || [];
        const locations = (prefs[0].target_locations as string[]) || [];
        setTargetTitles(titles);
        setTargetLocations(locations);

        if (titles.length > 0) {
          // Build OR filter from target titles for recommended jobs
          const titleFilters = titles.map((t) => `title.ilike.*${t.split(" ").join("*")}*`).join(",");
          let q = supabase
            .from("jobs")
            .select("id, title, company_name, source, location, remote, apply_url")
            .or(titleFilters)
            .eq("is_active", true)
            .order("discovered_at", { ascending: false })
            .limit(20);

          const { data: recJobs } = await q;
          if (recJobs && recJobs.length > 0) {
            setSuggested(recJobs as JobResult[]);
          }
        }
      }
    })();
  }, [ready]);

  const search = async () => {
    if (!query.trim()) return;
    if (!ready) {
      setError("Sign in to search for jobs.");
      return;
    }
    setSearching(true);
    setError(null);
    setResults(null);

    const supabase = getBrowserSupabase();
    if (!supabase) {
      setError("Auth unavailable.");
      setSearching(false);
      return;
    }

    try {
      // Split query into words and match ANY word for broader results.
      // "business analyst" matches "Business Systems Analyst", "Risk Analyst", etc.
      const words = query.trim().split(/\s+/).filter(Boolean);
      const orFilter = words.map((w) => `title.ilike.%${w}%`).join(",");

      const { data, error: err } = await supabase
        .from("jobs")
        .select("id, title, company_name, source, location, remote, apply_url")
        .or(orFilter)
        .eq("is_active", true)
        .order("discovered_at", { ascending: false })
        .limit(50);

      if (err) throw err;
      // Score and sort results by match quality
      const scored = ((data ?? []) as JobResult[]).map((job) => ({
        ...job,
        matchScore: scoreJob(job, extractedSkills, targetLocations),
      }));
      scored.sort((a, b) => (b.matchScore || 0) - (a.matchScore || 0));
      setResults(scored);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed.");
    } finally {
      setSearching(false);
    }
  };

  const queueJob = async (job: JobResult) => {
    if (!ready) return;
    const supabase = getBrowserSupabase();
    if (!supabase) return;

    setQueueing(job.id);
    try {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setError("Please sign in.");
        return;
      }

      const { error: err } = await supabase.from("applications").insert({
        user_id: user.id,
        job_id: job.id,
        status: "queued",
        fit_score: null,
      });

      if (err) {
        if (err.message.includes("duplicate") || err.code === "23505") {
          setQueuedIds((prev) => new Set(prev).add(job.id));
          setToast("You've already applied to this role.");
          setTimeout(() => setToast(null), 3000);
          return;
        }
        throw err;
      }
      setQueuedIds((prev) => new Set(prev).add(job.id));
      setToast(`Applied to ${job.title} at ${job.company_name}. We'll submit within 30 minutes.`);
      setTimeout(() => setToast(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit application.");
    } finally {
      setQueueing(null);
    }
  };

  return (
    <ConsoleShell
      activePath="/search"
      eyebrow="Search"
      title="Find jobs"
      description="Search across Greenhouse, Lever, SmartRecruiters, and Workday. Click Apply to submit an application on your behalf."
      actions={[
        { href: "/applications", label: "View applications", variant: "secondary" },
      ]}
    >
      {toast && (
        <div className="search-toast">{toast}</div>
      )}

      <section className="console-section">
        <div className="search-bar">
          <div className="search-bar-input">
            <Search size={18} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              placeholder="Search by role title (e.g. Product Manager, Risk Analyst, Software Engineer)"
              autoFocus
            />
          </div>
          <button
            type="button"
            className="btn-primary"
            onClick={search}
            disabled={searching || !query.trim()}
          >
            {searching ? <Loader2 size={16} className="spin" /> : <Search size={16} />}
            Search
          </button>
        </div>

        {targetTitles.length > 0 && (
          <div className="search-quick-chips">
            <span className="search-quick-label">Quick search:</span>
            {targetTitles.map((t) => (
              <button
                key={t}
                type="button"
                className="search-quick-chip"
                onClick={() => { setQuery(t); }}
              >
                {t}
              </button>
            ))}
          </div>
        )}

        {!Object.keys(extractedSkills).length && !analyzing && (
          <div className="search-analyze-prompt">
            <Sparkles size={16} />
            <div>
              <strong>Get personalized match scores</strong>
              <p>We'll scan your resume with AI and score every job against your skills, experience, and background.</p>
            </div>
            <button
              type="button"
              className="btn-primary"
              onClick={async () => {
                setAnalyzing(true);
                setToast("Analyzing your resume...");
                try {
                  const supabase = getBrowserSupabase();
                  if (!supabase) throw new Error("Not signed in");
                  const { data: { session } } = await supabase.auth.getSession();
                  if (!session) throw new Error("Not signed in");
                  const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE || "https://api.asion.ai"}/profile/analyze-resume`, {
                    method: "POST",
                    headers: { "Authorization": `Bearer ${session.access_token}` },
                  });
                  if (!res.ok) {
                    const errText = await res.text();
                    throw new Error(errText || "Analysis failed");
                  }
                  const result = await res.json();
                  setExtractedSkills(result.extracted as ExtractedSkills);
                  setToast(`Found ${(result.extracted?.skills || []).length} skills in your resume!`);
                  setTimeout(() => setToast(null), 4000);
                } catch (e) {
                  setToast(e instanceof Error ? e.message : "Analysis failed. Try again.");
                  setTimeout(() => setToast(null), 5000);
                } finally {
                  setAnalyzing(false);
                }
              }}
            >
              Analyze my resume
            </button>
          </div>
        )}
        {analyzing && (
          <div className="search-analyze-prompt">
            <Loader2 size={16} className="spin" />
            <div>
              <strong>Scanning your resume...</strong>
              <p>Extracting skills, experience, and education. This takes about 10 seconds.</p>
            </div>
          </div>
        )}

        {error && <div className="search-error">{error}</div>}

        {results !== null && results.length === 0 && (
          <div className="search-empty">
            <Sparkles size={22} />
            <div>
              <strong>No roles found for &ldquo;{query}&rdquo;</strong>
              <p>
                Try a broader title (e.g. &ldquo;analyst&rdquo; instead
                of &ldquo;senior risk analyst II&rdquo;) or check back
                later — the bridge adds new roles every 4 hours.
              </p>
            </div>
          </div>
        )}

        {results && results.length > 0 && (
          <>
            <div className="search-count">
              {results.length} role{results.length === 1 ? "" : "s"} found
              {Object.keys(extractedSkills).length > 0 && " · sorted by resume match"}
            </div>
            <div className="search-results">
              {results.map((job) => {
                const isQueued = queuedIds.has(job.id);
                const isQueueing = queueing === job.id;
                return (
                  <article className="search-result" key={job.id}>
                    <div className="search-result-main">
                      <strong>{job.title}</strong>
                      <span className="search-result-meta">
                        {job.company_name}
                        {job.location ? ` · ${job.location}` : ""}
                        {job.remote ? " · Remote" : ""}
                      </span>
                      <span className="search-result-source">
                        {SOURCES[job.source] || job.source}
                      </span>
                    </div>
                    {job.matchScore != null && job.matchScore > 0 && (
                      <span className={`search-match-badge ${job.matchScore >= 70 ? "search-match-high" : job.matchScore >= 40 ? "search-match-mid" : "search-match-low"}`}>
                        {job.matchScore}% match
                      </span>
                    )}
                    <div className="search-result-actions">
                      {job.apply_url && (
                        <a
                          href={job.apply_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="search-result-link"
                          title="View on ATS"
                        >
                          <ExternalLink size={14} />
                        </a>
                      )}
                      <button
                        type="button"
                        className={isQueued ? "search-queue-btn search-queue-btn-done" : "search-queue-btn"}
                        onClick={() => !isQueued && queueJob(job)}
                        disabled={isQueued || isQueueing}
                      >
                        {isQueueing
                          ? "Applying…"
                          : isQueued
                          ? "✓ Applied"
                          : "Apply"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </>
        )}

        {results === null && !searching && suggested && suggested.length > 0 && (
          <>
            <div className="search-recommended-header">
              <Sparkles size={16} />
              <strong>Recommended for you</strong>
              <span>Based on your target roles: {targetTitles.join(", ")}</span>
            </div>
            <div className="search-results">
              {suggested.map((job) => {
                const isQueued = queuedIds.has(job.id);
                const isQueueing = queueing === job.id;
                return (
                  <article className="search-result" key={job.id}>
                    <div className="search-result-main">
                      <strong>{job.title}</strong>
                      <span className="search-result-meta">
                        {job.company_name}
                        {job.location ? ` · ${job.location}` : ""}
                        {job.remote ? " · Remote" : ""}
                      </span>
                      <span className="search-result-source">
                        {SOURCES[job.source] || job.source}
                      </span>
                    </div>
                    <div className="search-result-actions">
                      {job.apply_url && (
                        <a href={job.apply_url} target="_blank" rel="noopener noreferrer" className="search-result-link" title="View on ATS">
                          <ExternalLink size={14} />
                        </a>
                      )}
                      <button
                        type="button"
                        className={isQueued ? "search-queue-btn search-queue-btn-done" : "search-queue-btn"}
                        onClick={() => !isQueued && queueJob(job)}
                        disabled={isQueued || isQueueing}
                      >
                        {isQueueing ? "Applying…" : isQueued ? "✓ Applied" : "Apply"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </>
        )}

        {results === null && !searching && (!suggested || suggested.length === 0) && (
          <div className="search-hint">
            <p>
              Search by role title to find open positions. The job pool
              updates every 4 hours with roles from Greenhouse, Lever,
              and more. Click Apply and we handle the rest.
            </p>
            {targetTitles.length === 0 && (
              <p>
                <strong>Tip:</strong> Set your target roles in{" "}
                <Link href="/onboarding">Profile</Link> to see personalized
                recommendations here.
              </p>
            )}
          </div>
        )}
      </section>
    </ConsoleShell>
  );
}
