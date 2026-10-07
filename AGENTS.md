# Leadscanner repository agent contract

## Current scope
- Build a fast cold-lead pipeline from a clean slate.
- Treat legacy repository code as implementation material, never as requirements by default.
- The Google Sheet Lead Dedupe Registry is the only retained historical lead source and is suppression-only.
- The active phases are discovery/filter -> historical dedupe -> identity/domain/contact verification -> bounded first-party research.
- Copy, offer selection, draft creation and mailbox execution are not active yet.

## Execution rules
- Work on `main` unless the user explicitly requests another branch.
- Put cheap gates before network-heavy research: website presence/category -> competitor hint -> historical dedupe -> official-site verification -> research.
- Pass explicit JSON contracts between stages; never rely on hidden state from a previous stage.
- Discovery data is a locator only, not prospect fact evidence.
- Verify official domain and public business email from the official site before research.
- Research only candidates with `ready_for_research=true` and fetch at most two extra first-party pages per candidate.
- Preserve bounded concurrency and same-domain URL safety.
- Prefer one workflow/job chain over repeated setup and artifact handoffs.

## Safety
- Never infer an email address, company identity, prospect fact, pain point or commercial outcome.
- Never use dedupe-history content as new prospect research.
- Never automatically send commercial outreach.

## Validation
- Run focused tests for every active-path change.
- Keep the active workflow path list narrow so unrelated legacy edits do not consume CI time.
- Report completion only with exact `main` commit and GitHub Actions evidence.
