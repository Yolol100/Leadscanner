# Instantly NL/EN Campaign QA — 2026-10-09

## Scope and authoritative evidence

Workspace campaign and account evidence: successful read-only GitHub Actions run
[37929923573](https://github.com/Yolol100/Leadscanner/actions/runs/37929923573),
artifact `instantly-control-37929923573`. No API payload or private recipient data is
stored in this note. Current deployment code must also pass the latest Actions
CI run. All settings below are point-in-time readbacks, **not a claim that
outreach can legally be sent**.

## Verified campaigns

| Property | NL | EN |
|---|---|---|
| Exact campaign | Websiteadvies NL | Websiteadvies EN |
| ID | `5c720281-fd07-4c47-8155-c88d7d3c09b8` | `fd405145-4bf5-40c5-b6ae-2e7f5af6120c` |
| Instantly status | Draft (0) | Draft (0) |
| Email steps / variants | 3 / 3 | 3 / 3 |
| Campaign leads | 0 | 0 |
| Assigned senders | 0 | 0 |
| Other campaigns | 0 (workspace-wide) | 0 (workspace-wide) |

Original 1,128 mijn.host drafts remain in the isolated source list. One historical
contact from the removed legacy campaign remains in a separate non-sending archive.
There is no evidence of a live test send during this QA.

## Approved copy and personalization data contract

- Step 1 uses exact approved per-lead `{{leadscanner_subject}}` and
  `{{leadscanner_body}}`. Never infer a missing observation or rewrite reviewed
  legacy content automatically.
- Step 2 waits **four calendar days after Step 1**, not immediately. When both
  `leadscanner_observation` and `leadscanner_value_action` are present,
  the Liquid conditional references those verified facts; otherwise it selects
  generic copy. Step 3 waits five calendar days after Step 2. The final step's
  unused delay is zero because there is no next step.
- Liquid guards for missing verified facts and a mandatory subject/body contract
  are tested in `tests/test_instantly_template_rendering.py`,
  `tests/test_instantly_campaign_copy.py`, `tests/test_instantly_client.py`.
  Local rendering is a **simulation only**, not a provider-rendered guarantee.
- `approved_custom_variables` rejects nested merge/Liquid delimiters in lead
  copy or website-derived facts, preventing the lead from injecting a new
  provider template at send time.
- Future approved `reviewed_mail` leads use `auto_language`, which classifies
  the actual approved text and fails closed for ambiguous or mismatched
  NL/EN copy. Unknown country/TLD/name never decides language.
- Exact user approval, canonical registry revalidation, reviewed copy,
  proper campaign identity, **Draft status**, zero sender accounts and
  Instantly lead readback are required before staging.

## Provider options (last live configuration readback)

- Send schedule: weekdays 09:30–16:30 Netherlands local time
  (Instantly provider equivalent `Arctic/Longyearbyen` handles CET/CEST).
- Campaign daily limit 10; max new leads daily 5; minimum email gap 12 minutes.
- Stop on reply and company reply enabled; auto-reply stop enabled.
- Open tracking and click tracking disabled; text-only enabled.
- Unsubscribe header enabled; risky contacts disabled.

Account-level daily limits and warmup must be rechecked once an active
sender account is reconnected. Account caps apply across campaigns.

## Latest independent settings readback

A second provider read-only audit confirmed both Drafts using
[GitHub Actions run 37933798576](https://github.com/Yolol100/Leadscanner/actions/runs/37933798576):
**11/11 expected campaign settings match per language**, with zero mismatches,
zero missing provider fields and zero assigned senders. Each schedule contains
the expected Monday-Friday 09:30-16:30 CET/CEST window (zone:
`Arctic/Longyearbyen`).

Regressions on `main` also include:
- nested template/Liquid syntax rejection for future lead data;
- suppression-list and domain checks in the final activation preflight;
- both languages' three-step local Liquid fallback scenario matrix;
- non-zero intervals between both follow-up sends.

Code regression runs:
[37933105186](https://github.com/Yolol100/Leadscanner/actions/runs/37933105186)
and [37933363355](https://github.com/Yolol100/Leadscanner/actions/runs/37933363355)
both passed. A local Liquid simulation remains *not* an Instantly Preview.

## Independent no-go checks

1. **Legal contact basis:** 1,128 imported leads recorded as
   `review_required`, with zero verified consent/existing-customer
   references. Historical draft copy and public business addresses are not
   permission evidence. The stage action is not permission; do not
   manufacture, bulk-mark or auto-approve consent.
2. **Sender account:** one Instantly account, status `-1` (inactive);
   zero active senders. The user is reconnecting the account separately.
3. **Global provider blocklist:** an earlier authenticated read failed with
   `instantly_network_error`, but the new read-only provider audit on
   [37938304051](https://github.com/Yolol100/Leadscanner/actions/runs/37938304051)
   **succeeded and reported zero blocked entries at that moment**.
   Official endpoint: `GET /api/v2/block-lists-entries`. The local canonical
   dedupe registry is independently required and does *not* replace the
   provider blocklist. The activation code requires a **fresh** global provider
   blocklist read and recipient/domain recheck immediately before activation.
   One successful read does not prove future availability.
4. **Real provider Preview:** no campaign leads and no active account exist.
   Therefore a lead-populated Instantly Preview and test email have **not**
   yet been conducted. Synthetic no-network preview tests do not substitute.
5. **Copy outcomes:** no delivered messages/replies are available to support
   empirical reply-rate or a '10/10' conversion guarantee.

References:
- https://help.instantly.ai/en/articles/6687668-liquid-syntax
- https://help.instantly.ai/en/articles/7916860-time-to-wait-between-steps
- https://help.instantly.ai/en/articles/6135930-how-to-add-and-use-variables-in-campaigns
- https://help.instantly.ai/en/articles/7002900-preview-and-send-test-emails
- https://help.instantly.ai/en/articles/6222396-campaign-options
- https://developer.instantly.ai/api-reference/groups/block-list-entry
- https://www.acm.nl/nl/verkoop-aan-consumenten/reclame-en-verleiden/spam-voorkomen-uw-reclame


## Continuation verification — live workspace and copy QA

Fresh read-only Actions audit
[37938304051](https://github.com/Yolol100/Leadscanner/actions/runs/37938304051)
reconfirmed **exactly two campaigns**, no extras, both Draft with zero
campaign leads/senders, **11/11 options per language matched**, and a
successful Instantly global provider blocklist read with **zero current
entries**. The one sender account remained inactive, and all **1,128** imported
source records remained `review_required` without documented contact basis.
No action in that audit sent, activated or deleted any campaign or lead.

The aggregate-only mail analysis was refined without modifying mail content:
[37938696038](https://github.com/Yolol100/Leadscanner/actions/runs/37938696038)
reported 1,128 subject/body pairs complete, NL 1,066, EN 59, unknown 3,
zero messages without a question mark, **two messages with one question**,
**1,108 with two questions**, and **18 with three or more**. Other soft review
flags: 11 messages under 35 words, 3 without an obvious opt-out phrase,
zero unrendered template markers, zero missing sender identification, and
zero separately stored verified observation/action pairs. These are
**editorial indicators only**, not evidence of individual mail quality,
consent, rendering accuracy, delivery, replies or conversions.

The aggregate audit keeps subject/body/addresses private; the next editorial
step is a consent-safe review of selected outliers, not a mass rewrite of
approved historical mail. The reviewed-mail NL/EN sequence contracts remain
separate from actual provider Preview and test sends. Regression workflow
[37938696038](https://github.com/Yolol100/Leadscanner/actions/runs/37938696038)
passed **355 focused tests**, including the new private-safe question-count
distribution cases.

**Operational decision unchanged:** configuration/static QA PASS within this
defined scope; activation **NO-GO** until genuine per-lead contact basis,
healthy sending account, actual variable-populated Instantly Preview,
current suppression checks and fresh explicit launch approval are all evidenced.

## Release checklist

- [x] Only two expected campaigns exist.
- [x] Both Draft with no assigned sender and no outbound sends.
- [x] Six steps saved; sequence contracts checked in Instantly audit.
- [x] Exact `reviewed_mail` NL/EN routing and unknown-language hold tested.
- [x] Local Liquid fixture tests for complete, missing and partial evidence.
- [x] Provider blocklist gate added before Leadscanner activation.
- [ ] Reconnect sending account; verify status/limits/health/warmup.
- [x] Provider blocklist successfully fetched in latest read-only audit (0 entries).
- [ ] Repeat provider and canonical suppression checks at actual activation.
- [ ] Document genuine per-lead contact basis and suppression evidence.
- [ ] Stage and verify an individually approved, legally eligible test lead.
- [ ] Run Instantly Preview with populated variables and inspect all 3 emails
      per language; check linked unsubscribe and actual account signature.
- [ ] Explicit new activation approval; no automatic launch.

**Decision:** engineering configuration and static QA **PASS** for the verified
scope; operational and legal go-live **BLOCKED** until the last five gates
are independently evidenced. Do not claim any delivery/conversion result.

## Final continued audit — 2026-10-09

**Evidence:** [full regression run 37948776593](https://github.com/Yolol100/Leadscanner/actions/runs/37948776593) (375/375 tests pass, `main` at `cc3411a`) and [10-command provider readback 37948334148](https://github.com/Yolol100/Leadscanner/actions/runs/37948334148) (10/10 read-only actions green, no mutations). Results are scoped to these runs, not proof of future provider availability.

**Confirmed repairs:**
- Blocklist pagination now fails closed on an empty page with a remaining cursor; parent-domain exclusions cover subdomains.
- Duplicate imported source addresses block routing; unreadable Instantly blocklists block new lead staging.
- New-lead staging rechecks campaign Draft state, reviewed sequences, and key safety options just before `POST /leads`. Historical language routing now rejects NL/EN follow-up copy drift.
- Public Actions result files redact addresses, contact names, domains, custom variables, and email content; sync error reports no longer echo recipient addresses.
- Archived legacy contact can be checked after the source campaign was deleted, without exposing personal data or altering the archive.

**Live readback:**
- Two campaigns exactly, both Draft, zero campaign leads and zero assigned senders.
- NL and EN each have three approved steps; both match reviewed copy and 11/11 tested safety settings, including weekday 09:30–16:30 schedule.
- 1,128 isolated historical concepts remain present: 1,066 NL, 59 EN, three ambiguous/held. All 1,128 remain unverified for lawful sending. No lead was automatically moved or sent.
- Global Instantly blocklist read succeeded with zero entries **at the audited moment**; the separate canonical registry still applies.
- Retired archive: one preserved contact with 14 stored custom fields. Original-vs-archive byte equality cannot be independently established after deletion.
- One sending account exists but is not actively connected; provider-rendered, populated Previews of all six emails and sender-specific deliverability remain unproven.

**Residual privacy risk:** The repository is public, and some *historical immutable command files* contain literal email addresses. New result redaction does not erase past Git history, commands, or old artifacts. Do not rewrite history, delete records, or change repository visibility without an explicit retention/privacy decision.

**Release decision:** Code/regression and the audited live Draft configurations: **PASS**. Campaign activation, real message rendering, per-lead legal basis and sending readiness: **NO-GO**. Keep send/activate off until those gates are independently verified and a new explicit approval is given.
