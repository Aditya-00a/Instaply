# Launching Instaply

A pragmatic step-by-step for shipping this to the world. Two parts:

1. **Make the GitHub repo "presentable"** — the polish a maintainer ships before the first eyeballs land.
2. **The actual announcement** — where to post, in what order, with what copy.

---

## Part 1 — GitHub setup (do this first, in one sitting)

### Repo settings (https://github.com/Aditya-00a/Instaply/settings)

- [ ] **About** (top-right of the repo page → gear icon):
  - **Description:** `Free, open-source job-application agent that runs on your laptop while you sleep. Discovers, scores, and drafts applications across Greenhouse / Lever / SmartRecruiters. Pauses for you to solve captcha and click submit.`
  - **Website:** `https://instaply.asion.ai`
  - **Topics:** `job-search` `job-application` `automation` `playwright` `ats` `greenhouse` `lever` `smartrecruiters` `python` `ollama` `local-first` `local-llm` `open-source` `students` `autonomous-agent`
  - Tick: **Releases**, **Packages**, **Deployments** (so they show in the right rail)

- [ ] **Features** (Settings → General → Features):
  - Wikis: **off** (everything is in the README + QUICKSTART)
  - Issues: **on**
  - Discussions: **on** (bigger community surface than issues, lower friction)
  - Projects: **on** (use one for the public roadmap)

- [ ] **Branches** (Settings → Branches):
  - Branch protection on `main`:
    - Require PR before merging
    - Require status checks to pass (once you add CI)
    - Require linear history (no merge commits)
    - Allow force pushes from admins only
  - Default branch is `main`

- [ ] **Pages** (Settings → Pages):
  - The marketing site is on Vercel at `instaply.asion.ai`, so you don't need GitHub Pages

- [ ] **Sponsors** (Settings → Sponsors → Set up GitHub Sponsors):
  - Worth doing even if you don't expect dollars — adds the "Sponsor" button at the top of the repo, soft "you can support this" signal
  - Enable, then add a small message ("Star the repo and tell a student. Or sponsor a coffee if you can.")
  - Update `.github/FUNDING.yml` to point at your Sponsors username (it already exists in the repo)

### Files already present (verify they're current)

- [x] `LICENSE` — MIT
- [x] `README.md` — autonomous-first, with the install grid + architecture diagram
- [x] `QUICKSTART.md` — the `python setup.py` walkthrough
- [x] `CONTRIBUTING.md` — verify it doesn't have personal email; should send people to issues
- [x] `CODE_OF_CONDUCT.md` — Contributor Covenant
- [x] `SECURITY.md` — verify the contact is project-level, not personal (use GitHub Security Advisories)
- [x] `CHANGELOG.md` — keep updated per release
- [x] `LAUNCH.md` — this file
- [x] `.github/ISSUE_TEMPLATE/*` — bug, feature, "got the job"
- [x] `.github/PULL_REQUEST_TEMPLATE.md`
- [x] `.github/FUNDING.yml` — Sponsors button
- [x] `.github/banner.svg` / `architecture.svg` / `demo.svg` — refreshed for the autonomous flow

### Pin issues + create the public roadmap

- [ ] Create 5 **good first issues** (label them `good first issue`):
  - "Profile wizard: replace manual `data/profile.json` editing with an interactive setup"
  - "Add Workday adapter (in beta — needs hardening against Workday's anti-automation)"
  - "Add Ashby adapter"
  - "Add iCIMS adapter"
  - "macOS launchd + Linux cron equivalents of `setup-scheduler.ps1`"
  - "Local web review dashboard at `localhost:3001`"
- [ ] Pin those issues to the repo (Issues page → "..." → Pin issue)
- [ ] Create a **Project (beta)** named "Instaply Roadmap" with three columns: Now / Next / Later. Throw the roadmap items in.

### Pre-launch sanity check

```bash
# 1. Fresh clone works on a clean machine (try a friend's laptop or a VM)
git clone https://github.com/Aditya-00a/Instaply
cd Instaply/agent

# 2. Setup wizard runs
python setup.py --detect-only   # prints JSON, exits 0

# 3. Imports clean
python -c "import sys; sys.path.insert(0,'.'); import importlib.util; \
  spec=importlib.util.spec_from_file_location('run','run.py'); \
  m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); \
  print('run.py imports clean')"

# 4. The README renders cleanly on the public repo page
# Open https://github.com/Aditya-00a/Instaply in an incognito window —
# the install block, architecture SVG, demo SVG, comparison table,
# and star history chart should all load.
```

If any of those fail, fix before announcing. **The single biggest mistake
is launching with a broken install path** — people try once, fail, and
never come back.

---

## Part 2 — The announcement (in launch order)

### T−7 days: prep

- [ ] Record a **30–60s screen capture** of the setup wizard + the agent finding + drafting jobs. Tools: Loom, OBS, QuickTime, Cleanshot. Money shot: `python setup.py` → wizard detects hardware → installs Ollama → recommends model → "Hardware: M3 Max, 36 GB · Recommended: Qwen3-Coder 30B" → `python run.py` → loop ticks → "12 strong matches queued for review."
- [ ] Convert to a GIF (≤ 8 MB so it embeds inline on Twitter/Reddit/HN). `ffmpeg -i demo.mp4 -vf "fps=12,scale=720:-1" -loop 0 demo.gif`
- [ ] Write the announcement copy ahead of time (drafts below). Don't write it the morning of.
- [ ] Pick the **launch day**: Tuesday, Wednesday, or Thursday. Avoid Mondays (people are buried) and Fridays (post gets buried over the weekend). 8–10 AM Eastern is the HN sweet spot.

### T−1 day: dry runs

- [ ] Send a quiet DM to 3–5 friends/peers who'll +1 and comment thoughtfully on launch day. Not vote-rigging, just: a post with 0 comments looks dead.
- [ ] Test the setup wizard on a machine that has *never* run it before (a fresh VM or a friend's laptop). The wizard's first impression is the whole product.

### Launch day order (start at 8 AM ET)

1. **Hacker News (first, biggest leverage)**
   - URL: https://news.ycombinator.com/submit
   - Title: **`Show HN: Instaply – open-source job-application agent that runs locally`**
   - URL field: `https://github.com/Aditya-00a/Instaply` (not the marketing site — HN trusts repos more)
   - First comment (post immediately yourself, anchors the discussion):
     > I built this after sending 1,300+ applications during my own job search. The thing that broke me wasn't the rejections — it was the 30 minutes per application typing the same answers, then doing it 1,300 times. Existing automation tools want $30–80/mo for what is fundamentally a form-filling problem, and they do it from a datacenter IP that gets bot-detected within seconds.
     >
     > Instaply runs as a background loop on your own laptop. One command sets it up — `python setup.py` detects your hardware, installs Ollama if you don't have it, picks the right local model for your GPU/RAM (3B for tiny laptops up to 70B for workstations), and writes your config. Then it discovers fresh jobs across Greenhouse / Lever / SmartRecruiters / JobSpy sources, scores them against your profile (39 deterministic field rules + LLM fallback), and drafts tailored applications into a queue. You wake up to 12 drafts ready to review.
     >
     > It pauses at every captcha and at every final Submit button — never silently submits anything. Your IP, your cookies, your real Chrome session. There's no Instaply server in the loop, no telemetry, no signup, no subscription. MIT.
     >
     > Happy to answer anything about the architecture, the autofill rule design, the captcha-pause-for-human policy, why I gave up on the SaaS path, or whether this should even exist.

2. **Reddit (immediately after, in this order — don't shotgun all at once)**
   - **r/LocalLLaMA** — this audience LOVES "auto-installs Ollama, picks the right model for your hardware". Title: `Free local-first job-application agent (auto-picks the right Ollama model for your machine)`
   - **r/cscareerquestions** — title: `Open-sourced the job-application agent I built after 1,300 apps`. **Read the rules before posting** — they're strict about self-promotion. Frame as "sharing what I built", not "use my product".
   - **r/csMajors** + **r/internships** — same post, slightly more student-focused
   - **r/jobs** — broader audience, less technical framing
   - **r/Python** — angle: "interesting Python project, here's the architecture"
   - **r/selfhosted** — angle: "self-hosted alternative to paid job-application SaaS"
   - Wait 24 hours between subreddit cross-posts (mods downrank cross-spam)

3. **Twitter/X (about an hour after HN)**
   - Thread of 5–7 tweets:
     1. Hook: "I sent 1,300 job applications last fall. Then I built a tool that does it for me while I sleep. Free + open source. Here's what it looks like." + the GIF
     2. The setup-wizard angle: one command, detects your hardware, installs the right local LLM
     3. The autonomous angle: runs as a background task, discovers + scores + drafts overnight, you review the queue with coffee
     4. The privacy angle: zero servers in the loop, your IP, your cookies, captcha walls don't fire
     5. The cost angle: $0 forever, MIT, no signup, no telemetry
     6. The link to GitHub + a "star if you've ever cried over Workday at 1am" CTA
     7. Tag `@simonw` — he amplifies good local-first OSS
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
- ❌ Don't launch with a broken install path. Test from an incognito browser on a fresh machine if you can borrow one.
- ❌ Don't oversell. The README's "1,300 applications, free forever" framing is honest. Keep it that honest in every channel.
- ❌ Don't ignore negative comments. Engage them like a maintainer who cares about getting it right. The thoughtful response to a "this is just a worse RecruitBot" comment is what wins skeptics.

---

## A small note for after launch

When the issues start coming in, the first thing people will hit is the
fact that **`data/profile.json` doesn't exist yet** — they'll have to
hand-author it from `backend/models/schemas.py`. That's the friction
point that'll slow adoption the most. The setup wizard handles Ollama;
the next thing to ship is a **profile wizard** that asks the user 20
questions and writes a complete `profile.json` + `master-resume.json`.
That's the next ship after launch.

Other early-issue likely culprits:
- The post-lift TODO defaults in `agent/backend/services/autofill.py`
  (demographics, school name, etc.) — auto-fill nothing until profile
  data is wired through. Users will report blank fields.
- The Workday adapter is hardcoded as beta — anyone trying to apply to
  a Workday-only company will get a polite "not yet" message.
- macOS / Linux scheduler scripts don't exist yet — anyone not on
  Windows will need the manual `crontab` snippet from QUICKSTART.md.

Good luck. 💛
