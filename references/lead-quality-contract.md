# Lead quality contract — optional private pre-draft reviewer

This is a supplement to `skills://leads`, not another controller or a replacement for its four steps. `webactueel-workflow` remains controller.

## 7 scoring fields: total exactly 10

| Field | Max |
| --- | ---: |
| `source_accuracy` | 2.0 |
| `activity_fit` | 1.5 |
| `distinctive_opening` | 1.5 |
| `added_value` | 2.0 |
| `natural_tone` | 1.0 |
| `subject_clarity` | 1.0 |
| `formal_requirements` | 1.0 |

Each independent review assigns numeric values inside its field range; invalid/nonfinite inputs are rejected. This is a subjective **editorial** rubric, not measured conversion. `score_0_to_10` is clamped [0,10] and further capped when evidence or required copy elements are missing. Explicit separate outputs: `factually_confirmed`, `editorially_strong`, `additional_check_needed`, `not_send_ready` (always true), `eligible_for_private_draft` (never send), `measured_conversion=null`. Passing a syntactically valid evidence record cannot replace human verification of actual live pages.

## Minimum private evidence record

One JSON object per line, containing:
- `draft`: `draft_id` (opaque `draft-` + 32 hex), `email`, `source_url`, `subject`, `body`.
- `verification`: `company_identity="confirmed"`, `branch="confirmed"`, `email="confirmed"`, `email_source_excerpt`, `email_source_url`, `fact="confirmed"`, `fact_quote`, `fact_source_excerpt`, `fact_source_url`, `checked_at` (timezone-aware ISO8601 within 30 days), `dedupe="clear"`, `claims_supported=true`, `existing_features` (list), `cross_domain_link_proved` (boolean when needed).
- `proposal`: `feature`, `adds_value=true`, `why_relevant` describing a real *additional* customer-journey benefit.
- `rubric`: seven numeric fields above.

This validation is **not** a website crawler, a legal permission checker, a new approval system, or a sending tool. Real site evidence and registry/HMAC readback must still be verified through the existing lead pipeline before draft creation. Never place real records or correspondence in public GitHub or Actions logs.

## Hard fail / caps

- Unknown company/email => max 3.5; branch or unrelated email domain => max 4.
- Unconfirmed quote/source or stale check => max 5; historical dedupe unsafe or unsupported claim => max 4.
- Already present functionality sold again => max 5; unproven incremental value => max 6.
- Generic opening => max 7; missing exact opt-out, more than one commercial question, or >110 body words => 0.
- Exactly one CTA, short subject, no raw placeholders, no invented outcomes, exact opt-out and short Andrew signature.
- No "10+" score; review-only status cannot imply lawful send authorization.

## Private batch, progress and replay

`python3 scripts/lead_quality_gate.py --input PRIVATE.jsonl --output PRIVATE-results.jsonl --batch-size 100`.

Write private JSONL result and checkpoint atomically, hash and re-read output. Check source hash and processed row identities on resume. Any changed source, missing checkpoint or output hash mismatch => fail closed. This is an opt-in review tool, not wired into `myhost-draft.yml` until the source-evidence bridge is validated. Existing IMAP, opt-out and dedupe remain unchanged.

## Lessons provenance

- `QA450PerMail` in private Google Sheet, checked 2026-10-15: 206 generic openings, 215 only service mentions, 29 distinctive; 27 require source recheck; 399 rewrite recommended.
- `Verbeter450Concepten` currently contains 100 of 450; four lack reconfirmed official source.
- `Batch1Topkwaliteit`: 100 evaluations, of which 99 still flag manual final review.
- Historical anonymized adversarial scenarios: incorrect business classification from name; attributing unsupported menu/property; selling an existing online booking feature; assuming a nonmatching email domain; score exceeding 10 due to arithmetic; continuing after partial batch despite changed data.
- Source priority: official business page/contact evidence > KVK/CBS classification context > third-party directories/Overture hints. No source implies permission to send unsolicited marketing. Check ACM and Telecommunicatiewet art.11.7 during human review.
