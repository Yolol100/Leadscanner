# Leadscanner repository agent contract

## Current scope
- Build a fast cold-lead pipeline from a clean slate.
- Treat the current repository as implementation material, not as a legacy requirements source.
- The only historical lead state that remains authoritative is the Google Sheet Lead Dedupe Registry.
- Use that registry only to suppress companies already seen in prior concepts/outreach. Never use it as prospect research or outreach evidence.

## Execution rules
- Work on main unless the user explicitly requests another branch.
- Put cheap gates before network-heavy research.
- Keep each stage contract explicit and fail closed when required identity/evidence is missing.
- Prefer one execution workflow over multiple event listeners and artifact handoffs.
- Reuse existing code only when it is clearly useful for the new critical path.
- Keep changes bounded to the active phase; avoid unrelated refactors.

## Safety
- Never infer an email address or prospect fact.
- Never automatically send commercial outreach.
- Repository/runtime automation may create review artifacts only when a later phase explicitly implements that path.

## Validation
- Run focused tests for the changed execution path first.
- Add wider regression coverage only when that wider path becomes active again.
- Report completion only with exact repository and workflow evidence.
