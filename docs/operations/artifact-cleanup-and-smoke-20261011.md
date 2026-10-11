# Leadscanner Actions artifact privacy cleanup — 11 October 2026

## Scope and result

The repository was publicly readable during the investigation. Historical Actions artifacts can contain prospect contact data and review copy. An earlier preview archive was confirmed to contain recipient fields; no addresses or copy are reproduced in this report.

A narrowly authorized one-time artifact cleanup and three independent API readback passes were performed using short-lived GitHub Actions credentials with `actions:write` permission.

| GitHub Actions run | Deleted | Artifacts after run | Outcome |
| --- | ---: | ---: | --- |
| [38148702649](https://github.com/Yolol100/Leadscanner/actions/runs/38148702649) | 71 | 72 | Initial privacy purge and offline synthetic preview passed |
| [38148936546](https://github.com/Yolol100/Leadscanner/actions/runs/38148936546) | 1 | 72 | Strict review intentionally failed: 32 outputs remained unclassified |
| [38149118132](https://github.com/Yolol100/Leadscanner/actions/runs/38149118132) | 33 | 40 | Final scan passed: 0 suspected, 0 unclassified |

**Total deletion operations: 105** (including short-lived command-control outputs produced by verification runs).

All 40 retained artifacts matched one of the two explicit aggregate-only output name contracts: `site-research-<offset>-<run>` or `instantly-sync-<run>`. In the previous code audit these formats were designed to contain only counts and statuses, not contact addresses or email copy. This is a verification of repository API inventory and declared artifact formats, **not a claim of forensic inspection of every historical byte**. The source repository remains public and the real-prospect preview/staging/draft privacy gate remains active.

## Safe preview validation

The synthetic preview used a reserved `.invalid` domain and fictitious company/contact data only. It exercised the real local post-research pipeline:

- five first-party-labeled observations ranked by score;
- human-reviewed NL copy and a separate fact-only review mode;
- review-queue Markdown/CSV and exact-content approval token;
- rejection of an altered observation using the old approval token;
- sealed preview snapshot, digest validation, ZIP readback, and privacy-safe run overview.

No business website, Instantly API, mailbox, or registry was accessed by the synthetic test; **network calls, sends and remote mutations were zero**. It does not replace a full live preview with consent-reviewed inputs once the repository is made private.

## Remaining security boundaries

- Previously downloaded artifacts or archived copies elsewhere cannot be recalled by deleting Actions artifacts.
- Existing Actions logs were not erased, and GitHub-hosted access history has not been forensically audited here.
- The user must change repository visibility to **Private** before resuming real-person preview or staging; this is not done by cleanup.
- The cleanup execution jobs were removed from the workflow afterward. The normal public-repository Instantly control job now uploads no artifact when there are no new commands and never uploads command results on a public repository.
- The aggregate-only format allowlist and tests remain in source for future checks.
