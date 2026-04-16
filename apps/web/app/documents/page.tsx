"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Download, FileText, FileUp, Upload } from "lucide-react";

import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";
import { generatedDocuments } from "../console-data";

type DocRow = {
  id: string;
  file_name: string;
  file_size_bytes: number | null;
  is_primary: boolean;
  created_at: string;
  storage_path: string;
};

type State =
  | { kind: "demo" }
  | { kind: "loading" }
  | { kind: "live"; resumes: DocRow[]; coverLetters: DocRow[] }
  | { kind: "error"; message: string };

function fmtSize(b: number | null): string {
  if (!b) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function DocumentsPage() {
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

        const [{ data: resumesData, error: rErr }, { data: clData, error: clErr }] =
          await Promise.all([
            supabase
              .from("resumes")
              .select("id, file_name, file_size_bytes, is_primary, created_at, storage_path")
              .order("created_at", { ascending: false }),
            supabase
              .from("cover_letters")
              .select("id, file_name, file_size_bytes, is_primary, created_at, storage_path")
              .order("created_at", { ascending: false }),
          ]);

        if (rErr) throw rErr;
        // Cover letters table might not exist yet if 0008 migration hasn't run.
        const cls = clErr ? [] : ((clData ?? []) as DocRow[]);

        if (!cancelled)
          setState({
            kind: "live",
            resumes: (resumesData ?? []) as DocRow[],
            coverLetters: cls,
          });
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

  const handleDownload = async (bucket: string, doc: DocRow) => {
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { data, error } = await supabase.storage
      .from(bucket)
      .createSignedUrl(doc.storage_path, 60);
    if (error || !data?.signedUrl) {
      alert("Could not generate download link: " + (error?.message || "unknown"));
      return;
    }
    window.open(data.signedUrl, "_blank");
  };

  const isDemo = state.kind === "demo";

  return (
    <ConsoleShell
      activePath="/documents"
      eyebrow=""
      title="Documents"
      description="Your uploaded resumes and cover letters. Used to autofill applications."
      actions={[
        { href: "/onboarding", label: "Upload more" },
        { href: "/applications", label: "View applications", variant: "secondary" },
      ]}
    >
      {state.kind === "error" && (
        <section className="console-section">
          <div className="dashboard-error">
            Couldn&apos;t load documents — {state.message}
          </div>
        </section>
      )}

      {state.kind === "loading" && (
        <section className="console-section">
          <div className="dashboard-loading">Loading your documents…</div>
        </section>
      )}

      {state.kind === "live" && (
        <>
          <section className="console-section">
            <div className="section-intro">
              <div>
                <p className="eyebrow">Resumes</p>
                <h2>
                  {state.resumes.length > 0
                    ? `${state.resumes.length} resume${state.resumes.length === 1 ? "" : "s"} on file`
                    : "No resumes yet"}
                </h2>
              </div>
              <Link href="/onboarding" className="btn-secondary">
                <Upload size={14} />
                Upload
              </Link>
            </div>

            {state.resumes.length === 0 ? (
              <EmptyDocCard
                kind="resume"
                ctaHref="/onboarding"
              />
            ) : (
              <div className="doc-grid">
                {state.resumes.map((d) => (
                  <DocCard
                    key={d.id}
                    doc={d}
                    onDownload={() => handleDownload("resumes", d)}
                  />
                ))}
              </div>
            )}
          </section>

          {/* Cover letters — hidden until upload flow is built */}
          {state.coverLetters.length > 0 && (
            <section className="console-section">
              <div className="section-intro">
                <div>
                  <p className="eyebrow">Cover letters</p>
                  <h2>{state.coverLetters.length} on file</h2>
                </div>
              </div>
              <div className="doc-grid">
                {state.coverLetters.map((d) => (
                  <DocCard
                    key={d.id}
                    doc={d}
                    onDownload={() => handleDownload("cover_letters", d)}
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {isDemo && (
        <section className="console-section">
          <div className="section-intro">
            <div>
              <p className="eyebrow">Preview</p>
              <h2>Sample document bundles</h2>
            </div>
          </div>

          <div className="workspace-list">
            {generatedDocuments.map((d) => (
              <div className="workspace-list-row" key={`${d.company}-${d.role}`}>
                <div>
                  <strong>{d.role}</strong>
                  <p>{d.company}</p>
                  <div className="workspace-tag-row">
                    <span className="workspace-tag">Resume: {d.resume}</span>
                    <span className="workspace-tag">Letter: {d.coverLetter}</span>
                  </div>
                </div>
                <span className="workspace-inline-note">{d.updated}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </ConsoleShell>
  );
}

function DocCard({ doc, onDownload }: { doc: DocRow; onDownload: () => void }) {
  return (
    <article className="doc-card">
      <div className="doc-card-ico">
        <FileText size={22} />
      </div>
      <div className="doc-card-body">
        <div className="doc-card-title">
          {doc.file_name}
          {doc.is_primary && <span className="doc-card-tag">Primary</span>}
        </div>
        <div className="doc-card-meta">
          {fmtSize(doc.file_size_bytes)} · uploaded {fmtDate(doc.created_at)}
        </div>
      </div>
      <button type="button" className="doc-card-btn" onClick={onDownload}>
        <Download size={14} />
        Open
      </button>
    </article>
  );
}

function EmptyDocCard({
  kind,
  ctaHref,
}: {
  kind: "resume" | "cover_letter";
  ctaHref: string;
}) {
  const label = kind === "resume" ? "resume" : "cover letter";
  return (
    <div className="doc-empty">
      <div className="doc-empty-ico">
        <FileUp size={28} />
      </div>
      <div className="doc-empty-body">
        <strong>No {label} uploaded yet</strong>
        <p>
          Drop a {label} from the onboarding screen to start applying. You
          can upload multiple versions and mark one as primary.
        </p>
      </div>
      <Link href={ctaHref} className="btn-primary">
        <Upload size={14} />
        Upload {label}
      </Link>
    </div>
  );
}
