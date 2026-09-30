# Leadscanner repository agent contract

## Scope
- This repository is the controlled discovery, verification and review-draft runtime for the `leads` Skill.
- `webactueel-workflow` remains the cross-skill controller; Leadscanner does not become a second workflow owner.
- Never infer email addresses, contact permission or business facts from memory, trend sources or model guesses.
- Outreach stays review-only; no automatic send.

## Agent capability and impact policy
- Classify every intended action as `read_only`, `safe_write` or `high_risk_write`.
- `read_only`: inspect/search/test without external mutation.
- `safe_write`: bounded, reversible repository/runtime changes with preflight and exact readback.
- `high_risk_write`: sending outreach, destructive changes, permission/security changes, production deploys or broad external mutations. These are outside the normal Leadscanner runtime unless the owning workflow explicitly authorizes them.
- Tool availability or green CI never grants contact or write permission.

Before non-trivial code changes, build a bounded impact context from changed paths, direct dependencies, workflow contracts and relevant tests. Generated indexes/graphs are commit-bound evidence/cache only, never lead truth or durable memory.

GitHub Trending and external repositories are discovery-only. Reuse patterns only after owner-fit, primary-source/currentness checks and license/usage-rights review. Never import scraped identities or contact data from trend repositories.

## Validation
Run the repository's existing tests and workflow validation for every changed execution path. Preserve bounded batches, exact evidence, draft readback and the no-send invariant.
