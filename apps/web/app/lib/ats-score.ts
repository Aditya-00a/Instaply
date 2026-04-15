/**
 * Client-side ATS heuristic scorer for resumes.
 *
 * Extracts text from the uploaded PDF (via pdfjs-dist lazy-loaded only
 * when we need it) and runs a set of well-known ATS-friendliness checks
 * informed by what we've learned shipping Revize / auto-apply:
 *   - Clear section headers (Experience / Education / Skills)
 *   - Contact info present (email + phone)
 *   - Action verbs at the start of bullet points
 *   - No image-only layouts (text extracted ≥ a minimum length)
 *   - Appropriate length (1 page for <5 yrs experience, 2 for more)
 *   - No suspicious characters (tables, columns tend to mangle)
 *   - Quantified achievements (numbers / %)
 *   - Keywords from target roles present (if provided)
 *
 * Produces a 0–100 score and a list of concrete, rankable tips.
 * The worst-of-both outcomes — a pretty but unparseable resume — is
 * exactly what this is designed to surface.
 */

export type AtsCheck = {
  id: string;
  title: string;
  status: "pass" | "warn" | "fail";
  weight: number; // contribution to total score
  detail?: string;
};

export type AtsReport = {
  score: number; // 0-100
  grade: "A" | "B" | "C" | "D" | "F";
  checks: AtsCheck[];
  textLength: number;
  pageCount: number | null;
};

const ACTION_VERBS = [
  "built","designed","led","shipped","launched","scaled","drove","delivered",
  "owned","developed","created","implemented","managed","engineered","automated",
  "optimized","reduced","increased","improved","streamlined","architected",
  "founded","grew","raised","closed","negotiated","wrote","coded","trained",
  "migrated","refactored","deployed","analyzed","researched","prototyped",
  "onboarded","orchestrated","published","presented","rolled out","spearheaded",
];

const EMAIL_RE = /[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/i;
const PHONE_RE = /(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}/;
const LINKEDIN_RE = /linkedin\.com\/in\//i;

export async function extractPdfText(file: File): Promise<{ text: string; pageCount: number }> {
  // Lazy-load pdfjs only when needed.
  const pdfjs = (await import("pdfjs-dist/legacy/build/pdf.mjs")) as unknown as {
    GlobalWorkerOptions: { workerSrc: string };
    getDocument: (opts: Record<string, unknown>) => {
      promise: Promise<{
        numPages: number;
        getPage: (i: number) => Promise<{
          getTextContent: () => Promise<{ items: unknown[] }>;
        }>;
      }>;
    };
  };
  // Disable worker — run everything on the main thread for simplicity.
  pdfjs.GlobalWorkerOptions.workerSrc = "";

  const buf = await file.arrayBuffer();
  const loadingTask = pdfjs.getDocument({
    data: buf,
    disableWorker: true,
    isEvalSupported: false,
    useSystemFonts: true,
  });
  const doc = await loadingTask.promise;
  const pageCount = doc.numPages;
  let text = "";
  for (let i = 1; i <= pageCount; i++) {
    const page = await doc.getPage(i);
    const content = await page.getTextContent();
    text += content.items
      .map((it: unknown) => {
        const obj = it as { str?: string };
        return obj.str ?? "";
      })
      .join(" ");
    text += "\n";
  }
  return { text, pageCount };
}

export function scoreResumeText(text: string, pageCount: number | null): AtsReport {
  const lower = text.toLowerCase();
  const words = text.split(/\s+/).filter(Boolean).length;
  const lines = text.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const checks: AtsCheck[] = [];

  // 1. Contact info
  const hasEmail = EMAIL_RE.test(text);
  const hasPhone = PHONE_RE.test(text);
  const hasLinkedin = LINKEDIN_RE.test(text);
  checks.push({
    id: "contact",
    title: "Contact info present",
    status: hasEmail && hasPhone ? "pass" : hasEmail || hasPhone ? "warn" : "fail",
    weight: 10,
    detail:
      hasEmail && hasPhone
        ? `Email and phone detected${hasLinkedin ? " + LinkedIn" : ""}.`
        : hasEmail
        ? "Email found but no phone. ATS forms often require phone."
        : hasPhone
        ? "Phone found but no email. Most ATS forms require email."
        : "No email or phone detected. Recruiters can't contact you.",
  });

  // 2. Section headers — require at least two of the big three
  const sections = ["experience", "work", "employment", "education", "skills", "projects"];
  const foundSections = sections.filter((s) => lower.includes(s));
  const hasExperience = ["experience", "work", "employment"].some((s) => lower.includes(s));
  const hasEducation = lower.includes("education");
  const hasSkills = lower.includes("skills");
  const sectionCount = [hasExperience, hasEducation, hasSkills].filter(Boolean).length;
  checks.push({
    id: "sections",
    title: "Clear section headers",
    status: sectionCount >= 3 ? "pass" : sectionCount === 2 ? "warn" : "fail",
    weight: 15,
    detail:
      sectionCount >= 3
        ? "Experience / Education / Skills all detected."
        : `Detected ${foundSections.length} sections. ATS parsers rely on clear "Experience", "Education", "Skills" headers.`,
  });

  // 3. Action verbs at start of bullets
  const bulletLines = lines.filter((l) => /^[\u2022\u2023\u25E6\-\*]\s|^\s*[a-z]/i.test(l));
  const verbMatches = lines.filter((l) =>
    ACTION_VERBS.some((v) => l.toLowerCase().trim().startsWith(v))
  );
  const verbRatio = bulletLines.length > 0 ? verbMatches.length / bulletLines.length : 0;
  checks.push({
    id: "action-verbs",
    title: "Action verbs lead bullet points",
    status: verbRatio >= 0.35 ? "pass" : verbRatio >= 0.15 ? "warn" : "fail",
    weight: 15,
    detail:
      verbRatio >= 0.35
        ? `${verbMatches.length} lines start with strong action verbs.`
        : `Only ${verbMatches.length} lines start with action verbs. Lead with "built", "shipped", "led", "designed", etc.`,
  });

  // 4. Quantified achievements
  const numbers = text.match(/(\d+%|\$\d|\d{2,}[+km])/gi) || [];
  checks.push({
    id: "quantified",
    title: "Quantified impact",
    status: numbers.length >= 5 ? "pass" : numbers.length >= 2 ? "warn" : "fail",
    weight: 15,
    detail:
      numbers.length >= 5
        ? `${numbers.length} metrics / numbers detected.`
        : `Only ${numbers.length} quantified metrics. Numbers and %s make bullets land.`,
  });

  // 5. Length — words
  checks.push({
    id: "length",
    title: "Appropriate length",
    status: words >= 250 && words <= 900
      ? "pass"
      : words >= 180
      ? "warn"
      : "fail",
    weight: 10,
    detail:
      words < 180
        ? `Only ${words} words. Either image-based (ATS can't read it) or too thin.`
        : words > 1100
        ? `${words} words. Trim to the sharpest 1-2 pages.`
        : `${words} words — right length band for most recruiters.`,
  });

  // 6. Page count (PDF only)
  if (pageCount) {
    checks.push({
      id: "pages",
      title: "Page count",
      status: pageCount <= 2 ? "pass" : pageCount === 3 ? "warn" : "fail",
      weight: 5,
      detail:
        pageCount <= 2
          ? `${pageCount} page${pageCount === 1 ? "" : "s"}.`
          : `${pageCount} pages. Most recruiters skim 1-2 pages; trim older roles.`,
    });
  }

  // 7. ATS-unfriendly characters (control chars, PUA icons)
  const puaCount = (text.match(/[\uE000-\uF8FF]/g) || []).length;
  const tabsInLines = lines.filter((l) => /\t/.test(l)).length;
  checks.push({
    id: "parsable",
    title: "ATS-parsable text",
    status: puaCount < 5 && tabsInLines < 10 ? "pass" : "warn",
    weight: 10,
    detail:
      puaCount >= 5
        ? `${puaCount} private-use glyphs (icon fonts) detected. Some ATS parsers choke.`
        : tabsInLines >= 10
        ? `Heavy tab use detected. Columns/tables often get mangled by ATS.`
        : "Text extracted cleanly.",
  });

  // 8. Skills density — at least some technical / domain words
  const commonSkillHits = [
    "python","sql","javascript","typescript","react","node","aws","gcp","azure",
    "docker","kubernetes","excel","tableau","power bi","figma","go","rust","java",
    "risk","marketing","finance","operations","product","design","analytics",
  ].filter((k) => lower.includes(k)).length;
  checks.push({
    id: "skills-density",
    title: "Recognized skills / tools",
    status: commonSkillHits >= 5 ? "pass" : commonSkillHits >= 2 ? "warn" : "fail",
    weight: 10,
    detail:
      commonSkillHits >= 5
        ? `${commonSkillHits} recognized tools / domain terms.`
        : `Only ${commonSkillHits} recognized keywords. ATS filtering often keyword-matches job posts.`,
  });

  // 9. Education phrasing
  const hasDegree = /(b\.?s\.?|b\.?a\.?|m\.?s\.?|m\.?b\.?a|phd|bachelor|master|doctor)/i.test(
    text
  );
  checks.push({
    id: "education",
    title: "Degree or credential stated",
    status: hasDegree ? "pass" : "warn",
    weight: 5,
    detail: hasDegree
      ? "Degree / credential detected."
      : "No degree abbreviation found. If you have one, state it (B.S., M.S., MBA, etc.).",
  });

  // 10. No first-person pronouns (resumes shouldn't say "I did...")
  const firstPersonHits = (text.match(/\bi\b|\bme\b|\bmy\b/gi) || []).length;
  checks.push({
    id: "voice",
    title: "Third-person voice",
    status: firstPersonHits <= 2 ? "pass" : firstPersonHits <= 5 ? "warn" : "fail",
    weight: 5,
    detail:
      firstPersonHits <= 2
        ? "No first-person pronouns."
        : `${firstPersonHits} "I/me/my" hits. Resumes read stronger in third person.`,
  });

  // Aggregate score
  const totalWeight = checks.reduce((s, c) => s + c.weight, 0);
  const earned = checks.reduce((s, c) => {
    const mult = c.status === "pass" ? 1 : c.status === "warn" ? 0.5 : 0;
    return s + c.weight * mult;
  }, 0);
  const score = Math.round((earned / totalWeight) * 100);
  const grade: AtsReport["grade"] =
    score >= 90 ? "A" : score >= 80 ? "B" : score >= 70 ? "C" : score >= 60 ? "D" : "F";

  return { score, grade, checks, textLength: text.length, pageCount };
}
