"use client";

import { useEffect, useState } from "react";

type OrbitCard = { name: string; role: string; tag: string };

const cosmicCompanies: OrbitCard[] = [
  { name: "Stripe", role: "SWE Intern", tag: "Applied" },
  { name: "Figma", role: "Design Intern", tag: "In review" },
  { name: "Notion", role: "PM New Grad", tag: "Drafting" },
  { name: "Linear", role: "Frontend", tag: "Applied" },
  { name: "Vercel", role: "DevRel Intern", tag: "Queued" },
  { name: "Anthropic", role: "Research Eng", tag: "Drafting" },
  { name: "Ramp", role: "SWE Intern", tag: "Applied" },
  { name: "Plaid", role: "Backend", tag: "Queued" },
];

export function OrbitScene() {
  const [tick, setTick] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    let raf = 0;
    let last = performance.now();
    const loop = (t: number) => {
      const dt = (t - last) / 1000;
      last = t;
      setTick((v) => v + dt);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [paused]);

  const ringRadii = [180, 280, 380];
  const ringSpeeds = [0.18, -0.12, 0.08];
  const ringTilts = [62, 70, 58];

  return (
    <div
      className="orbit-stage"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="orbit-glow" />
      <div className="orbit-grid" />

      {ringRadii.map((r, ri) => (
        <div
          key={ri}
          className="orbit-ring"
          style={{
            width: r * 2,
            height: r * 2,
            transform: `translate(-50%, -50%) rotateX(${ringTilts[ri]}deg) rotateZ(${tick * ringSpeeds[ri] * 60}deg)`,
          }}
        >
          <div className="orbit-line" style={{ width: r * 2, height: r * 2 }} />
        </div>
      ))}

      {/* Center sun */}
      <div className="orbit-sun">
        <div className="orbit-sun-inner">
          <div className="orbit-sun-pulse" />
          <div className="orbit-sun-label">
            <span className="orbit-sun-dot" />
            <span>agent · live</span>
          </div>
        </div>
      </div>

      {/* Orbiting cards */}
      {cosmicCompanies.map((c, i) => {
        const ringIdx = i % 3;
        const r = ringRadii[ringIdx]!;
        const speed = ringSpeeds[ringIdx]!;
        const tilt = ringTilts[ringIdx]!;
        const perRing = Math.ceil(cosmicCompanies.length / 3);
        const angle = (i / perRing) * Math.PI * 2 + tick * speed;
        const x = Math.cos(angle) * r;
        const y = Math.sin(angle) * r * Math.cos((tilt * Math.PI) / 180);
        const depth = Math.sin(angle) * r * Math.sin((tilt * Math.PI) / 180);
        const scale = 0.7 + (depth + r) / (r * 4);
        return (
          <div
            key={i}
            className="orbit-card"
            style={{
              transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px)) scale(${scale})`,
              zIndex: Math.round(depth + 1000),
              opacity: 0.55 + scale * 0.5,
            }}
          >
            <div className="orbit-card-row">
              <div className="orbit-card-logo">{c.name[0]}</div>
              <div className="orbit-card-meta">
                <div className="orbit-card-name">{c.name}</div>
                <div className="orbit-card-role">{c.role}</div>
              </div>
            </div>
            <div className={`orbit-card-tag tag-${c.tag.toLowerCase().replace(" ", "-")}`}>
              <span className="dot" /> {c.tag}
            </div>
          </div>
        );
      })}

      {/* Floating particles */}
      {Array.from({ length: 40 }).map((_, i) => {
        const seed = i * 137.508;
        const x = (Math.sin(seed) * 0.5 + 0.5) * 100;
        const y = (Math.cos(seed * 1.3) * 0.5 + 0.5) * 100;
        const drift = Math.sin(tick * 0.3 + i) * 8;
        return (
          <div
            key={i}
            className="orbit-particle"
            style={{
              left: `${x}%`,
              top: `${y}%`,
              transform: `translateY(${drift}px)`,
              opacity: 0.2 + (Math.sin(tick + i) + 1) * 0.2,
            }}
          />
        );
      })}
    </div>
  );
}
