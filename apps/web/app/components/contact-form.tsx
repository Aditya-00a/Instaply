"use client";

import { useState } from "react";

const TOPICS = [
  "Support",
  "Sales & partnerships",
  "Press & media",
  "Security report",
  "Something else",
] as const;

type Topic = (typeof TOPICS)[number];

/**
 * Contact form — composes a mailto: with subject + body so it works
 * without a backend. When we stand up a real /contact POST endpoint, we
 * can switch to a fetch() submission and keep the same UI.
 */
export function ContactForm() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [topic, setTopic] = useState<Topic>("Support");
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    const subject = `Instaply — ${topic} — ${name || "no name"}`;
    const body = [
      `Name: ${name || "—"}`,
      `Email: ${email || "—"}`,
      `Topic: ${topic}`,
      "",
      "Message:",
      message || "—",
    ].join("\n");

    const href = `mailto:hello@asion.ai?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    window.location.href = href;
    setSent(true);
  };

  return (
    <form className="contact-form" onSubmit={handleSubmit}>
      <div className="contact-form-row">
        <label className="contact-form-field">
          <span>Your name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Jane Doe"
            required
          />
        </label>
        <label className="contact-form-field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@domain.com"
            required
          />
        </label>
      </div>

      <label className="contact-form-field">
        <span>Topic</span>
        <select value={topic} onChange={(e) => setTopic(e.target.value as Topic)}>
          {TOPICS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      <label className="contact-form-field">
        <span>Message</span>
        <textarea
          rows={6}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Tell us what's on your mind. Paste error messages, links, or anything that helps."
          required
        />
      </label>

      <div className="contact-form-actions">
        <button type="submit" className="btn-primary">
          {sent ? "Open email client again" : "Send message"}
        </button>
        <span className="contact-form-hint">
          Opens in your default email app. We reply within 48 hours.
        </span>
      </div>

      {sent && (
        <div className="contact-form-confirm">
          Your email app should have opened with the message pre-filled.
          If nothing happened, email us directly at{" "}
          <a href="mailto:hello@asion.ai">hello@asion.ai</a>.
        </div>
      )}
    </form>
  );
}
