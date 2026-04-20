// Minimal autonomous-first holding page for instaply.asion.ai.
// Replaces the deprecated MCP cosmic landing — anyone landing here from
// the README, HN, or social gets the right pitch + a one-line install.
//
// The cosmic component files in app/components/cosmic/ are now orphan
// files; nothing imports them and Next.js won't ship them in the build.

import "./cosmic.css";

const REPO_URL = "https://github.com/Aditya-00a/Instaply";
const README_URL = `${REPO_URL}#%EF%B8%8F-get-running-in-5-commands`;
const QUICKSTART_URL = `${REPO_URL}/blob/main/QUICKSTART.md`;
const INSTALL_CMD =
  "git clone https://github.com/Aditya-00a/Instaply && cd Instaply/agent && python setup.py";

export default function Home() {
  return (
    <div className="cosmic-root cosmic-landing-min">
      <main className="cosmic-min-wrap">
        <div className="cosmic-eyebrow">
          <span />
          open source · MIT · runs locally
        </div>

        <h1 className="cosmic-min-title">
          Job applications that happen <em>while you sleep.</em>
        </h1>

        <p className="cosmic-min-sub">
          Instaply is a free, local-first agent that discovers fresh
          jobs across Greenhouse, Lever, and SmartRecruiters, scores
          them against your profile, drafts tailored applications, and
          queues them. You wake up to a queue ready to review.
          <br />
          Your laptop. Your browser. Your data. No servers, no signup,
          no telemetry.
        </p>

        <div className="cosmic-min-install">
          <code>{INSTALL_CMD}</code>
        </div>

        <div className="cosmic-min-actions">
          <a
            href={REPO_URL}
            className="cosmic-cta cosmic-cta-lg"
            target="_blank"
            rel="noreferrer"
          >
            View on GitHub →
          </a>
          <a
            href={QUICKSTART_URL}
            className="cosmic-link-btn"
            target="_blank"
            rel="noreferrer"
          >
            Quickstart guide
          </a>
        </div>

        <div className="cosmic-min-trust">
          <div>
            <strong>MIT</strong>
            <span>licensed</span>
          </div>
          <div className="cosmic-min-trust-sep" />
          <div>
            <strong>Local</strong>
            <span>by default</span>
          </div>
          <div className="cosmic-min-trust-sep" />
          <div>
            <strong>Free</strong>
            <span>forever</span>
          </div>
        </div>

        <footer className="cosmic-min-foot">
          Built with Python, Playwright, and a refusal to charge anyone
          $30/month to fill a form.
        </footer>
      </main>
    </div>
  );
}
