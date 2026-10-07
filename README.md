# Leadscanner

Leadscanner is being rebuilt as a fast, cold-only lead pipeline.

## Active execution path

The only active GitHub workflow is `.github/workflows/leads-cold.yml`.

Manual dispatch has two modes:

- `preview` (default): runs research and mail generation, then exports `review-queue.md`, `review-queue.csv`, and `review-queue.json`. Each reviewable lead receives an approval token bound to the exact reviewed copy. Preview performs zero mailbox or Google Sheet mutations and needs no mutation credentials.
- `draft`: requires `execution_mode=draft`, `confirm_review_drafts=true`, the GitHub Actions `preview_run_id` of the reviewed preview, and one or more exact `approved_review_tokens`. Draft mode downloads that exact successful preview artifact instead of repeating discovery/research.

Current manual run:

1. **Discovery** — resolve one region through PDOK and query Overture Maps Places; keep only candidates with a website.
2. **Cheap filters** — remove malformed/missing identity, duplicate domains within the run, and obvious competitor categories/names without visiting sites.
3. **Historical dedupe** — fetch the live Lead Dedupe Registry and exclude matches by normalized company, domain, email or prior lead ID.
4. **Verification** — for at most 100 deduped candidates, visit the official-domain website with bounded concurrency; require same-domain redirects, prove company/domain consistency, exclude confirmed competitors, and find a public business email on the official site.
5. **Bounded research** — only for verified candidates with a public business email, reuse the homepage text already fetched during verification and visit at most two additional relevant first-party pages. Store sourced visible-text evidence only; add no inferred pain.
6. **Outreach reason** — select exactly one concrete first-party signal or hold. Generic company descriptions, opening hours, prices/percentages, reviews and directory evidence do not qualify.
7. **Value-first action** — map the selected signal to one small proposed website example. The pipeline uses proposed-language only and never claims the artifact already exists.
8. **Mail generation + semantic QA** — create one short NL/EN cold email with one observation, one proposed example, one low-friction CTA and an easy no. Subject <=8 words; body <=100 words; no meeting pressure, price, ROI, percentage or unsupported result claim.
9. **Review-draft preparation** — create a deterministic `growth-<20 hex>` lead ID from official domain + verified public email and build only `review_draft` / `review_required` rows.
10. **Human review queue** — export every reviewable lead with company, domain, verified email, signal, evidence URL, proposed value, subject, body and an approval token. The token fingerprint includes the exact copy/evidence, so a changed rerun becomes stale and is rejected.
11. **Immutable preview snapshot** — seal request, review batch, review queue and preview manifest into `preview-snapshot.json` with a content digest and source run/commit provenance. Preview artifacts are retained for 7 days.
12. **Fast draft resume** — draft mode loads the exact artifact from `preview_run_id`, verifies the successful workflow-dispatch run, repository, `main` branch, commit SHA and snapshot digest, then materializes only the snapshot-bound review batch. Discovery, verification, research and copy generation are not repeated.
13. **Exact approval selection** — draft mode accepts only preview tokens explicitly pasted into `approved_review_tokens`; there is no `all` wildcard and unknown/stale tokens fail closed.
14. **Live dedupe revalidation** — immediately before mutation, re-check every approved lead against the current canonical registry. Anything added since the preview is suppressed and cannot become a new draft.
15. **Registry access preflight + approved mijn.host draft storage** — before the still-current approved batch is written, prove Google Sheets write access. Then append only those drafts through IMAP. Exact retries are allowed; changed existing drafts are rejected instead of overwritten.
16. **Exact mailbox readback** — require an exact match on recipient, subject, body, lead ID and review status. SMTP/send remains unavailable.
17. **Canonical dedupe closure** — append only successfully read-back, still-current approved identities to `DedupeRegistry` in one Google Sheets batch and verify the new rows by an exact API readback.
18. **Run manifest** — emit `run-manifest.json` with mode, stage counts, review-queue count, approved count, operator-rejected count, post-preview suppression count, source preview ID/run/commit, mutation state and safety flags. Preview ends as `preview_ready`; a successful draft run ends as `closed`.

Preview is the default and is mutation-free. Confirmed draft mode creates review drafts only; neither mode sends commercial email.

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

## Historical state

The Google Sheet **Lead Dedupe Registry** is the only retained historical lead source. It is used solely to prevent re-prospecting companies already seen in prior concepts/outreach. Historical copy, observations, scores and campaign content are not prospect research inputs.

## Safety

The active path may generate and store validated review drafts, but it never sends email. Discovery hints are not treated as verified company facts. Public business email addresses are accepted only when observed on the official site. Draft storage requires `OUTREACH_MAIL_PASSWORD`; canonical registry writes require the GitHub Actions secret `LEAD_REGISTRY_SERVICE_ACCOUNT_JSON` for a service account that can edit the retained Google Sheet.
