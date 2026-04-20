type Step = { n: string; t: string; d: string };

const steps: Step[] = [
  {
    n: "01",
    t: "Install once",
    d: "One click on Claude Desktop, or `uvx instaply-mcp` for Claude Code. ~30 seconds.",
  },
  {
    n: "02",
    t: "Import your resume",
    d: "Tell Claude to import your PDF or DOCX. Instaply reads it and saves your profile locally — never leaves your machine.",
  },
  {
    n: "03",
    t: "Search + apply from chat",
    d: "Ask Claude to find roles. Pick one. It opens Chrome, fills the form, pauses for captcha and your final submit.",
  },
  {
    n: "04",
    t: "Save answers once",
    d: "Teach it a screening answer once and it'll reuse it on every future application that asks the same thing.",
  },
];

export function CosmicHow() {
  return (
    <section className="cosmic-how" id="how">
      <div className="cosmic-section-head">
        <div className="cosmic-eyebrow">
          <span />
          how it works
        </div>
        <h2>Four steps. Then go to class.</h2>
      </div>
      <div className="cosmic-how-grid">
        {steps.map((s) => (
          <div className="cosmic-how-card" key={s.n}>
            <div className="cosmic-how-num">{s.n}</div>
            <div className="cosmic-how-line" />
            <h3>{s.t}</h3>
            <p>{s.d}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
