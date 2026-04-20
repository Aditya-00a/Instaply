"use client";

type Props = { onApply: () => void; repoUrl: string };

export function CosmicCTA({ onApply, repoUrl }: Props) {
  return (
    <section className="cosmic-final">
      <div className="cosmic-final-glow" />
      <div className="cosmic-final-inner">
        <h2>
          Stop refreshing Workday at 1am.
          <br />
          Let the agent do its thing.
        </h2>
        <div className="cosmic-final-actions">
          <button className="cosmic-cta cosmic-cta-lg" onClick={onApply}>
            Install in Claude
          </button>
          <a
            href={repoUrl}
            className="cosmic-link-btn"
            target="_blank"
            rel="noreferrer"
          >
            View on GitHub →
          </a>
        </div>
        <div className="cosmic-final-foot">
          made with care for every student grinding the application game · open source on github
        </div>
      </div>
    </section>
  );
}
