<!-- Thanks for sending a PR! Quick checklist below — feel free to delete the parts that don't apply. -->

## What does this change?

<!-- One or two sentences. -->

## Why?

<!-- The pain it solves, or the user it helps. -->

## How to test

<!-- Steps a reviewer can run on their machine. Include a sample posting URL if relevant. -->

```bash
# e.g.
pip install -e ".[dev]"
pytest tests/
instaply apply <url>
```

## Checklist

- [ ] I ran `pytest -q` and it passes
- [ ] If I added a new ATS adapter, I included a fixture HTML in `tests/fixtures/` and a test
- [ ] No real personal data (emails, phone numbers, names) in any test fixture or commit
- [ ] No API keys, tokens, or `.env` files committed
- [ ] Updated `CHANGELOG.md` if user-visible

## Anything else reviewers should know?

<!-- Tradeoffs, follow-up work, things you considered and rejected. -->
