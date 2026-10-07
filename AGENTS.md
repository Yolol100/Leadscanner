# Leadscanner repository agent contract

## Current scope
- Build a fast cold-lead pipeline from a clean slate.
- Keep only the active cold-pipeline dependency closure. Legacy Google Maps adapters, remediation scripts, old mailbox bridges, pricing/scoring code and their tests have been removed.
- The Google Sheet Lead Dedupe Registry is the only retained historical lead source and is suppression-only.
- The active phases are preview discovery/filter -> historical dedupe -> identity/domain/contact verification -> bounded first-party research -> one evidence-backed outreach reason -> one proposed value-first action -> short validated cold mail -> human review queue -> immutable preview snapshot -> draft resume from that exact snapshot -> exact approval selection -> live dedupe revalidation -> strict review-draft storage -> exact mailbox readback -> canonical dedupe-registry append/readback -> provenance-bound run manifest.
- The cold discovery/review pipeline must never auto-send. A separate GitHub Instantly control plane in this same workflow may execute only explicit user-confirmed Instantly actions from immutable command files; it must not bypass Leadscanner approval or live dedupe gates for Leadscanner-sourced prospects.

## Execution rules
- Work on `main` unless the user explicitly requests another branch.
- Active discovery is PDOK + Overture Maps Places only; do not silently reintroduce Google Maps scraping.
- Put cheap gates before network-heavy research: website presence/category -> competitor hint -> historical dedupe -> official-site verification -> research.
- Pass explicit JSON contracts between stages; never rely on hidden state from a previous stage.
- Discovery data is a locator only, not prospect fact evidence.
- Verify official domain and public business email from the official site before research.
- Research only candidates with `ready_for_research=true` and fetch at most two extra first-party pages per candidate.
- After research, select exactly one concrete first-party customer-action signal (appointment/booking, quote request, reservation or ordering) or hold the lead. Generic quality, service, catalog or brand language never qualifies.
- Map that reason to exactly one small proposed example; never claim an artifact already exists.
- Generate at most one short cold mail with one CTA, no meeting pressure, and no price/ROI/result claim.
- Every preview must emit privacy-safe `funnel-metrics.json` with stage rejection totals and `coverage-audit.json` with Overture operational-supply status.
- Do not add a second discovery source from a single thin/gap run; broaden the current query first and require repeated independent gap evidence before deliberate source expansion.
- Default every manual execution to `preview`; preview must not require mailbox or Google write credentials and must not mutate either system.
- Every preview must emit `review-queue.json`, `review-queue.md`, and `review-queue.csv` with one approval token per reviewable lead.
- Bind each approval token to the exact lead ID, subject, body, evidence and proposed value action; changed copy must invalidate the token.
- Seal every preview into a digest-bound `preview-snapshot.json` containing source repository/run/commit, the review batch, review queue, request and preview manifest.
- Enter mutation mode only when `execution_mode=draft`, `confirm_review_drafts=true`, a numeric `preview_run_id`, and at least one exact `approved_review_tokens` value are all explicit.
- Draft mode must resume the exact successful, non-expired preview artifact from `main`; it must not rerun discovery, verification, research or copy generation.
- Revalidate approved snapshot leads against the current dedupe registry immediately before any mailbox mutation; suppress anything that appeared in the registry after preview.
- Store only the remaining exact approved subset as `review_draft` mail through the dedicated IMAP draft writer; allow exact retries but reject changed existing drafts.
- Require exact To/Subject/body/lead-ID/review-status readback before updating the registry.
- Preflight Google Sheets write access before any non-empty draft batch, then append/read back the canonical DedupeRegistry only after mailbox readback is green.
- Preserve bounded concurrency and same-domain URL safety.
- Prefer one workflow/job chain over repeated setup and artifact handoffs.
- Keep the ChatGPT web control boundary repository-native: new immutable JSON commands under `instantly-commands/inbox/` -> allowlisted executor -> Actions result artifact.
- Instantly write commands require exact target-bound confirmation and must fail closed on a GitHub Actions re-run; intentional retries require a fresh command file.
- Do not expose a generic Instantly HTTP method/path escape hatch. Add named operations with focused validation instead.
- If the repository is public, sensitive Instantly reads and all Instantly writes must fail closed. Full ChatGPT control is allowed only after the repository is private so command payloads and Actions results cannot expose lead/reply/account data publicly.
- Campaign activation, replies, forwards and test sends are explicit send-capable actions; they require the send gate plus exact confirmation, and activation must re-read campaign, sender and lead state before activation.
- Never commit Instantly, SMTP/IMAP, OAuth, Google service-account or other credential material in command JSON. Keep secrets in GitHub Actions Secrets.
- Scheduled Instantly reconciliation is read-only toward Instantly and may update only an already-existing canonical dedupe row. It must never create a registry identity or send outreach.

## Safety
- Never infer an email address, company identity, prospect fact, pain point or commercial outcome.
- Never use dedupe-history content as new prospect research.
- Never automatically send commercial outreach. Send-capable Instantly actions are user-triggered only and require the repository command gates described above.
- Never let scheduled synchronization, a workflow re-run, or a repository code push become an implicit send trigger.

## Validation
- Run focused tests for every active-path change.
- Keep the active workflow path list narrow so unrelated legacy edits do not consume CI time.
- Emit one `run-manifest.json` for every manual run with execution mode, stage counts, review-queue count, approval count, operator-rejected count, post-preview suppression count, source preview ID/run/commit, closure state, and safety flags.
- Report completion only with exact `main` commit and GitHub Actions evidence.
