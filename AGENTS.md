# Leadscanner repository agent contract

## Current scope
- Build a fast cold-lead pipeline from a clean slate.
- Treat legacy repository code as implementation material, never as requirements by default.
- The Google Sheet Lead Dedupe Registry is the only retained historical lead source and is suppression-only.
- The active phases are discovery/filter -> historical dedupe -> identity/domain/contact verification -> bounded first-party research -> one evidence-backed outreach reason -> one proposed value-first action -> short validated cold mail -> strict review-draft storage -> exact mailbox readback -> canonical dedupe-registry append/readback.
- Commercial sending is not active and must not be added to this workflow.

## Execution rules
- Work on `main` unless the user explicitly requests another branch.
- Put cheap gates before network-heavy research: website presence/category -> competitor hint -> historical dedupe -> official-site verification -> research.
- Pass explicit JSON contracts between stages; never rely on hidden state from a previous stage.
- Discovery data is a locator only, not prospect fact evidence.
- Verify official domain and public business email from the official site before research.
- Research only candidates with `ready_for_research=true` and fetch at most two extra first-party pages per candidate.
- After research, select exactly one first-party outreach reason or hold the lead.
- Map that reason to exactly one small proposed example; never claim an artifact already exists.
- Generate at most one short cold mail with one CTA, no meeting pressure, and no price/ROI/result claim.
- Store only `review_draft` mail through the dedicated IMAP draft writer; allow exact retries but reject changed existing drafts.
- Require exact To/Subject/body/lead-ID/review-status readback before updating the registry.
- Preflight Google Sheets write access before any non-empty draft batch, then append/read back the canonical DedupeRegistry only after mailbox readback is green.
- Preserve bounded concurrency and same-domain URL safety.
- Prefer one workflow/job chain over repeated setup and artifact handoffs.

## Safety
- Never infer an email address, company identity, prospect fact, pain point or commercial outcome.
- Never use dedupe-history content as new prospect research.
- Never automatically send commercial outreach. The active route exposes no SMTP/send action.

## Validation
- Run focused tests for every active-path change.
- Keep the active workflow path list narrow so unrelated legacy edits do not consume CI time.
- Report completion only with exact `main` commit and GitHub Actions evidence.
