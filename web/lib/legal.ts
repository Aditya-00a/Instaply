import fs from "node:fs";
import path from "node:path";

/**
 * Reads a markdown file from legal/.
 * Files are kept in web/legal/ (Docker build) or ../legal/ (monorepo root, local dev).
 * We check both locations so local dev and prod work without changes.
 */
export function readLegalDoc(name: "terms" | "privacy" | "refund"): string {
  const cwd = process.cwd();

  // Docker / standalone: legal/ lives inside web/
  const localPath = path.join(cwd, "legal", `${name}.md`);
  if (fs.existsSync(localPath)) {
    return fs.readFileSync(localPath, "utf-8");
  }

  // Local monorepo dev: legal/ is a sibling of web/
  const monoPath = path.join(cwd, "..", "legal", `${name}.md`);
  return fs.readFileSync(monoPath, "utf-8");
}
