"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { ConsoleShell } from "../components/console-shell";
import { blockedQuestions } from "../console-data";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type AnswerRow = {
  id: string;
  question_text: string;
  answer_text: string;
  company_slug: string | null;
  times_used: number;
  created_at: string;
};

type State =
  | { kind: "demo" }
  | { kind: "loading" }
  | { kind: "live"; rows: AnswerRow[] }
  | { kind: "error"; message: string };

export default function ReviewPage() {
  const [state, setState] = useState<State>(
    isSupabaseConfigured() ? { kind: "loading" } : { kind: "demo" }
  );

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    let cancelled = false;
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) {
        if (!cancelled) setState({ kind: "demo" });
        return;
      }
      try {
        const {
          data: { user },
        } = await supabase.auth.getUser();
        if (!user) {
          if (!cancelled) setState({ kind: "demo" });
          return;
        }

        // Pull saved answers; column names match 0001_init.sql shape.
        const { data, error } = await supabase
          .from("answers")
          .select("id, question_text, answer_text, company_slug, times_used, created_at")
          .order("created_at", { ascending: false });

        if (error) throw error;
        if (!cancelled) setState({ kind: "live", rows: (data ?? []) as AnswerRow[] });
      } catch (e) {
        if (!cancelled)
          setState({
            kind: "error",
            message: e instanceof Error ? e.message : "Unknown error",
          });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = state.kind === "live" ? state.rows : [];
  const blocked = rows.filter((r) => r.times_used === 0);
  const saved = rows.filter((r) => !r.times_used === 0);

  return (
    <ConsoleShell
      activePath="/review"
      eyebrow=""
      title="Answers"
      description="Saved screening answers Instaply reuses across applications. Edit any to refine future submissions."
      actions={[
        { href: "/onboarding", label: "Edit profile" },
        { href: "/applications", label: "View applications", variant: "secondary" },
      ]}
    >
      {state.kind === "error" && (
        <section className="console-section">
          <div className="dashboard-error">
            Couldn&apos;t load answers — {state.message}
          </div>
        </section>
      )}

      {state.kind === "loading" && (
        <section className="console-section">
          <div className="dashboard-loading">Loading saved answers…</div>
        </section>
      )}

      {state.kind === "live" && rows.length === 0 && (
        <section className="console-section">
          <article className="glass dashboard-empty-hero">
            <div className="dashboard-empty-icon" aria-hidden>
              <Sparkles size={22} />
            </div>
            <div className="dashboard-empty-copy">
              <span className="eyebrow">Nothing to review</span>
              <h2>No saved answers yet.</h2>
              <p>
                When Instaply hits an unfamiliar screening question, it
                surfaces it here so you can answer once and reuse the
                response across applications. Start applying to populate
                this list.
              </p>
            </div>
            <div className="dashboard-empty-actions">
              <Link href="/onboarding" className="btn-primary">
                Complete profile
              </Link>
              <Link href="/applications" className="btn-secondary">
                View applications
              </Link>
            </div>
          </article>
        </section>
      )}

      {state.kind === "live" && rows.length > 0 && (
        <>
          <section className="console-section">
            <div className="app-summary-grid">
              <div className="app-summary-card">
                <span>Total</span>
                <strong>{rows.length}</strong>
              </div>
              <div className="app-summary-card">
                <span>Saved</span>
                <strong>{saved.length}</strong>
              </div>
              <div className="app-summary-card">
                <span>Needs review</span>
                <strong>{blocked.length}</strong>
              </div>
            </div>
          </section>

          {blocked.length > 0 && (
            <section className="console-section">
              <div className="section-intro">
                <div>
                  <p className="eyebrow">Needs review</p>
                  <h2>
                    {blocked.length} answer{blocked.length === 1 ? "" : "s"} waiting on you
                  </h2>
                </div>
              </div>
              <div className="answers-list">
                {blocked.map((r) => (
                  <AnswerRowCard key={r.id} row={r} />
                ))}
              </div>
            </section>
          )}

          <section className="console-section">
            <div className="section-intro">
              <div>
                <p className="eyebrow">Saved</p>
                <h2>Reusable answers</h2>
              </div>
            </div>
            {saved.length === 0 ? (
              <div className="workspace-empty">No reusable answers saved yet.</div>
            ) : (
              <div className="answers-list">
                {saved.map((r) => (
                  <AnswerRowCard key={r.id} row={r} />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {state.kind === "demo" && (
        <section className="console-section">
          <div className="section-intro">
            <div>
              <p className="eyebrow">Preview</p>
              <h2>Sample blocked questions</h2>
            </div>
          </div>
          <div className="answers-list">
            {blockedQuestions.slice(0, 4).map((q, i) => (
              <article className="answers-row" key={i}>
                <div className="answers-row-q">
                  <strong>{q.question}</strong>
                  <p className="answers-row-empty">{q.company}</p>
                </div>
                <span className="app-pill app-pill-warn">Needs answer</span>
              </article>
            ))}
          </div>
        </section>
      )}
    </ConsoleShell>
  );
}

function AnswerRowCard({ row }: { row: AnswerRow }) {
  return (
    <article className="answers-row">
      <div className="answers-row-q">
        <strong>{row.question_text}</strong>
        {row.answer_text ? (
          <p className="answers-row-a">{row.answer_text}</p>
        ) : (
          <p className="answers-row-empty">No answer saved yet.</p>
        )}
        <span className="answers-row-meta">
          {row.company_slug || "—"} ·{" "}
          {new Date(row.created_at).toLocaleDateString()}
        </span>
      </div>
      <span
        className={`app-pill ${row.is_blocked ? "app-pill-warn" : "app-pill-success"}`}
      >
        {row.times_used === 0 ? "Needs review" : `Used ${row.times_used}x`}
      </span>
    </article>
  );
}
