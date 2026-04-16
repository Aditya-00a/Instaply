"use client";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

type App = {
  id: string;
  status: string;
  company_name?: string;
  job_title?: string;
  apply_url?: string;
  queued_at: string;
  completed_at?: string | null;
  confirmed_at?: string | null;
  error_message?: string | null;
};

const STATUS_BADGE: Record<string, string> = {
  queued:       "bg-white/10 text-white/80",
  in_progress:  "bg-blue-500/20 text-blue-300",
  submitted:    "bg-amber-500/20 text-amber-300",
  confirmed:    "bg-emerald-500/20 text-emerald-300",
  failed:       "bg-red-500/20 text-red-300",
  needs_review: "bg-fuchsia-500/20 text-fuchsia-300",
  skipped:      "bg-white/10 text-white/50",
};

export default function ApplicationsPage() {
  const [rows, setRows] = useState<App[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiGet<{ applications: App[] }>("/applications")
      .then((d) => setRows(d.applications))
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="text-red-400">{err}</div>;
  if (!rows) return <div className="text-white/60">Loading…</div>;
  if (rows.length === 0) return <EmptyState />;

  return (
    <div>
      <h1 className="text-3xl font-semibold">Applications</h1>
      <div className="mt-6 overflow-x-auto rounded-lg border border-white/10">
        <table className="w-full text-sm">
          <thead className="text-left text-white/60">
            <tr>
              <th className="px-4 py-3 font-medium">Company</th>
              <th className="px-4 py-3 font-medium">Role</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Queued</th>
              <th className="px-4 py-3 font-medium">Confirmed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className="border-t border-white/5">
                <td className="px-4 py-3">{a.company_name || "—"}</td>
                <td className="px-4 py-3">
                  {a.apply_url ? (
                    <a href={a.apply_url} target="_blank" className="underline text-white/80">
                      {a.job_title || "—"}
                    </a>
                  ) : a.job_title || "—"}
                </td>
                <td className="px-4 py-3">
                  <span className={`rounded px-2 py-0.5 text-xs ${STATUS_BADGE[a.status] || "bg-white/10"}`}>
                    {a.status}
                  </span>
                  {a.error_message && (
                    <div className="mt-1 text-xs text-red-400">{a.error_message}</div>
                  )}
                </td>
                <td className="px-4 py-3 text-white/60">
                  {new Date(a.queued_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-white/60">
                  {a.confirmed_at ? new Date(a.confirmed_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-16">
      <h2 className="text-2xl font-semibold">No applications yet</h2>
      <p className="mt-2 text-white/60">
        Open Claude Desktop and run <span className="font-mono">search_jobs</span> to get started,
        or set up the MCP integration first.
      </p>
      <a href="/settings/mcp" className="mt-6 inline-block underline text-accent">
        Set up MCP →
      </a>
    </div>
  );
}
