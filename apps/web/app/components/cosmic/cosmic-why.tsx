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
            Instaply started from a familiar problem: job seekers often need to
            send hundreds of applications just to get a handful of replies, and
            the existing tools either charge too much or push personal data into
            someone else&rsquo;s cloud.
          </p>
          <p>
            So this project stays simple on purpose: free, local-first, no
            signup, no paid tier, and fully inspectable under MIT. If it helps
            someone land a role, that&rsquo;s the whole point.
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
            — Instaply open-source maintainers
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
