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

  // Load already-applied job IDs on mount so user sees "✓ Applied" instantly
  useEffect(() => {
    if (!ready) return;
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      const { data } = await supabase
        .from("applications")
        .select("job_id")
        .eq("user_id", user.id);
      if (data) {
        setQueuedIds(new Set(data.map((r: { job_id: string }) => r.job_id)));
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
          // Already queued
          setQueuedIds((prev) => new Set(prev).add(job.id));
          return;
        }
        throw err;
      }
      setQueuedIds((prev) => new Set(prev).add(job.id));
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

        {results === null && !searching && (
          <div className="search-hint">
            <p>
              The job pool updates every 4 hours with roles from
              Greenhouse, Lever, and more. Search by title and click
              Apply — we handle the rest.
            </p>
          </div>
        )}
      </section>
    </ConsoleShell>
  );
}
