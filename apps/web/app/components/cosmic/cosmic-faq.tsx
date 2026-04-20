"use client";

import { useState } from "react";

type Item = { q: string; a: string };

const items: Item[] = [
  {
    q: "Is it actually free?",
    a: "Yes. MIT-licensed, no paid tier, no upsell. The MCP server runs on your machine and is the whole product. If your model provider charges you for tokens, that's between you and them — Instaply takes nothing.",
  },
  {
    q: "Won't I get caught using AI to apply?",
    a: "Instaply pauses at every captcha and lets you click the final Submit yourself. You see and approve everything before it lands. Nothing goes out without you.",
  },
  {
    q: "What about my data?",
    a: "Lives in ~/.instaply/data.db — a SQLite file on your laptop. No Instaply server is in the loop. Delete the folder to factory-reset.",
  },
  {
    q: "Which job boards are supported?",
    a: "Greenhouse, Lever, and SmartRecruiters today. Workday, Ashby, and iCIMS are on the roadmap. PRs welcome.",
  },
  {
    q: "Can I contribute?",
    a: "Yes — repo is on GitHub, see CONTRIBUTING.md for good first issues.",
  },
];

export function CosmicFAQ() {
  const [open, setOpen] = useState(0);
  return (
    <section className="cosmic-faq" id="faq">
      <div className="cosmic-section-head">
        <div className="cosmic-eyebrow">
          <span />
          questions
        </div>
        <h2>The honest answers.</h2>
      </div>
      <div className="cosmic-faq-list">
        {items.map((it, i) => (
          <div
            key={i}
            className={`cosmic-faq-item ${open === i ? "open" : ""}`}
            onClick={() => setOpen(open === i ? -1 : i)}
          >
            <div className="cosmic-faq-q">
              <span>{it.q}</span>
              <span className="cosmic-faq-plus">{open === i ? "–" : "+"}</span>
            </div>
            <div className="cosmic-faq-a">
              <p>{it.a}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
