"use client";

import { KeyRound, Mail, Trash2, UserX } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

export function AccountSettingsCard() {
  const router = useRouter();
  const ready = isSupabaseConfigured();

  // Password
  const [newPw, setNewPw] = useState("");
  const [pwStatus, setPwStatus] = useState<string | null>(null);
  const [pwLoading, setPwLoading] = useState(false);

  // Email
  const [newEmail, setNewEmail] = useState("");
  const [emailStatus, setEmailStatus] = useState<string | null>(null);
  const [emailLoading, setEmailLoading] = useState(false);

  // Delete
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);

  const changePassword = async () => {
    if (newPw.length < 8) {
      setPwStatus("Password must be at least 8 characters.");
      return;
    }
    if (!ready) { setPwStatus("Not available in preview mode."); return; }
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    setPwLoading(true);
    const { error } = await supabase.auth.updateUser({ password: newPw });
    setPwLoading(false);
    if (error) { setPwStatus(error.message); return; }
    setPwStatus("Password updated.");
    setNewPw("");
    setTimeout(() => setPwStatus(null), 3000);
  };

  const changeEmail = async () => {
    if (!newEmail.includes("@")) {
      setEmailStatus("Enter a valid email.");
      return;
    }
    if (!ready) { setEmailStatus("Not available in preview mode."); return; }
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    setEmailLoading(true);
    const { error } = await supabase.auth.updateUser({ email: newEmail });
    setEmailLoading(false);
    if (error) { setEmailStatus(error.message); return; }
    setEmailStatus("Confirmation email sent to your new address. Check your inbox.");
    setNewEmail("");
  };

  const deleteAccount = async () => {
    if (deleteConfirm !== "DELETE MY ACCOUNT") return;
    if (!ready) return;
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    setDeleting(true);

    // Delete profile (cascades to applications, resumes, etc. via FK)
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) { setDeleting(false); return; }

    await supabase.from("profiles").delete().eq("id", user.id);
    await supabase.auth.signOut();
    router.push("/");
  };

  return (
    <article className="glass settings-card">
      <div className="console-card-header">
        <div>
          <div className="panel-kicker">Account</div>
          <h3>Account management</h3>
        </div>
        <KeyRound size={18} />
      </div>

      {/* Change password */}
      <div className="account-section">
        <div className="account-section-head">
          <KeyRound size={14} />
          <strong>Change password</strong>
        </div>
        <div className="account-section-row">
          <input
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            placeholder="New password (min 8 chars)"
            className="account-input"
            minLength={8}
          />
          <button
            type="button"
            className="btn-secondary"
            onClick={changePassword}
            disabled={pwLoading || newPw.length < 8}
          >
            {pwLoading ? "Updating…" : "Update"}
          </button>
        </div>
        {pwStatus && <div className="account-status">{pwStatus}</div>}
      </div>

      {/* Change email */}
      <div className="account-section">
        <div className="account-section-head">
          <Mail size={14} />
          <strong>Change email</strong>
        </div>
        <div className="account-section-row">
          <input
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="new@email.com"
            className="account-input"
          />
          <button
            type="button"
            className="btn-secondary"
            onClick={changeEmail}
            disabled={emailLoading || !newEmail}
          >
            {emailLoading ? "Sending…" : "Update"}
          </button>
        </div>
        {emailStatus && <div className="account-status">{emailStatus}</div>}
      </div>

      {/* Delete account */}
      <div className="account-section account-section-danger">
        <div className="account-section-head">
          <UserX size={14} />
          <strong>Delete account</strong>
        </div>
        <p className="account-danger-text">
          This permanently deletes your account, all applications,
          resumes, and credits. This action cannot be undone.
        </p>
        <div className="account-section-row">
          <input
            type="text"
            value={deleteConfirm}
            onChange={(e) => setDeleteConfirm(e.target.value)}
            placeholder='Type "DELETE MY ACCOUNT" to confirm'
            className="account-input account-input-danger"
          />
          <button
            type="button"
            className="account-delete-btn"
            onClick={deleteAccount}
            disabled={deleteConfirm !== "DELETE MY ACCOUNT" || deleting}
          >
            <Trash2 size={14} />
            {deleting ? "Deleting…" : "Delete forever"}
          </button>
        </div>
      </div>
    </article>
  );
}
