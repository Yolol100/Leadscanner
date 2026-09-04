# Leadscanner repository instructions

## Scope
- This private repository is the central GitHub runtime for `leads`.
- It contains three separate capability classes: `prospect_discovery`, optional read-only `website_evidence_scan`, and controlled `outreach_delivery`.
- `leads` still owns company realness, Customer Potential/qualification, contact choice, compliance basis/status, mailcopy and interpretation of provider/readback outcomes.
- `webactueel-workflow` remains controller for cross-skill routing, source selection, repository selection, handoffs and total workflow closure.
- Do not make the website scanner a default step for every prospect.

## Capability boundaries

### Prospect discovery
- Use only approved `ProspectSources` and write discovered company/domain candidates to `ProspectCandidates`.
- Preserve robots, public-network/SSRF blocking, pacing, timeout, byte and candidate limits.
- Never harvest contacts, score leads, create copy, decide compliance or receive SMTP/IMAP credentials.

### Website evidence scan
- Preserve the existing Node/Crawlee/Playwright/Axe/Lighthouse/Linkinator/tech-detect stack.
- It remains read-only: GET/HEAD only, public official sites only, no login/forms/orders/payments/bookings or other state changes.
- Output is evidence only, primarily `scan-results/leads-handoff.json`.
- Scanner output never changes lead fit, priority, compliance or send permission automatically.

### Outreach delivery
- Accept only previously reviewed/approved Leads transport state.
- Preserve sender preflight, Sheet contract checks, compliance preflight, suppression, mailbox pacing, sequences/threading, SMTP, IMAP reply/bounce/opt-out readback and reporting.
- Manual workflow default is `validate`; live requires an explicit `live` selection. Scheduled live additionally requires `OUTREACH_ENABLED=true`.
- CI must never receive production mailbox/service-account secrets and must never send email.
- The active direct SMTP runtime has no Reoon dependency. Do not add `REOON_API_KEY` unless a future explicit, tested runtime route genuinely requires it.
- Reply, bounce and opt-out stop further sequence activity fail-closed.

## Secret boundaries
- Never commit, print, log or artifact secret values.
- Discovery may receive `GOOGLE_SERVICE_ACCOUNT_JSON` only; it must never receive mailbox or verifier credentials.
- Sheet-only extended/compliance preflights must not receive mailbox credentials.
- Reporting must not receive mailbox credentials.
- SMTP/IMAP secrets are scoped only to steps that require mailbox transport/authentication.

## Before changing files
- For scanner behavior, read `README.md`, `package.json`, `requests/scan.json` handling and `.github/workflows/scan.yml`.
- For Leads Python runtime, read `LEADS-INTEGRATION.md`, `toolkit-contract.json`, the relevant production workflow and the direct import closure under `scripts/`.
- Keep `main` generic. Concrete request state belongs only on temporary runtime branches or explicit workflow inputs; run evidence remains in short-lived Actions artifacts/Sheets.
- Do not introduce a dependency on `Yolol100/Orchestrator`; Leadscanner must remain standalone for Leads GitHub execution.

## Validation
For scanner/runtime changes, preserve existing Node checks:

```bash
npm ci
npm test
npm run check:crawler
npm run check:tools
```

For Leads Python changes:

```bash
python3 -m pip install -r requirements-outreach.txt
python3 -m compileall -q scripts
PYTHONPATH=scripts python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Do not use production credentials or `live` mode in tests. Workflow/security tests must keep discovery credential isolation and the outreach fail-closed order intact.

## Evidence boundaries
- Discovery creates candidates, not approved leads.
- Scanner output is candidate technical/browser evidence only; Lighthouse is lab evidence and axe findings are automated accessibility signals, not full conformance proof.
- SMTP acceptance is not proof of inbox placement or business outcome.
- Reporting/ReplyInbox classifications are evidence for Leads/operator review and may not autonomously rewrite copy or sales truth.
- Green repository tests prove the tested code/contracts only; live mailbox/Sheet readiness requires separate configured preflight/readback.
