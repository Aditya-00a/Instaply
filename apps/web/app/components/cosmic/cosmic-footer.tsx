type Props = { repoUrl: string };

export function CosmicFooter({ repoUrl }: Props) {
  return (
    <footer className="cosmic-footer">
      <div className="cosmic-footer-inner">
        <div className="cosmic-footer-brand">
          <div className="cosmic-logo">
            <span className="cosmic-logo-mark">
              <span />
            </span>
            <span>instaply</span>
          </div>
          <p>An open-source MCP for job applications. Free forever. MIT licensed.</p>
        </div>
        <div className="cosmic-footer-cols">
          <div>
            <h5>Product</h5>
            <a href="#how">How it works</a>
            <a href="#stack">Open source</a>
            <a href={`${repoUrl}#roadmap`} target="_blank" rel="noreferrer">
              Roadmap
            </a>
          </div>
          <div>
            <h5>Community</h5>
            <a href={repoUrl} target="_blank" rel="noreferrer">
              GitHub
            </a>
            <a href={`${repoUrl}/issues`} target="_blank" rel="noreferrer">
              Issues
            </a>
            <a
              href={`${repoUrl}/blob/main/CONTRIBUTING.md`}
              target="_blank"
              rel="noreferrer"
            >
              Contributing
            </a>
          </div>
          <div>
            <h5>Trust</h5>
            <a href="/privacy">Privacy</a>
            <a href="/security">Security</a>
            <a
              href={`${repoUrl}/blob/main/LICENSE`}
              target="_blank"
              rel="noreferrer"
            >
              License
            </a>
          </div>
        </div>
      </div>
      <div className="cosmic-footer-bottom">
        <span>© 2026 Aditya Sakhale</span>
        <span>MIT licensed · No cookies · No tracking</span>
      </div>
    </footer>
  );
}
