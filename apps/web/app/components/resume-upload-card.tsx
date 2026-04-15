"use client";

import { Check, FileUp, Loader2, Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type DocRow = {
  id: string;
  file_name: string;
  file_size_bytes: number | null;
  is_primary: boolean;
  created_at: string;
};

type DocKind = "resume" | "cover_letter";

type Props = {
  kind?: DocKind; // default: resume
};

const LABELS: Record<
  DocKind,
  { title: string; emptyTitle: string; description: string; pillEyebrow: string }
> = {
  resume: {
    pillEyebrow: "Resume",
    title: "Your resumes",
    emptyTitle: "Upload your resume to start applying",
    description:
      "PDF or DOCX, up to 10 MB. Instaply uses this to autofill applications on your behalf.",
  },
  cover_letter: {
    pillEyebrow: "Cover letter",
    title: "Your cover letters",
    emptyTitle: "Upload a cover letter template",
    description:
      "Optional. PDF or DOCX, up to 10 MB. Instaply personalizes this per employer before submitting.",
  },
};

export function ResumeUploadCard({ kind = "resume" }: Props) {
  const ready = isSupabaseConfigured();
  const bucket = kind === "cover_letter" ? "cover_letters" : "resumes";
  const table = kind === "cover_letter" ? "cover_letters" : "resumes";

  const [docs, setDocs] = useState<DocRow[] | null>(ready ? null : []);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justUploaded, setJustUploaded] = useState<string | null>(null);

  const copy = LABELS[kind];

  const load = useCallback(async () => {
    if (!ready) return;
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { data, error } = await supabase
      .from(table)
      .select("id, file_name, file_size_bytes, is_primary, created_at")
      .order("created_at", { ascending: false });
    if (!error) setDocs((data ?? []) as DocRow[]);
  }, [ready, table]);

  useEffect(() => {
    load();
  }, [load]);

  const upload = async (file: File) => {
    setError(null);
    if (!ready) {
      setError("Sign in to upload.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("File must be under 10 MB.");
      return;
    }
    const supabase = getBrowserSupabase();
    if (!supabase) return;

    setUploading(true);
    try {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setError("Please sign in first.");
        return;
      }

      const path = `${user.id}/${Date.now()}-${file.name}`;
      const { error: uploadErr } = await supabase.storage
        .from(bucket)
        .upload(path, file, { upsert: false, contentType: file.type });
      if (uploadErr) throw uploadErr;

      const { error: rowErr } = await supabase.from(table).insert({
        user_id: user.id,
        storage_path: path,
        file_name: file.name,
        file_size_bytes: file.size,
        is_primary: (docs?.length ?? 0) === 0,
      });
      if (rowErr) throw rowErr;

      setJustUploaded(file.name);
      setTimeout(() => setJustUploaded(null), 3000);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) upload(f);
    e.target.value = "";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f) upload(f);
  };

  const formatSize = (b: number | null) => {
    if (!b) return "";
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
    return `${(b / (1024 * 1024)).toFixed(1)} MB`;
  };

  const hasDocs = (docs?.length ?? 0) > 0;

  return (
    <article className="glass resume-upload-card">
      <div className="resume-upload-head">
        <div>
          <div className="panel-kicker">{copy.pillEyebrow}</div>
          <h3>{hasDocs ? copy.title : copy.emptyTitle}</h3>
          <p>{copy.description}</p>
        </div>
      </div>

      <label
        className={`resume-dropzone${uploading ? " resume-dropzone-busy" : ""}`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
      >
        <input
          type="file"
          accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={onFile}
          hidden
          disabled={uploading || !ready}
        />
        <div className="resume-dropzone-ico">
          {uploading ? <Loader2 size={22} className="spin" /> : <Upload size={22} />}
        </div>
        <div>
          <strong>
            {uploading
              ? "Uploading…"
              : `Drag a ${kind === "cover_letter" ? "cover letter" : "resume"} here or click to select`}
          </strong>
          <span>Supported: .pdf, .doc, .docx · Max 10 MB</span>
        </div>
      </label>

      {error && <div className="resume-upload-error">{error}</div>}
      {justUploaded && (
        <div className="resume-upload-ok">
          <Check size={14} /> Uploaded {justUploaded}
        </div>
      )}

      {hasDocs && (
        <div className="resume-list">
          {docs!.map((r) => (
            <div className="resume-list-row" key={r.id}>
              <div className="resume-list-icon">
                <FileUp size={14} />
              </div>
              <div className="resume-list-main">
                <strong>
                  {r.file_name}
                  {r.is_primary && <span className="resume-list-tag">Primary</span>}
                </strong>
                <span>
                  {formatSize(r.file_size_bytes)} · uploaded{" "}
                  {new Date(r.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {!ready && (
        <div className="resume-upload-note">
          Sign in to upload. (Preview mode is read-only.)
        </div>
      )}
    </article>
  );
}
