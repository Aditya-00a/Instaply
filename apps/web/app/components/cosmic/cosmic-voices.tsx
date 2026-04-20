type Principle = { q: string; who: string };

const principles: Principle[] = [
  {
    q: "Your résumé and answers stay on your machine. We don't see them, sell them, or store them.",
    who: "local-first",
  },
  {
    q: "Every application is a draft until you say go. The agent assists — it doesn't autopilot.",
    who: "human-in-the-loop",
  },
  {
    q: "No paid tier. No premium features. No 'just $9.99 a month'. The codebase is the product.",
    who: "free, on purpose",
  },
];

export function CosmicVoices() {
  return (
    <section className="cosmic-voices">
      <div className="cosmic-voices-track">
        {[...principles, ...principles].map((q, i) => (
          <figure key={i} className="cosmic-voice">
            <blockquote>&ldquo;{q.q}&rdquo;</blockquote>
            <figcaption>{q.who}</figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
