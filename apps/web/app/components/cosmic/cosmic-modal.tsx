"use client";

import { useState } from "react";

type Props = { open: boolean; onClose: () => void };

const MCPB_URL = "https://instaply.asion.ai/instaply.mcpb";
const CLAUDE_CODE_CMD = "claude mcp add instaply -- uvx instaply-mcp";
const JSON_SNIPPET = `{
  "mcpServers": {
    "instaply": {
      "command": "uvx",
      "args": ["instaply-mcp"]
    }
  }
}`;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="cosmic-modal-copy"
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

export function CosmicModal({ open, onClose }: Props) {
  if (!open) return null;
  return (
    <div className="cosmic-modal-overlay" onClick={onClose}>
      <div className="cosmic-modal" onClick={(e) => e.stopPropagation()}>
        <button className="cosmic-modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <div className="cosmic-modal-step">
          <h3>Install Instaply in your client</h3>
          <p className="cosmic-modal-sub">
            Pick the one you use — install takes under a minute.
          </p>
          <div className="cosmic-modal-options">
            {/* Claude Desktop */}
            <a
              className="cosmic-modal-opt"
              href={MCPB_URL}
              target="_blank"
              rel="noreferrer"
            >
              <strong>Claude Desktop</strong>
              <span>Download instaply.mcpb, double-click. Done.</span>
            </a>

            {/* Claude Code */}
            <div className="cosmic-modal-opt">
              <strong>Claude Code</strong>
              <span>Run this in your terminal:</span>
              <div className="cosmic-modal-code">
                {CLAUDE_CODE_CMD}
                <CopyButton text={CLAUDE_CODE_CMD} />
              </div>
            </div>

            {/* Cursor / Codex / Windsurf / Zed */}
            <div className="cosmic-modal-opt">
              <strong>Cursor / Codex / Windsurf / Zed</strong>
              <span>Add to your client&rsquo;s MCP config:</span>
              <div className="cosmic-modal-code">
                {JSON_SNIPPET}
                <CopyButton text={JSON_SNIPPET} />
              </div>
            </div>
          </div>
          <div className="cosmic-modal-foot">
            Don&rsquo;t have a client yet? <code>pip install instaply-mcp</code>{" "}
            works as a fallback —{" "}
            <a
              href="https://pypi.org/project/instaply-mcp/"
              target="_blank"
              rel="noreferrer"
            >
              view on PyPI
            </a>
            .
          </div>
        </div>
      </div>
    </div>
  );
}
