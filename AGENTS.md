# Leadscanner repository instructions

## Scope
- This private repository is a conditional read-only technical browser evidence adapter for `leads`; it is not a leadfinding, scoring, outreach, compliance or campaign owner.
- `leads` owns lead fit, official-site evidence, the chosen outreach angle, personalization and provider-readback interpretation.
- `webactueel-workflow` remains controller for cross-skill routing, source selection, repository selection, handoffs and total workflow closure.
- Prefer native browser/Site Tool evidence when it can satisfy the same bounded evidence class. Use this repository only when a specific technical proof gap remains or the user explicitly requests a technical scan/rescan.

## Before changing files
- Read `README.md`, `package.json`, `requests/scan.json` contract handling and `.github/workflows/scan.yml` before changing runtime behavior.
- Keep `main` generic. Concrete request state belongs only on temporary `runtime/**` branches or explicit workflow-dispatch input; run evidence remains in short-lived Actions artifacts.
- Preserve the single-target requirement, public-official-site restriction, GET/HEAD-only behavior, page/rate bounds and privacy boundaries.
- Never add leadfinding, e-mail discovery, send-permission logic, mailcopy, campaign management, follow-ups, arbitrary shell/proxy behavior or production-site mutations.

## Validation
Use the locked dependency graph and the repository's existing checks. At minimum for runtime or workflow changes:

```bash
npm ci
npm test
npm run check:crawler
npm run check:tools
```

Run the smallest matching scan fixture/workflow path when request validation, browser evidence, handoff output or workflow behavior changes.

## Evidence boundaries
- Scanner output is candidate technical/browser evidence only. It never proves lead fit, priority, send permission, conversion impact, WCAG conformance or campaign outcome.
- Lighthouse is lab evidence; axe findings are automated accessibility signals, not complete conformance proof.
- A successful Action proves only the executed bounded scan. `leads` must interpret the evidence and return completion state to `webactueel-workflow`.
- Do not merge, send outreach or mutate a customer website solely because scanner checks are green.
