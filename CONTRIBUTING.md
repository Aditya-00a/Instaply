# Contributing to Instaply

First — thank you. Every PR makes the tool better for the next student grinding through 200 applications a week.

## Quick orientation

```
instaply/adapters/       ← the most-wanted contributions live here
instaply/autofill/       ← rule engine + answer cache
instaply/orchestrator.py ← end-to-end glue
tests/                   ← pytest, fixtures live here
.github/                 ← banner, diagrams, issue templates, CI
```

## Setting up locally

```bash
git clone https://github.com/instaply/instaply.git
cd Instaply
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m playwright install chromium
pytest -q
```

If `pytest -q` is green, you're ready to hack.

## The most useful PR you can send: a new ATS adapter

Workday, Ashby, iCIMS, Taleo, Workable, BambooHR — each one unblocks thousands of postings.

The adapter contract is small. To add a new one:

1. **Grab a real posting URL** for the ATS you're targeting. Save the rendered HTML to `tests/fixtures/<atsname>_sample.html`.
2. **Create `instaply/adapters/<atsname>.py`**, mirroring `greenhouse.py` as a template. You need to implement:
   - `detect_url(url) -> bool`
   - `detect_html(html) -> bool`
   - `parse_form(html, company_slug=None) -> list[FieldCandidate]`
3. **Register** the adapter in `instaply/adapters/__init__.py` (it's an ordered list).
4. **Add a test** at `tests/test_<atsname>_adapter.py`. Cover: URL detection, HTML detection, parse output, end-to-end resolve.
5. **Submit PR**. Run `pytest -q` first to confirm everything passes.

Adapters are scored by:
- Coverage (does it find every input on the page?)
- Robustness (does it survive minor DOM changes?)
- Label resolution accuracy (do the labels match what a human reads?)

Look at the existing three adapters for reference — they're well-commented.

## Code style

- **Python 3.11+**
- `ruff check .` should pass (CI enforces this)
- Type hints on public functions
- Docstrings on every module and public function — explain *why*, not *what*
- No new dependencies unless absolutely necessary; if you add one, justify it in the PR

## Testing

- `pytest -q` to run everything
- New features need at least one test
- New adapters need a fixture HTML in `tests/fixtures/` and a `test_<atsname>_adapter.py`
- Use `worker/tests/test_*_adapter.py` as templates

**Never put real personal data in fixtures.** Use Jane Doe / `+1 (555) 555-0123` / `jane.doe@example.com`. The repo is public — fixtures get committed.

## Commit messages

Conventional Commits, loosely:

```
feat(adapter): add Ashby adapter
fix(autofill): handle aria-required="false" correctly
docs(readme): clarify Ollama setup
test(verifier): cover the all-rejection edge case
```

## What I'm looking for in a PR review

1. Does this make the tool more useful to a student?
2. Does it preserve privacy? (No new network calls without justification.)
3. Is it tested?
4. Is it understandable in 6 months?

If yes to all four, I'll merge it fast.

## What I won't merge

- Anything that adds telemetry or analytics
- Anything that requires a hosted account on a service I control
- Anything that breaks the "runs entirely on your laptop" promise
- Adapters for sites that explicitly forbid automation in their ToS *and* are likely to ban users for using it (this is a judgment call — open an issue first if unsure)

## Got the job?

[Open an issue](https://github.com/instaply/instaply/issues/new?template=got_the_job.yml) with the title *"Got the job"*. That's the only metric that matters.
