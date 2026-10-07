# Instantly / Leadscanner audit prompt

Use this prompt for a full repository audit. The audit is not complete when issues
are merely listed: every reproducible issue inside the current Leadscanner scope
must be fixed on `main`, covered by a targeted regression test, and re-audited.

## Role

Act as a repository, API-contract, lifecycle, regression, concurrency and
production-readiness engineer for `Yolol100/Leadscanner`.

## Ground truth

Use the current `main` branch as implementation truth. For Instantly behavior,
compare against the current official Instantly API v2 documentation / official
`Instantly-ai/instantly-starter-kit`. Do not invent undocumented endpoints or
status meanings.

Do not reintroduce legacy Google Maps discovery or old Leads behavior. Preserve
the current PDOK + Overture -> official website -> canonical Dedupe Registry ->
human approval architecture.

## Non-negotiable invariants

- New prospects are checked against the canonical retained dedupe registry.
- Leadscanner-sourced contacts cannot bypass exact approval and live dedupe
  revalidation.
- Preview is mutation-free.
- Writes are explicit, named and allowlisted; there is no arbitrary HTTP
  method/path command.
- A GitHub Actions rerun cannot repeat an Instantly write.
- Command files are immutable after creation.
- Send-capable actions require exact confirmation and campaign activation has a
  fresh preflight.
- Safe reads may retry transient failures; non-idempotent writes must not retry
  automatically.
- Secrets must not be written into command JSON, logs or result artifacts.
- Instantly -> registry synchronization can update existing identities only and
  cannot send or create new prospects.
- Stale/out-of-order events cannot roll registry state backward.
- Concurrent Instantly control and registry synchronization cannot clobber the
  same canonical registry row.
- Only the single active cold workflow remains.

## Audit method

Run the following loop until every check is green:

1. Inspect current repository state, workflow, command executor, Instantly
   client, sync/event logic, registry writer, approval boundary and tests.
2. Cross-check every used Instantly endpoint, method, success code, async
   behavior, campaign/account status and verification status against official
   v2 sources.
3. Threat-model retries, workflow reruns, duplicate commands, modified command
   files, stale callbacks, concurrent registry writes, partial failures,
   timeouts, 429/5xx responses, 200-with-error responses and missing readback.
4. Run syntax/compile checks and the complete focused active-path unit suite.
5. Add adversarial regression tests for every discovered weakness before or
   alongside the minimal fix.
6. Apply the minimal production-safe fix directly on `main`.
7. Re-run the complete suite and a read-only live Instantly smoke test through
   ChatGPT -> GitHub Actions -> Instantly.
8. Repeat the audit after fixes; do not stop at the first green run.

## 10-point acceptance rubric

Award one point only when the criterion is demonstrably green:

1. Architecture / single-workflow / no legacy-source regression.
2. Dedupe + immutable preview + exact approval boundary.
3. Command allowlist, immutability, confirmation and rerun idempotency.
4. Current Instantly v2 endpoint and status contract fidelity.
5. Sending safety and activation readiness checks.
6. Async/background-job and readback correctness.
7. Stale-event, terminal-state and registry race protection.
8. Retry, timeout, rate-limit and error-hygiene behavior.
9. Secret handling / output redaction / public-repository hygiene.
10. Full CI plus a real read-only end-to-end Instantly smoke test.

A reported score of 10/10 is allowed only when all ten checks pass after the
final fixes. If a live external dependency prevents proof, report less than
10/10 and name the exact unresolved proof gap.

## Final evidence

Report the final `main` commit, GitHub Actions run ID, test count, live smoke
run ID/result, the fixed findings, and the final 10-point score. Do not claim
success from an earlier commit.
