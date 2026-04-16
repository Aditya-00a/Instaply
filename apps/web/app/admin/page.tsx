"use client";

import { useEffect, useState } from "react";
import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type UserRow = {
  id: string;
  email: string;
  full_name: string | null;
  needs_sponsorship: boolean;
  created_at: string;
  legal_accepted_at: string | null;
};

type Stat = { label: string; value: string | number };

export default function AdminPage() {
  const ready = isSupabaseConfigured();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [appCounts, setAppCounts] = useState<Record<string, number>>({});
  const [creditBals, setCreditBals] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) {
      setLoading(false);
      return;
    }
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;

      try {
        // Load all profiles
        const { data: profiles, error: pErr } = await supabase
          .from("profiles")
          .select("id, email, full_name, needs_sponsorship, created_at, legal_accepted_at")
          .order("created_at", { ascending: false });
        if (pErr) throw pErr;
        setUsers((profiles ?? []) as UserRow[]);

        // Load application counts per user
        const { data: apps } = await supabase
          .from("applications")
          .select("user_id, status");
        const counts: Record<string, number> = {};
        for (const a of apps ?? []) {
          counts[a.user_id] = (counts[a.user_id] || 0) + 1;
        }
        setAppCounts(counts);

        // Load credit balances via ledger sum
        const { data: ledger } = await supabase
          .from("credit_ledger")
          .select("user_id, delta");
        const bals: Record<string, number> = {};
        for (const l of ledger ?? []) {
          bals[l.user_id] = (bals[l.user_id] || 0) + l.delta;
        }
        setCreditBals(bals);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Load failed");
      } finally {
        setLoading(false);
      }
    })();
  }, [ready]);

  const stats: Stat[] = [
    { label: "Total users", value: users.length },
    { label: "With legal acceptance", value: users.filter((u) => u.legal_accepted_at).length },
    { label: "Total queued apps", value: Object.values(appCounts).reduce((a, b) => a + b, 0) },
    { label: "Total credits issued", value: Object.values(creditBals).reduce((a, b) => a + b, 0) },
  ];

  return (
    <ConsoleShell
      activePath="/admin"
      eyebrow="Admin"
      title="Founder dashboard"
      description="All users, credits, and application counts. Only visible to you."
    >
      {error && (
        <section className="console-section">
          <div className="dashboard-error">{error}</div>
        </section>
      )}

      {loading && (
        <section className="console-section">
          <div className="dashboard-loading">Loading admin data…</div>
        </section>
      )}

      {!loading && (
        <>
          <section className="console-section">
            <div className="app-summary-grid">
              {stats.map((s) => (
                <div className="app-summary-card" key={s.label}>
                  <span>{s.label}</span>
                  <strong>{s.value}</strong>
                </div>
              ))}
            </div>
          </section>

          <section className="console-section">
            <article className="glass app-table-card">
              <div className="app-table-head" style={{ gridTemplateColumns: "2fr 1fr 80px 80px 100px" }}>
                <span>User</span>
                <span>Name</span>
                <span>Credits</span>
                <span>Apps</span>
                <span>Joined</span>
              </div>
              {users.length === 0 ? (
                <div className="workspace-empty">No users yet.</div>
              ) : (
                users.map((u) => (
                  <div
                    className="app-table-row"
                    key={u.id}
                    style={{ gridTemplateColumns: "2fr 1fr 80px 80px 100px" }}
                  >
                    <div className="app-table-cell-role">
                      <strong>{u.email}</strong>
                      <span style={{ fontSize: 10, fontFamily: "var(--font-mono)" }}>
                        {u.id.slice(0, 8)}
                      </span>
                    </div>
                    <span className="app-table-cell-source">{u.full_name || "—"}</span>
                    <span className="app-table-cell-fit" style={{ fontWeight: 600 }}>
                      {creditBals[u.id] ?? 0}
                    </span>
                    <span className="app-table-cell-fit">
                      {appCounts[u.id] ?? 0}
                    </span>
                    <span className="app-table-cell-date">
                      {new Date(u.created_at).toLocaleDateString()}
                    </span>
                  </div>
                ))
              )}
            </article>
          </section>
        </>
      )}
    </ConsoleShell>
  );
}
