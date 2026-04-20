"use client";

import { useEffect, useState } from "react";

type Props = { onApply: () => void; repoUrl: string };

export function CosmicNav({ onApply, repoUrl }: Props) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const root = document.querySelector(".cosmic-root");
    if (!root) return;
    const onScroll = () => {
      setScrolled(root.scrollTop > 30);
    };
    root.addEventListener("scroll", onScroll);
    return () => root.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav className={`cosmic-nav ${scrolled ? "scrolled" : ""}`}>
      <div className="cosmic-nav-inner">
        <a className="cosmic-logo" href="#">
          <span className="cosmic-logo-mark">
            <span />
          </span>
          <span>instaply</span>
        </a>
        <div className="cosmic-nav-links">
          <a href="#how">How it works</a>
          <a href="#why">Why free</a>
          <a href="#stack">Open source</a>
          <a href="#faq">FAQ</a>
        </div>
        <div className="cosmic-nav-cta">
          <a href={repoUrl} className="cosmic-ghost" target="_blank" rel="noreferrer">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.4-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2.9-.3 1.9-.4 2.9-.4s2 .1 2.9.4c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.7.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5z" />
            </svg>
            <span>GitHub</span>
          </a>
          <button className="cosmic-cta" onClick={onApply}>
            Install in Claude
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </div>
    </nav>
  );
}
