import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "../components/public-shell";

export const metadata: Metadata = {
  title: "Integrations",
  description:
    "Use Instaply through the web dashboard, the Claude Desktop MCP integration, or the ChatGPT Connector.",
};

const SURFACES = [
  {
    name: "Web dashboard",
    url: "https://instaply.asion.ai",
    who: "The default. Browser-based, works everywhere.",
    setup: [
      "Sign up at instaply.asion.ai",
      "Upload your resume and fill your profile",
      "Connect a Gmail inbox for confirmation verification",
      "Turn on auto-apply and only step in for Needs attention rows",
    ],
  },
  {
    name: "Claude Desktop MCP",
    url: "https://instaply.asion.ai/sign-in",
    who: "For people who live inside Claude Desktop and want to manage applications alongside their other work.",
    setup: [
      "Create an account on the web first",
      "Generate an MCP token from Settings → API tokens",
      "In Claude Desktop config, add the Instaply MCP server with your token",
      "Restart Claude; the instaply_* tools are now available in every chat",
    ],
  },
  {
    name: "ChatGPT Connector",
    url: "https://instaply.asion.ai/sign-in",
    who: "For ChatGPT Plus / Team users who prefer GPT as their workspace.",
    setup: [
      "Create an account on the web first",
      "Generate an API token from Settings → API tokens",
      "Install the Instaply Connector from the ChatGPT Connector directory",
      "Paste your token when prompted and authorize",
    ],
  },
];

export default function IntegrationsPage() {
  return (
    <PublicShell>
      <section className="info-hero">
        <div className="info-eyebrow">Integrations</div>
        <h1 className="info-title">
          Use Instaply from wherever you work.
        </h1>
        <p className="info-lede">
          Every surface talks to the same backend and the same credit
          balance. Switch freely.
        </p>
      </section>

      {SURFACES.map((s) => (
        <section className="info-section" key={s.name}>
          <h2>{s.name}</h2>
          <p className="info-body">{s.who}</p>
          <ol className="info-steps">
            {s.setup.map((step, i) => (
              <li className="info-step" key={step}>
                <div className="info-step-num">{i + 1}</div>
                <div className="info-step-body">
                  <p>{step}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}

      <section className="info-cta-row">
        <Link href="/sign-in" className="landing-cta">
          Get your token
        </Link>
        <a href="mailto:hello@asion.ai" className="landing-cta landing-cta-secondary">
          Contact for enterprise setup
        </a>
      </section>
    </PublicShell>
  );
}
