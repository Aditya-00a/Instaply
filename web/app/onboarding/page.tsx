"use client";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { apiPatch } from "@/lib/api";

type Profile = {
  full_name: string;
  phone: string;
  linkedin_url: string;
  work_auth_status: "us_citizen" | "green_card" | "h1b" | "f1_opt" | "f1_cpt" | "other" | "";
  needs_sponsorship: boolean | null;
  willing_to_relocate: boolean | null;
  current_city: string;
  current_state: string;
};

const EMPTY: Profile = {
  full_name: "", phone: "",
  linkedin_url: "", work_auth_status: "",
  needs_sponsorship: null, willing_to_relocate: null,
  current_city: "", current_state: "",
};

export default function OnboardingPage() {
  const [p, setP] = useState<Profile>(EMPTY);
  const [resume, setResume] = useState<File | null>(null);
  const [existingResume, setExistingResume] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgType, setMsgType] = useState<"ok" | "err">("ok");

  useEffect(() => {
    (async () => {
      const { data: { user } } = await supabase().auth.getUser();
      if (!user) { window.location.href = "/signup"; return; }
      const { data: row } = await supabase()
        .from("profiles").select("*").eq("id", user.id).single();
      if (row) setP({ ...EMPTY, ...row });
      // Check for existing resume
      const { data: resumes } = await supabase()
        .from("resumes").select("file_name").eq("user_id", user.id).eq("is_primary", true).limit(1);
      if (resumes && resumes.length > 0) setExistingResume(resumes[0].file_name);
    })();
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const sb = supabase();
      const { data: { user } } = await sb.auth.getUser();
      if (!user) throw new Error("Not signed in");

      // Upload resume if present
      if (resume) {
        const path = `${user.id}/${Date.now()}-${resume.name}`;
        const { error: upErr } = await sb.storage.from("resumes").upload(path, resume, { upsert: false });
        if (upErr) throw upErr;
        // Clear existing primary resume first (unique constraint)
        await sb.from("resumes").update({ is_primary: false }).eq("user_id", user.id).eq("is_primary", true);
        await sb.from("resumes").insert({
          user_id: user.id, file_name: resume.name,
          storage_path: path, is_primary: true,
        });
        setExistingResume(resume.name);
      }

      // Build the profile patch — only include valid work_auth_status
      const validAuth = ["us_citizen", "green_card", "h1b", "f1_opt", "f1_cpt", "other"];
      const patch: Record<string, unknown> = {
        full_name: p.full_name,
        phone: p.phone,
        linkedin_url: p.linkedin_url || null,
        needs_sponsorship: p.needs_sponsorship,
        willing_to_relocate: p.willing_to_relocate,
        current_city: p.current_city || null,
        current_state: p.current_state || null,
      };
      if (validAuth.includes(p.work_auth_status)) {
        patch.work_auth_status = p.work_auth_status;
      }

      await apiPatch("/profile", patch);
      setMsg("Saved! You're ready to apply — go to Applications or connect Claude Desktop.");
      setMsgType("ok");
    } catch (e: any) {
      setMsg(e.message || "Save failed");
      setMsgType("err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto">
      <h1 className="text-3xl font-semibold">Tell us about you</h1>
      <p className="mt-2 text-sm text-white/60">
        Fill once, apply forever. You can edit later.
      </p>

      <form onSubmit={save} className="mt-8 space-y-5">
        <Field label="Full name" value={p.full_name} onChange={(v) => setP({ ...p, full_name: v })} required />
        <Field label="Phone" value={p.phone} onChange={(v) => setP({ ...p, phone: v })} placeholder="+12125551234" />
        <Field label="LinkedIn URL" value={p.linkedin_url} onChange={(v) => setP({ ...p, linkedin_url: v })} placeholder="https://linkedin.com/in/you" />

        <div className="grid grid-cols-2 gap-4">
          <Field label="City" value={p.current_city} onChange={(v) => setP({ ...p, current_city: v })} placeholder="New York" />
          <Field label="State" value={p.current_state} onChange={(v) => setP({ ...p, current_state: v })} placeholder="NY" />
        </div>

        <Select
          label="US work authorization"
          value={p.work_auth_status}
          onChange={(v) => setP({ ...p, work_auth_status: v as Profile["work_auth_status"] })}
          options={[
            ["", "Select…"],
            ["us_citizen","US Citizen"],
            ["green_card","Green Card"],
            ["h1b","H-1B"],
            ["f1_opt","F-1 OPT"],
            ["f1_cpt","F-1 CPT"],
            ["other","Other work auth"],
          ]}
          required
        />

        <YesNo label="Do you need visa sponsorship now or in the future?"
               value={p.needs_sponsorship} onChange={(v) => setP({ ...p, needs_sponsorship: v })} />
        <YesNo label="Willing to relocate?"
               value={p.willing_to_relocate} onChange={(v) => setP({ ...p, willing_to_relocate: v })} />

        <div>
          <label className="text-sm text-white/70">Resume (PDF or DOCX)</label>
          {existingResume && !resume && (
            <div className="mt-1 text-xs text-emerald-400">✓ Resume on file: {existingResume}</div>
          )}
          <input type="file" accept=".pdf,.docx,.doc" onChange={(e) => setResume(e.target.files?.[0] ?? null)}
                 className="mt-1 block w-full text-sm" />
        </div>

        <button disabled={busy}
                className="rounded-md bg-accent px-5 py-3 text-sm font-medium disabled:opacity-50 w-full">
          {busy ? "Saving…" : "Save profile"}
        </button>
        {msg && (
          <div className={`text-sm ${msgType === "err" ? "text-red-400" : "text-emerald-400"}`}>
            {msg}
          </div>
        )}
      </form>
    </div>
  );
}

function Field({ label, value, onChange, required, placeholder }: { label: string; value: string; onChange: (v: string) => void; required?: boolean; placeholder?: string }) {
  return (
    <label className="block">
      <span className="text-sm text-white/70">{label}</span>
      <input value={value} required={required} placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)}
             className="mt-1 w-full rounded-md bg-white/5 border border-white/10 px-3 py-2 text-sm placeholder:text-white/30" />
    </label>
  );
}
function Select({ label, value, onChange, options, required }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][]; required?: boolean }) {
  return (
    <label className="block">
      <span className="text-sm text-white/70">{label}</span>
      <select value={value} required={required} onChange={(e) => onChange(e.target.value)}
              className="mt-1 w-full rounded-md bg-white/5 border border-white/10 px-3 py-2 text-sm">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}
function YesNo({ label, value, onChange }: { label: string; value: boolean | null; onChange: (v: boolean) => void }) {
  return (
    <div>
      <div className="text-sm text-white/70">{label}</div>
      <div className="mt-2 flex gap-4">
        {[["Yes", true], ["No", false]].map(([l, v]) => (
          <button type="button" key={String(v)} onClick={() => onChange(v as boolean)}
                  className={`rounded-md border px-4 py-2 text-sm ${value === v ? "border-accent bg-accent/10" : "border-white/15"}`}>
            {l as string}
          </button>
        ))}
      </div>
    </div>
  );
}
