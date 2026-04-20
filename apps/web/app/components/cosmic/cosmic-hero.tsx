"use client";

import { OrbitScene } from "./orbit-scene";

type Props = { onApply: () => void };

export function CosmicHero({ onApply }: Props) {
  return (
    <section className="cosmic-hero">
      <OrbitScene />
      <div className="cosmic-hero-overlay">
        <div className="cosmic-hero-pill">
          <span className="pulse-dot" />
          <span>open source · in active development</span>
        </div>
        <h1 className="cosmic-hero-title">
          The job hunt is <em>broken.</em>
          <br />
          We made a friend who hunts <em>for</em> you.
        </h1>
        <p className="cosmic-hero-sub">
          Instaply is a free, open-source MCP server that opens a real browser
          on your laptop, fills out job applications, and pauses for you to
          click submit. It plugs into Claude Desktop, Claude Code, Cursor, and
          any other MCP client.
        </p>
        <div className="cosmic-hero-actions">
          <button className="cosmic-cta cosmic-cta-lg" onClick={onApply}>
            Install in Claude
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
          <a href="#how" className="cosmic-link-btn">
            See how it works ↓
          </a>
        </div>
        <div className="cosmic-hero-meta">
          <div>
            <strong>MIT</strong> licensed
          </div>
          <div className="dot-sep" />
          <div>
            <strong>Local-first</strong>
          </div>
          <div className="dot-sep" />
          <div>
            <strong>Free</strong>, always
          </div>
        </div>
      </div>
    </section>
  );
}
