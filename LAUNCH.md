# Launching Instaply

A pragmatic step-by-step for shipping this to the world. Two parts:

1. **Make the GitHub repo "presentable"** — the polish a maintainer ships before the first eyeballs land.
2. **The actual announcement** — where to post, in what order, with what copy.

---

## Part 1 — GitHub setup (do this first, in one sitting)

### Repo settings (https://github.com/Aditya-00a/Instaply/settings)

- [ ] **About** (top-right of the repo page → gear icon):
  - **Description:** `Free, local-first job-application agent. MCP server for Claude Desktop / Claude Code / Cursor / Codex / Windsurf / Zed. Plus a background loop that applies while you sleep.`
  - **Website:** `https://instaply.asion.ai`
  - **Topics:** `mcp` `claude` `claude-desktop` `claude-code` `model-context-protocol` `job-search` `job-application` `automation` `playwright` `ats` `greenhouse` `lever` `python` `ollama` `local-first` `open-source` `students`
  - Tick: **Releases**, **Packages**, **Deployments** (so they show in the right rail)

- [ ] **Features** (Settings → General → Features):
  - Wikis: **off** (everything is in `docs/` + README)
  - Issues: **on**
  - Discussions: **on** (bigger community surface than issues, lower friction)
  - Projects: **on** (use one for the public roadmap)

- [ ] **Branches** (Settings → Branches):
  - Branch protection on `main`:
    - Require PR before merging
    - Require status checks to pass (the GitHub Action `publish-mcp.yml` ideally)
    - Require linear history (no merge commits)
    - Allow force pushes from admins only
  - Default branch is `main`

- [ ] **Pages** (Settings → Pages):
  - Source: deploy from `main` / `/docs` (if you want a docs site later) — skip for v1
  - The marketing site is already on Vercel at `instaply.asion.ai`, that's enough

- [ ] **Secrets** (Settings → Secrets and variables → Actions):
  - You don't need any — PyPI publish uses Trusted Publishing (already set up)

- [ ] **Sponsors** (Settings → Sponsors → Set up GitHub Sponsors):
  - Worth doing even if you don't expect dollars — it adds the "Sponsor" button at the top of the repo, which is a soft "you can support this" signal
  - Enable, then add a small message ("Star the repo and tell a student. Or sponsor a coffee if you can.")
  - Update `.github/FUNDING.yml` to point at your Sponsors username (it already exists in the repo)

### Files already present (verify they're current)

- [x] `LICENSE` — MIT
- [x] `README.md` — beautified, install-cards layout
- [x] `CONTRIBUTING.md` — verify it doesn't have personal email; it should send people to issues, not your inbox
- [x] `CODE_OF_CONDUCT.md` — Contributor Covenant
- [x] `SECURITY.md` — verify the contact email is project-level, not personal (`security@instaply.asion.ai` if you want a project alias, otherwise GitHub Security Advisories)
- [x] `CHANGELOG.md` — keep updated per release
- [x] `.github/ISSUE_TEMPLATE/*` — bug, feature, "got the job"
- [x] `.github/PULL_REQUEST_TEMPLATE.md`
- [x] `.github/workflows/publish-mcp.yml` — auto-publishes to PyPI on tag push
- [x] `.github/FUNDING.yml` — Sponsors button

### Pin issues + create the public roadmap

- [ ] Create 3-5 **good first issues** (label them `good first issue`):
  - "Add Workday adapter" (in beta)
  - "Add Ashby adapter"
  - "Add iCIMS adapter"
  - "Make autofill EEO defaults profile-driven (post-lift TODO)"
  - "Build a simple `localhost:3001` review-queue dashboard"
- [ ] Pin those issues to the repo (Issues page → "..." → Pin issue)
- [ ] Create a **Project (beta)** named "Instaply Roadmap" with three columns: Now / Next / Later. Throw the roadmap items in.

### Pre-launch sanity check

```bash
# 1. The MCP package installs
pip install instaply-mcp
python -m instaply_mcp --help    # any output is good; no ImportError

# 2. The .mcpb is downloadable
curl -I https://instaply.asion.ai/instaply.mcpb   # expect HTTP 200
curl -I https://github.com/Aditya-00a/Instaply/releases/download/v0.4.3/instaply.mcpb

# 3. The agent setup wizard runs
cd agent && python setup.py --detect-only   # prints JSON, exits 0

# 4. The README renders cleanly
# Open https://github.com/Aditya-00a/Instaply in an incognito window — the
# install grid table should look right, the architecture SVG should load,
# the star history chart should show.
```

If any of those fail, fix before announcing. **The single biggest mistake is launching with a broken install path** — people try once, fail, and never come back.

---

## Part 2 — The announcement (in launch order)

### T−7 days: prep

- [ ] Record a **30–60s screen capture** of the chat-style demo. Tools: Loom, OBS, QuickTime, Cleanshot. You're looking for: open Claude Desktop → Instaply tools listed → "import resume from …" → "find data analyst roles" → "apply to #2" → browser opens, gets to captcha, you solve it, click submit, "done", logged.
- [ ] Convert to a GIF (≤ 8 MB so it embeds inline on Twitter/Reddit/HN). `ffmpeg -i demo.mp4 -vf "fps=12,scale=720:-1" -loop 0 demo.gif`
- [ ] Write the announcement copy ahead of time (drafts below). Don't write it the morning of.
- [ ] Pick the **launch day**: Tuesday, Wednesday, or Thursday. Avoid Mondays (people are buried) and Fridays (post gets buried over the weekend). 8–10 AM Eastern is the HN sweet spot.

### T−1 day: dry runs

- [ ] Submit the package to **Awesome MCP Servers** (the canonical community list): https://github.com/punkpeye/awesome-mcp-servers — open a PR adding Instaply under the Productivity section
- [ ] Send a quiet DM to 3–5 friends/peers who'll +1 and comment thoughtfully on launch day. Not vote-rigging, just: a post with 0 comments looks dead.

### Launch day order (start at 8 AM ET)

1. **Hacker News (first, biggest leverage)**
   - URL: https://news.ycombinator.com/submit
   - Title: **`Show HN: Instaply – local-first job-application agent for Claude Desktop`**
   - URL field: `https://github.com/Aditya-00a/Instaply` (not the marketing site — HN trusts repos more)
   - First comment (post immediately yourself, anchors the discussion):
     > I built this after sending 1,300+ applications during my own job search. The thing that broke me wasn't the rejections — it was the 30 minutes per application typing the same answers. Existing tools want $30–80/mo for what is fundamentally a form-filling problem.
     >
     > Instaply ships as an MCP server (so it plugs into Claude Desktop / Claude Code / Cursor / Codex / Windsurf / Zed in one click) and a Python autonomous loop you can run as a scheduled task. Both share the same engine — 39 deterministic field rules + an LLM fallback for the gnarly ones — and run entirely on your laptop with your IP and your cookies. There's no Instaply server in the loop.
     >
     > Free, MIT, no telemetry, no signup. Setup wizard auto-detects your hardware and recommends the right local Ollama model.
     >
     > Happy to answer anything about the architecture, the autofill rules, the captcha-pause-for-human design, or the wider question of "should this even exist."

2. **Reddit (immediately after, in this order — don't shotgun all at once)**
   - **r/LocalLLaMA** — this audience LOVES "auto-installs Ollama, picks the right model for your hardware". Title: `Free local-first job-application agent (MCP for Claude, picks the right Ollama model for your hardware)`
   - **r/ClaudeAI** — title: `I built an MCP server that fills out and submits job applications for you (free, MIT, runs locally)`
   - **r/cscareerquestions** — title: `Open-sourced the job-application agent I built after 1,300 apps`. **Read the rules before posting** — they're strict about self-promotion. Frame as "sharing what I built", not "use my product".
   - **r/csMajors** + **r/internships** — same post, slightly more student-focused
   - Wait 24 hours before more subreddit cross-posts (mods downrank cross-spam)

3. **Twitter/X (about an hour after HN)**
   - Thread of 5–7 tweets:
     1. Hook: "I sent 1,300 job applications last fall. Then I built a tool that does it for me. Free + open source. Here's what it looks like." + the GIF
     2. The MCP angle: install in Claude Desktop in one click, talk to it normally
     3. The autonomous angle: also runs as a background loop while you sleep
     4. The privacy angle: zero servers in the loop, your IP, your cookies, captcha walls don't fire
     5. The cost angle: $0 forever, MIT, picks the right local Ollama model for your hardware
     6. The link to GitHub + a "star if you've ever cried over Workday" CTA
     7. Tag `@AnthropicAI` and `@simonw` — they amplify good MCP work
   - Pin the thread to your profile

4. **LinkedIn (mid-afternoon, different audience)**
   - Long-form post, story-shaped:
     - Open: "1,300 job applications. Most never reached a human."
     - Middle: what you built and why
     - End: the link, ask people to share with anyone job-searching
   - Don't gate-keep with "comment to get the link" — ick, but also LinkedIn deboosts those now

5. **Indie Hackers (next day, post-launch retro)**
   - Different angle: "I tried turning this into a paid SaaS. Then I gave it away. Here's what I learned."
   - Indie Hackers loves the OSS-pivot story arc

6. **MCP-specific channels (parallel, low-effort)**
   - Awesome MCP Servers PR (already submitted T−1)
   - Anthropic's MCP Discord (#showcase channel) — single message with the GitHub link + screenshot
   - Tag the official `@AnthropicAI` MCP team on Twitter/X

### Day 2–7: the long tail

- [ ] **Reply to every single comment** on every platform for the first 48 hours. People can tell when a maintainer is present.
- [ ] If HN goes well (≥ 100 upvotes), expect **a wave of issues**. Triage them. The first 20 issues set the tone for the whole project — be warm, ship fixes fast, label generously.
- [ ] **Write a blog post** by day 7: "What I learned launching Instaply on Hacker News". Cross-post to dev.to, HackerNoon, your own site. This becomes evergreen SEO.
- [ ] Submit to **Product Hunt** on day ~7 if (and only if) you have a polished landing page with screenshots. PH's audience is product folks, less technical than HN.

### What "success" looks like (rough thresholds)

- HN: 100+ upvotes = a real launch. 300+ = front-page story. 1,000+ = inbox-flooding.
- GitHub: 100 stars in week 1 is healthy for a niche tool. 1,000 in week 1 means it landed.
- The metric you actually care about (per the README): the first **"Got the job"** issue. That's the one to celebrate.

---

## Things to NOT do

- ❌ Don't post on multiple subreddits simultaneously. Mods see it instantly.
- ❌ Don't ask friends to upvote on HN — moderators detect coordinated voting and kill the post.
- ❌ Don't launch with a broken install link. Test from an incognito browser on a fresh machine if you can borrow one.
- ❌ Don't oversell. The README's "1,300 applications, free forever" framing is honest. Keep it that honest in every channel.
- ❌ Don't ignore negative comments. Engage them like a maintainer who cares about getting it right. The thoughtful response to a "this is just a worse RecruitBot" comment is what wins skeptics.

---

## A small note for after launch

When the issues start coming in, the first thing people will hit is the demographic-default TODOs in `agent/backend/services/autofill.py` and the missing `data/profile.json` schema. The post-lift integration work I left for "later" is now the work for "this week". The setup wizard handles Ollama; the second piece is a **profile wizard** that asks the user 20 questions and writes a complete `profile.json` + `master-resume.json`. That's the next ship after launch.

Good luck. 💛
