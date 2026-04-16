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
};

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

      // Load preferences and auto-search recommended jobs
      const { data: prefs } = await supabase
        .from("preferences")
        .select("target_titles, target_locations")
        .eq("user_id", user.id)
        .limit(1);

      if (prefs && prefs[0]) {
        const titles = (prefs[0].target_titles as string[]) || [];
        const locations = (prefs[0].target_locations as string[]) || [];
        setTargetTitles(titles);

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
      setResults((data ?? []) as JobResult[]);
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
