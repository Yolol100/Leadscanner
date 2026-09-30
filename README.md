# Leadscanner — Verified B2B Lead Workflow

> **Operations tooling · Python · GitHub Actions · PDOK · Overture · Google Maps · review-only outreach**

Leadscanner supports a controlled B2B prospect workflow for the Andrews Groeiabonnement. It discovers candidate businesses, removes unsuitable competitors, verifies public business/contact evidence and prepares short NL/EN email drafts for human review.

It does **not** guess email addresses and does **not** send outreach automatically.

## Workflow

`discover/filter -> verify -> draft -> mijn.host review_draft -> exact readback`

| Stage | What happens |
| --- | --- |
| Discovery | PDOK, Overture and Google Maps are used as discovery sources |
| Filtering | Duplicates and competing web/marketing/SEO providers are excluded |
| Verification | Official site, language and a public business email address are checked |
| Drafting | A short Groeiabonnement email is prepared only from verified evidence |
| Review | Drafts remain `review_required` and are read back exactly before human action |

## Safety boundaries

- Never invent or infer an email address.
- Never auto-send outreach.
- Keep public email evidence in review state.
- Exclude competing marketing, web, SEO, social, automation, WordPress and hosting providers.
- Use only the requested number of verified drafts.
- Treat GitHub Actions and issues as workflow transport/evidence, not as permission to contact anyone.

## Why there can be many open GitHub issues

This repository also uses owner-only GitHub issues as structured workflow requests and queue records, for example `[lead-verify]` and `[growth-draft]` jobs. Therefore, the repository's open-issue count should not be interpreted as a count of unresolved software defects.

Concrete technical defects can still be tracked as normal issues, but operational request records are intentionally part of the workflow surface.

## Running the workflow

Start through `workflow_dispatch` or an owner-only `[growth-draft]` issue with a JSON body.

The runtime is designed around explicit inputs, bounded batches and review-only outputs. Public repository state must not contain private credentials or unreviewed customer data.

## What this demonstrates

- Source-aware B2B prospect discovery and deduplication.
- Evidence-bound contact verification.
- Deterministic filtering and bounded workflow execution.
- Human-in-the-loop outreach safeguards.
- GitHub Actions orchestration and auditable request handling.

## About the developer

I am **Andrew Baeten**, a Senior WordPress Developer with 10+ years of experience and **70+ delivered projects**. I also build internal automation and QA tooling that makes repetitive web operations more controlled and reviewable.

[Portfolio cases](https://andrewbaeten.nl/category/cases) · [LinkedIn](https://www.linkedin.com/in/andrew-baeten-305a1478/) · [GitHub profile](https://github.com/Yolol100)
