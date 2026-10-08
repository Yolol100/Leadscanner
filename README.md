# Leadscanner

Leadscanner is being rebuilt as a fast, cold-only lead pipeline.

## Active execution path

The only active GitHub workflow is `.github/workflows/leads-cold.yml`.

Manual dispatch has three modes:

- `preview` (default): runs discovery, verification, research and mail generation, then exports the human review queue. Preview is mutation-free.
- `instantly_stage` (**primary outbound route**): requires `confirm_instantly_stage=true`, the reviewed `preview_run_id`, one or more exact `approved_review_tokens`, and an `instantly_campaign_id`. It resumes the sealed preview, revalidates dedupe immediately before each mutation, and stages approved leads into a Draft/Paused Instantly campaign. It never activates the campaign.
- `draft` (optional fallback): keeps the existing mijn.host review-draft path for manual mailbox review. It is not the primary outbound route.

Current manual run:

1. **Discovery** — resolve one region through PDOK and query Overture Maps Places; keep only candidates with a website.
2. **Cheap filters** — remove malformed/missing identity, duplicate domains within the run, and obvious competitor categories/names without visiting sites.
3. **Historical dedupe** — fetch the live Lead Dedupe Registry and exclude matches by normalized company, domain, email or prior lead ID.
4. **Verification** — for at most 100 deduped candidates, visit the official-domain website with bounded concurrency; require same-domain redirects, prove company/domain consistency, exclude confirmed competitors, and find a public business email on the official site.
5. **Bounded research** — only for verified candidates with a public business email, reuse the homepage text already fetched during verification and visit at most two additional relevant first-party pages. Store sourced visible-text evidence only; add no inferred pain.
6. **Outreach reason** — select exactly one concrete first-party customer action or hold. Only appointment/booking, quote-request, reservation or ordering flows qualify. Generic quality, service, craftsmanship, customization, company descriptions, service/product catalogs, opening hours, prices/percentages, reviews and directory evidence do not qualify.
7. **Value-first action** — map the selected signal to one small proposed website example. The pipeline uses proposed-language only and never claims the artifact already exists.
8. **Mail generation + semantic QA** — create one short NL/EN cold email only for a concrete customer-action signal, with one observation, one proposed example, one low-friction CTA and an easy no. Subject <=8 words; body <=100 words; no meeting pressure, price, ROI, percentage or unsupported result claim.
9. **Review-draft preparation** — create a deterministic `growth-<20 hex>` lead ID from official domain + verified public email and build only `review_draft` / `review_required` rows.
10. **Funnel diagnostics** — emit privacy-safe stage counts and exact rejection-reason totals for cheap filters, dedupe, verification, research, outreach and mail QA. No prospect copy, company names or email addresses are included in the metrics artifact.
11. **Overture coverage audit** — compare raw/filtered/deduped candidate supply with the requested verification capacity. Classify the run as sufficient, sufficient-with-buffer, thin, gap or configuration-limited. Never auto-add a second source from one run.
12. **Human review queue** — export every reviewable lead with company, domain, verified email, signal, evidence URL, proposed value, subject, body and an approval token. The token fingerprint includes the exact copy/evidence, so a changed rerun becomes stale and is rejected.
13. **Immutable preview snapshot** — seal request, review batch, review queue and preview manifest into `preview-snapshot.json` with a content digest and source run/commit provenance. Preview artifacts are retained for 7 days.
14. **Fast sealed-preview resume** — mutation modes load the exact artifact from `preview_run_id`, verify the successful workflow-dispatch run, repository, `main` branch, commit SHA and snapshot digest, and never repeat discovery/research.
15. **Exact approval selection** — only explicitly pasted preview tokens are accepted; there is no `all` wildcard and unknown/stale tokens fail closed.
16. **Primary Instantly stage** — `instantly_stage` re-checks each approved lead against the current canonical registry immediately before mutation, requires a Draft/Paused Instantly campaign, and adds only still-current approved leads.
17. **Campaign-aware personalization** — the current single-step campaign still uses the exact approved `{{leadscanner_subject}}` and `{{leadscanner_body}}` variables. Staged leads additionally carry verified `{{leadscanner_observation}}`, `{{leadscanner_evidence_url}}`, `{{leadscanner_value_action}}` and (when present) `{{leadscanner_signal_type}}` for a future Instantly-owned multi-step template. Every referenced `leadscanner_*` variable must be supplied; missing fields block staging before any write.
18. **Canonical dedupe closure** — only after exact Instantly lead, campaign and custom-variable readback succeeds is the identity written as `instantly_staged` in the canonical registry.
19. **Separate activation gate** — staging never sends. Campaign activation remains a distinct explicit `activate_campaign` action with sender/lead/sending-status preflight and exact confirmation.
20. **Scheduled reconciliation** — Instantly state is periodically read back and may update only already-existing registry identities; scheduled sync cannot create prospects or send mail.
21. **Optional mailbox fallback** — `draft` mode remains available for manual mijn.host review drafts when explicitly requested, but is outside the primary Instantly outbound route.
22. **Run manifest** — every manual run records provenance, counts, mutation state and safety flags. `instantly_stage` closes with `automatic_send=false` and `campaign_activation_required=true`.

The primary route is now: **Leadscanner discovery/review → Instantly staging → explicit campaign activation → Instantly sending/replies → registry sync**. The last verified active campaign snapshot had one email step using full-copy placeholders, not a proven three-step template. This phase does not change campaign copy or stop legacy review-mail generation; removing it first would break the current sequence. Once a three-step Instantly template is verified, a separate reviewed migration can switch the preview/approval contract to personalization-only.

## Speed design

- One workflow and one execution job; no issue listeners or multi-workflow artifact chain.
- The live dedupe registry is fetched and structurally validated before discovery so a broken registry fails early.
- Website research never runs for cheap-filter or dedupe rejects.
- Verification is capped at 100 candidates with at most 10 workers.
- Research is capped at 100 verified candidates with at most 6 workers and two extra pages each.
- Homepage content is passed from verification to research, so research does not fetch it again.
- Phases 7-9 are deterministic local transformations over already-fetched evidence and add no extra prospect network requests.
- Preview runs skip Google write preflight, IMAP and registry mutation entirely while still producing human-readable review artifacts.
- Draft mode does not rerun discovery, site verification, research or copy generation; it resumes the exact reviewed preview artifact by run ID.
- The snapshot and each approval token are content-bound, so modified preview data or copy fails closed.
- Immediately before mutation, approved leads are rechecked against the live dedupe registry; leads that became suppressed after preview are skipped and reported.
- Draft mode installs only `requests` + `google-auth`; Overture dependencies are preview-only.
- A confirmed still-current approved draft batch is not written unless canonical Google Sheets write access succeeds first.
- Manual execution runs are never auto-cancelled by a newer manual run, avoiding an interruption between draft storage and registry closure.
- Only the cold runtime dependencies are installed and pip caching is enabled.
- The ChatGPT/Instantly control boundary is repository-native through immutable command files; no separate MCP server/runtime is part of the active dependency closure.

## Historical state

The Google Sheet **Lead Dedupe Registry** is the only retained historical lead source. It is used solely to prevent re-prospecting companies already seen in prior concepts/outreach. Historical copy, observations, scores and campaign content are not prospect research inputs.

## Safety

The active path may stage approved leads into a Draft/Paused Instantly campaign, but staging never sends email. Sending starts only through the separate explicit campaign-activation gate. Discovery hints are not treated as verified company facts. Public business email addresses are accepted only when observed on the official site. Instantly writes require `INSTANTLY_API_KEY`; canonical registry writes require `LEAD_REGISTRY_SERVICE_ACCOUNT_JSON`. The optional mijn.host fallback still requires `OUTREACH_MAIL_PASSWORD`.

## Active data sources

The active discovery path does not use Google Maps scraping.

- **PDOK Locatieserver** resolves a requested Dutch place/municipality to `pdok_id`, resolved name/type, longitude and latitude. No authentication is used.
- **Overture Maps Places** supplies discovery candidates. The active handoff keeps only `overture_id`, business name hint, category/taxonomy hint, website hint, longitude, latitude, confidence and bounded discovery email candidates when Overture contains public email data. Phone numbers and social profiles are deliberately not emitted by discovery.
- **Official business websites** are the verification and research source. They supply the verified official domain/URL, identity evidence, HTTP status, public business email + source URL, verification/research URLs and bounded first-party text evidence.
- **Lead Dedupe Registry** is suppression-only historical state: company, website/domain, email(s), status/history, lead IDs, source and `exclude_from_new_leads`.
- **Instantly Email Outreach** is the primary outbound execution layer after Leadscanner approval: campaign lead storage, personalized variables, scheduling, warmup, sending and reply/campaign state.
- **mijn.host** remains an optional manual draft fallback only; it is not the primary outbound route.

The previous Google Maps CSV adapters and remediation-era code were removed from the repository. If Google Maps is ever reintroduced, it must be a deliberate new source with its own current verification, tests and evidence contract; no deleted legacy behavior is implicitly restored.

## Quality diagnostics

Every preview now emits `funnel-metrics.json` and `coverage-audit.json` in addition to the review artifacts. The funnel file explains why leads were rejected at each stage without storing prospect copy or contact details. The coverage file measures whether Overture supplies enough candidates for the requested verification capacity. A second discovery source is not added automatically; first broaden the query/radius, and require repeated independent gap evidence before introducing another source.

## Quality tuning evidence

- Rotterdam painter preview `37625580078`: 30 Overture candidates, 28 after dedupe, 9 research-ready, 0 review mails. Funnel reasons were 5 weak generic marketing signals and 4 cases with no outreach-worthy customer action. This confirms generic quality/service copy is now held instead of mailed.
- Rotterdam physiotherapy preview `37626656135`: 30 Overture candidates, 13 research-ready, 2 concrete appointment signals and 2 review mails. This confirms the stricter gate still passes real customer-action evidence.
- Overture coverage benchmark at 10 km found sufficient supply for painter, restaurant, dentist, real-estate and hair-salon searches. Bicycle stores were thin at 17 candidates; widening to 15 km produced 30 and removed the gap.
- Current decision: **do not add a second discovery source**. Broaden Overture query/radius first; only deliberate source expansion after repeated independent gap evidence.
