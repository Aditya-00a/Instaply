import type { Metadata } from "next";
import { PublicShell } from "../components/public-shell";
import { ContactForm } from "../components/contact-form";

export const metadata: Metadata = {
  title: "Contact",
  description:
    "Get in touch with Instaply for support, partnerships, press, or anything else. We respond within 48 hours.",
};

const CHANNELS = [
  {
    title: "Support",
    note: "Account issues, billing, application questions.",
    email: "hello@asion.ai",
    sla: "Response within 24 hours, Mon–Fri",
  },
  {
    title: "Sales & partnerships",
    note: "Enterprise pricing, bulk licences, integrations.",
    email: "hello@asion.ai",
    sla: "Response within 48 hours",
  },
  {
    title: "Press & media",
    note: "Interviews, press kit, factual corrections.",
    email: "hello@asion.ai",
    sla: "Response within 3 business days",
  },
  {
    title: "Security reports",
    note: "Responsible disclosure of vulnerabilities.",
    email: "hello@asion.ai",
    sla: "Acknowledged within 48 hours",
  },
];

export default function ContactPage() {
  return (
    <PublicShell>
      <section className="info-hero">
        <div className="info-eyebrow">Contact</div>
        <h1 className="info-title">Talk to us.</h1>
        <p className="info-lede">
          A real human reads every message. Fill the form, or email us
          directly at{" "}
          <a href="mailto:hello@asion.ai" className="link-accent">
            hello@asion.ai
          </a>
          .
        </p>
      </section>

      <section className="contact-grid">
        <ContactForm />

        <aside className="contact-side">
          {CHANNELS.map((c) => (
            <div className="contact-channel" key={c.title}>
              <div className="contact-channel-title">{c.title}</div>
              <p className="contact-channel-note">{c.note}</p>
              <a
                className="contact-channel-mail"
                href={`mailto:${c.email}`}
              >
                {c.email}
              </a>
              <div className="contact-channel-sla">{c.sla}</div>
            </div>
          ))}
        </aside>
      </section>
    </PublicShell>
  );
}
