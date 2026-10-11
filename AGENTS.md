# Leadscanner repository agent contract

## Public repository privacy gate
- The repository may remain public for source inspection and the bounded **public_audit** workflow that exports aggregate metrics only. **Personal review files, previews containing recipients, drafts, Instantly staging and sensitive command artifacts still require private visibility**. Require the GitHub Actions repository-private preflight before any reads or writes that produce such artifacts.
- This gate is fail-closed. A failed privacy gate must not upload partial review or prospect artifacts and must not bypass prior identity, dedupe, authorization, campaign or send checks.
- Existing public workflow artifacts containing contacts, researched prospect facts, or email copy need separate deletion/retention review. Never claim they were removed solely because a new gate passed.
- Repository visibility changes are operational decisions. Do not silently make a public repository private; the owner must approve the access change.


## Eenvoudig gebruik (bovenop ongewijzigde veiligheidsregels)
- Voor de gebruiker zijn er vier stappen: **zoeken → onderzoeken → kiezen → beoordelen**.
- Begin elke handmatige run bij het geanonimiseerde `overzicht.md` en vervolgens de review-queue met bronvermeldingen. De vele JSON-bestanden zijn technische bewijsstukken, geen extra gebruikersacties.
- Onderzoek breed; categorieën zijn hulpmiddelen om te rangschikken, geen harde uitsluitingen. Neem maximaal zes echte, controleerbare observaties mee (minder indien minder bewezen is). Beschrijf iets dat opvalt niet automatisch als een fout.
- Nieuwe en historische reviews gebruiken dezelfde broncontrole en e-mailrenderer; verwijder geen toestemming-/contact-, bron-, dedupe-, status-, campagne- of handmatige bevestigingspoort om het proces korter te laten lijken.
- De volledige lijst van reviewbevindingen wordt tot en met de menselijke goedkeuring aan één inhoudsgebonden token gekoppeld. Voor Instantly fact-only blijft de bestaande primair-observatie-templatecontract gelden tot een afzonderlijk geaudite wijziging is goedgekeurd.

## Current scope
- Build a fast cold-lead pipeline from a clean slate.
- Keep only the active cold-pipeline dependency closure. Legacy Google Maps adapters, remediation scripts, old mailbox bridges, pricing/scoring code and their tests have been removed.
- The Google Sheet Lead Dedupe Registry is the only retained historical lead source and is suppression-only.
- The primary active phases are preview discovery/filter -> historical dedupe -> official website verification -> bounded first-party research -> named-owner/team/business-email discovery -> exact email dedupe -> ranked first-party observations (up to six) -> one proposed value-first action -> validated reviewed-mail copy by default or explicitly selected fact-only review -> human review queue -> immutable preview snapshot -> exact approval selection -> fresh live dedupe revalidation -> Instantly staging into a Draft/Paused campaign -> exact Instantly readback -> canonical dedupe-registry closure -> explicit separate campaign activation -> scheduled Instantly reconciliation.
- The cold discovery/review pipeline and Instantly staging must never auto-send. Campaign activation is a separate user-confirmed send-capable action. The optional mijn.host draft path is fallback-only and not part of the primary outbound route.

## Execution rules
- Work on `main` unless the user explicitly requests another branch.
- Active discovery is PDOK + Overture Maps Places only; do not silently reintroduce Google Maps scraping.
- Put cheap gates before network-heavy research: website presence/category -> competitor hint -> historical dedupe -> official-site verification -> research.
- Pass explicit JSON contracts between stages; never rely on hidden state from a previous stage.
- Discovery data is a locator only, not prospect fact evidence.
- Verify official website/domain identity before research. Never use email presence, provider, personal-vs-generic mailbox or contact page availability as a gate on website research.
- After website research, inspect official About/Team/Owner/Contact pages and select an explicitly published email: personally named owner > named team member > personal-looking mailbox > general inbox. An address listed on the business's own contact page is not rejected for being on an external mail provider. Do not guess addresses or repurpose third-party footer contacts.
- Before turning selected email contacts into recipient-specific copy, check newly discovered addresses against the current dedupe registry, in addition to the earlier company/domain suppression gate.
- Research only candidates with `ready_for_research=true` and fetch at most twelve extra first-party pages per candidate.
- After research, classify and rank all sufficiently specific first-party observations regardless of category; retain up to six strongest diverse findings, or fewer when fewer are supported. Preserve a primary finding for compatibility. Generic promotional copy and unsupported claims never qualify.
- Map the selected observations to one small proposed example; never claim an artifact already exists.
- Default `preview_copy_mode=reviewed_mail` generates one evidence-backed NL/EN email for human approval. Explicit `preview_copy_mode=instantly_sequence` reviews verified official-site facts only and must never generate a per-lead email. If generating legacy copy, use one CTA, no meeting pressure, and no price/ROI/result claim.
- Every preview must emit privacy-safe `funnel-metrics.json` with stage rejection totals and `coverage-audit.json` with Overture operational-supply status.
- Every successful manual run also emits one readable, aggregate-only `overzicht.md` and GitHub job summary; never include contact details, company names or prospect copy.
- Do not add a second discovery source from a single thin/gap run; broaden the current query first and require repeated independent gap evidence before deliberate source expansion.
- Default public manual execution to `public_audit`: read-only live research with no recipient data, review text or tokens in public logs or artifacts. Personal `preview` is available only in private visibility and cannot mutate mailbox/registry; `instantly_stage` and `draft` require explicit human authorization.
- Every preview must emit `review-queue.json`, `review-queue.md`, and `review-queue.csv` with one approval token per reviewable lead.
- Bind each approval token to the exact lead ID, **all selected official-site findings**, verified evidence and proposed action; bind subject/body as well in reviewed-mail mode. Changed reviewed content must invalidate the token.
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
