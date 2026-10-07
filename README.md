# Leadscanner

Leadscanner is being rebuilt as a fast, cold-only lead pipeline.

## Active architecture

The active execution path is intentionally small:

candidate input -> live dedupe registry -> dedupe result

The next planned phases are:

discovery -> cheap filters -> identity/domain verification -> contact discovery -> bounded prospect research -> opportunity selection -> draft construction -> validation -> human-reviewed draft

Only the first dedupe path is active today. Legacy scripts remain in the repository as implementation material but are not part of the active workflow unless deliberately reintroduced later.

## Historical state

The Google Sheet Lead Dedupe Registry is the only retained historical lead source. It exists solely to prevent re-prospecting companies that already had a concept, send, reply, bounce, opt-out, or other prior lead history.

The active workflow reads the registry live on every manual run and excludes matches by conservative normalized company, domain, email, or lead ID.

## GitHub Actions

.github/workflows/leads-cold.yml is the only active Leadscanner workflow.

- push / pull_request: run only the focused dedupe tests when the new execution-path files change.
- workflow_dispatch: test first, then fetch the live dedupe registry and run the hard dedupe gate.
- No issue event listeners.
- No automatic outreach sending.
- No pip install on the active path; dedupe uses Python's standard library only.
