# Leadscanner repository agent contract

## Current scope
- Build a fast cold-lead pipeline from a clean slate.
- Keep only the active cold-pipeline dependency closure. Legacy Google Maps adapters, remediation scripts, old mailbox bridges, pricing/scoring code and their tests have been removed.
- The Google Sheet Lead Dedupe Registry is the only retained historical lead source and is suppression-only.
- The primary active phases are preview discovery/filter -> historical dedupe -> identity/domain/contact verification -> bounded first-party research -> one evidence-backed outreach reason -> one proposed value-first action -> verified-facts-only review (default; no per-lead email) or legacy validated mail -> human review queue -> immutable preview snapshot -> exact approval selection -> fresh live dedupe revalidation -> Instantly staging into a Draft/Paused campaign -> exact Instantly readback -> canonical dedupe-registry closure -> explicit separate campaign activation -> scheduled Instantly reconciliation.
- The cold discovery/review pipeline and Instantly staging must never auto-send. Campaign activation is a separate user-confirmed send-capable action. The optional mijn.host draft path is fallback-only and not part of the primary outbound route.

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
- Default `preview_copy_mode=instantly_sequence` must not generate a per-lead email; it reviews verified official-site facts only. Use `preview_copy_mode=reviewed_mail` only for the legacy Instantly template or optional mijn.host fallback. If generating legacy copy, use one CTA, no meeting pressure, and no price/ROI/result claim.
- Every preview must emit privacy-safe `funnel-metrics.json` with stage rejection totals and `coverage-audit.json` with Overture operational-supply status.
- Do not add a second discovery source from a single thin/gap run; broaden the current query first and require repeated independent gap evidence before deliberate source expansion.
- Default every manual execution to `preview`; preview must not require mailbox or Google write credentials and must not mutate either system.
- Sensitive GitHub Actions jobs (all manual preview/stage/draft, scheduled sync and newly added Instantly control commands) require the exact GitHub event value `repository.private == true` before data processing; a public or unknown visibility fails closed. This gate does not delete historical public artifacts, and it must not be bypassed by a manually supplied env variable. Ordinary CI tests and pushes without new Instantly commands must remain functional.
- Every preview must emit `review-queue.json`, `review-queue.md`, and `review-queue.csv` with one approval token per reviewable lead.
- Bind each approval token to the exact lead ID, verified evidence and proposed action; bind subject/body as well in legacy mail mode. Changed reviewed content must invalidate the token.
- Seal every preview into a digest-bound `preview-snapshot.json` containing source repository/run/commit, the review batch, review queue, request and preview manifest.
- The primary mutation mode is `execution_mode=instantly_stage`. It requires `confirm_instantly_stage=true`, a numeric `preview_run_id`, at least one exact `approved_review_tokens` value, and an explicit `instantly_campaign_id`.
- Instantly stage mode must resume the exact successful, non-expired preview artifact from `main`; it must not rerun discovery, verification, research or copy generation.
- Revalidate each approved snapshot lead against the current dedupe registry immediately before its Instantly mutation; suppress anything that appeared after preview.
- Stage legacy reviewed-mail leads only into Draft/Paused campaigns that reference **both** approved `leadscanner_subject` and `leadscanner_body` fields; legacy approval must not bypass fact-only campaign fingerprint review. Stage fact-only reviews only into a **Draft** campaign with exactly three email steps, an evidence-only template, all merge fields mapped, and exact `APPROVE_INSTANTLY_SEQUENCE <campaign_id> <sha256>` approval bound to the live sequence. Fact-only payloads must never contain `leadscanner_subject`/`leadscanner_body`. Re-read the fingerprint before every lead write, and require exact lead/campaign/custom-variable readback before registry closure.
- Before changing sequence/copy contracts, use the read-only `audit_campaign_sequence` command. Its report must never contain subject/body text; a three-step count alone does not prove that required merge fields exist or that an active campaign is safe to mutate. Audit the sequence fingerprint and unmapped merge fields. Fact-only previews must never be saved as mailbox drafts or staged without an exact campaign-level approval; independently review all three email variants and the applicable contact/legal basis before approval.
- Write `instantly_staged` to the canonical registry only after exact Instantly readback succeeds. A failed later lead must not invalidate already-closed prior staged leads; a retry reuses fresh dedupe to skip them safely.
- Campaign activation remains separate from staging and requires the existing exact confirmation, sender health, lead verification and sending-status preflight. For any Leadscanner-linked campaign require `APPROVE_INSTANTLY_ACTIVATION <campaign_id> <sequence_sha256> <leadset_sha256>` and a verified permission basis plus opaque evidence reference on **every** lead. Read-only `audit_activation_readiness` reports hashes/counts, never contact details. Re-read campaign and leadset **and** live canonical dedupe registry before the activate call. A missing, ambiguous, replied or suppressed registry identity blocks sending; bounced/unsubscribed/skipped Instantly lead states also block sending. Missing legal basis means NO SEND; public business email is not permission.
- Optional `draft` mode may still create mijn.host review drafts when explicitly requested; it is not the default outbound path.
- Preserve bounded concurrency and same-domain URL safety.
- Prefer one workflow/job chain over repeated setup and artifact handoffs.
- Keep the ChatGPT web control boundary repository-native: new immutable JSON commands under `instantly-commands/inbox/` -> allowlisted executor -> Actions result artifact.
- Instantly write commands require exact target-bound confirmation and must fail closed on a GitHub Actions re-run; intentional retries require a fresh command file.
- Do not expose a generic Instantly HTTP method/path escape hatch. Add named operations with focused validation instead.
- Repository visibility must not disable the user-requested Instantly control surface. Because command JSON and short-lived result artifacts may be visible when the repository is public, never place API keys, mailbox credentials, service-account JSON, OAuth tokens or other authentication secrets in them.
- Campaign activation, replies, forwards and test sends are explicit send-capable actions; they require the send gate plus exact confirmation, and activation must re-read campaign, sender and lead state before activation.
- Never commit Instantly, SMTP/IMAP, OAuth, Google service-account or other credential material in command JSON. Keep secrets in GitHub Actions Secrets.
- Scheduled Instantly reconciliation is read-only toward Instantly and may update only an already-existing canonical dedupe row. It must never create a registry identity or send outreach.

## Safety
- Never infer an email address, company identity, prospect fact, pain point or commercial outcome.
- Do not remove legacy mail generation or rewrite an active Instantly sequence until the actual target campaign and its replacement merge fields have been independently verified; a one-step `{{leadscanner_subject}}`/`{{leadscanner_body}}` sequence still depends on that reviewed copy.
- Never use dedupe-history content as new prospect research.
- Never automatically send commercial outreach. Instantly staging is non-sending; send-capable activation/reply/forward/test actions are user-triggered only and require the repository command gates described above.
- Never let scheduled synchronization, a workflow re-run, or a repository code push become an implicit send trigger.

## Validation
- Run focused tests for every active-path change.
- Keep the active workflow path list narrow so unrelated legacy edits do not consume CI time.
- Emit one `run-manifest.json` for every manual run with execution mode, stage counts, review-queue count, approval count, operator-rejected count, post-preview suppression count, source preview ID/run/commit, closure state, and safety flags.
- Report completion only with exact `main` commit and GitHub Actions evidence.
