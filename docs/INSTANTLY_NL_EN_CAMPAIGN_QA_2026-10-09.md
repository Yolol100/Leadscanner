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
| Exact campaign | Webactueel NL - Websiteadvies (Concept) | Webactueel EN - Website Advice (Draft) |
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

## Independent no-go checks

1. **Legal contact basis:** 1,128 imported leads recorded as
   `review_required`, with zero verified consent/existing-customer
   references. Historical draft copy and public business addresses are not
   permission evidence. The stage action is not permission; do not
   manufacture, bulk-mark or auto-approve consent.
2. **Sender account:** one Instantly account, status `-1` (inactive);
   zero active senders. The user is reconnecting the account separately.
3. **Global provider blocklist:** authenticated read still fails with
   `instantly_network_error`. Official Instantly blocklist endpoint is
   `GET /api/v2/block-lists-entries`. The local canonical dedupe registry is
   independently required and does *not* replace the provider blocklist.
   The activation code now refuses Leadscanner campaign activation unless
   a fresh provider list read succeeds and every recipient is clear.
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

## Release checklist

- [x] Only two expected campaigns exist.
- [x] Both Draft with no assigned sender and no outbound sends.
- [x] Six steps saved; sequence contracts checked in Instantly audit.
- [x] Exact `reviewed_mail` NL/EN routing and unknown-language hold tested.
- [x] Local Liquid fixture tests for complete, missing and partial evidence.
- [x] Provider blocklist gate added before Leadscanner activation.
- [ ] Reconnect sending account; verify status/limits/health/warmup.
- [ ] Resolve provider blocklist read and recheck exclusions.
- [ ] Document genuine per-lead contact basis and suppression evidence.
- [ ] Stage and verify an individually approved, legally eligible test lead.
- [ ] Run Instantly Preview with populated variables and inspect all 3 emails
      per language; check linked unsubscribe and actual account signature.
- [ ] Explicit new activation approval; no automatic launch.

**Decision:** engineering configuration and static QA **PASS** for the verified
scope; operational and legal go-live **BLOCKED** until the last five gates
are independently evidenced. Do not claim any delivery/conversion result.
