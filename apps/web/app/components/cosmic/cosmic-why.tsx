export function CosmicWhy() {
  return (
    <section className="cosmic-why" id="why">
      <div className="cosmic-why-inner">
        <div className="cosmic-why-left">
          <div className="cosmic-eyebrow">
            <span />
            why it&rsquo;s free
          </div>
          <h2>
            Because asking a 20-year-old to pay $30/month to apply to{" "}
            <em>internships</em> is wild.
          </h2>
        </div>
        <div className="cosmic-why-right">
          <p>
            I sent more than 1,300 job applications during my own search. I&rsquo;m
            an international student, I needed visa sponsorship, and the math
            for someone in my spot is brutal — apply to 20× more roles to land
            the same number of replies.
          </p>
          <p>
            So I built the agent I wished I&rsquo;d had, then put it on GitHub
            under MIT. Free, local-first, no signup, no paid tier. The codebase
            is the whole product. If it lands you a job, the only thing I want
            back is you telling a friend.
          </p>
          <p
            style={{
              fontFamily: "var(--font-jetbrains-mono), monospace",
              fontSize: 12,
              color: "#8a8175",
              letterSpacing: "0.04em",
              marginTop: 8,
            }}
          >
            — Aditya Sanjay Sakhale, NYU MS Risk Analytics &rsquo;26
          </p>
          <div className="cosmic-why-tags">
            <span>MIT licensed</span>
            <span>Local-first</span>
            <span>No tracking</span>
            <span>No signup</span>
          </div>
        </div>
      </div>
    </section>
  );
}
