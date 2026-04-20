export function CosmicStack() {
  return (
    <section className="cosmic-stack" id="stack">
      <div className="cosmic-section-head">
        <div className="cosmic-eyebrow">
          <span />
          open source
        </div>
        <h2>Built in the open. Ugly commits and all.</h2>
      </div>
      <div className="cosmic-stack-grid">
        <div className="cosmic-stack-main">
          <div className="cosmic-terminal">
            <div className="term-bar">
              <span />
              <span />
              <span />
              <div className="term-title">~/instaply · main</div>
            </div>
            <div className="term-body">
              <div>
                <span className="term-prompt">$</span> claude mcp add instaply -- uvx instaply-mcp
              </div>
              <div className="term-out">Connecting... ✓</div>
              <div>
                <span className="term-prompt">$</span> # in Claude:
              </div>
              <div className="term-out">
                &gt; import my resume from ~/Desktop/cv.pdf
              </div>
              <div className="term-out">
                ✓ Imported. Saved 12 skills, inferred role targets.
              </div>
              <div className="term-out">
                &gt; find data analyst roles, US, no sponsorship
              </div>
              <div className="term-out">
                → <span className="term-ok">5 matches</span>
              </div>
              <div className="term-out">&gt; apply to #2</div>
              <div className="term-out">→ opening Chrome on your laptop…</div>
              <div className="term-out">→ filled 14 fields. paused at captcha.</div>
              <div className="term-out term-blink">▍</div>
            </div>
          </div>
        </div>
        <div className="cosmic-stack-side">
          <div className="cosmic-stat">
            <div className="cosmic-stat-num">MIT</div>
            <div className="cosmic-stat-label">License</div>
          </div>
          <div className="cosmic-stat">
            <div className="cosmic-stat-num">MCP</div>
            <div className="cosmic-stat-label">Native</div>
          </div>
          <div className="cosmic-stat">
            <div className="cosmic-stat-num">BYO</div>
            <div className="cosmic-stat-label">Chrome</div>
          </div>
          <div className="cosmic-stat">
            <div className="cosmic-stat-num">Local</div>
            <div className="cosmic-stat-label">First, by default</div>
          </div>
        </div>
      </div>
    </section>
  );
}
