import fs from "node:fs";
import path from "node:path";

/**
 * Reads a legal markdown file from apps/web/content/legal/.
 * Used by the /terms, /privacy, /refund pages (server components).
 *
 * The .md files are the canonical source of truth — edit them, not the
 * page components.
 */
export function readLegalDoc(
  name: "terms" | "privacy" | "refund"
): string {
  const p = path.join(process.cwd(), "content", "legal", `${name}.md`);
  return fs.readFileSync(p, "utf-8");
}
