# Instantly integration

This repository contains a controlled Instantly API v2 bridge for Project Leads.

## Ownership

- `webactueel-workflow` remains the controller.
- Live Project Leads remains canonical policy.
- `Yolol100/Leadscanner` is execution/evidence only.
- Normal outreach remains `send_permission=none`.

## What the Leads-specific bridge can do

The original bridge supports four commands:

1. `CONNECTION_TEST` — read-only API connectivity probe.
2. `CAMPAIGN_STATUS` — read-only campaign status check.
3. `SYNC_SELECTED_TO_LIST` — dry-run or explicit apply of already validated OutreachQueue leads to an Instantly lead list.
4. `SYNC_SELECTED_TO_CAMPAIGN` — dry-run or explicit apply of already validated OutreachQueue leads to an Instantly campaign only when the campaign is `draft` or `paused`.

This Leads-specific bridge does **not** activate campaigns, resume campaigns, send emails, edit sequences, or bypass the Leads validation/suppression/copy gates.

## Secret setup

Create a GitHub Actions repository secret named:

`INSTANTLY_API_KEY`

Never commit the key to the repository or paste it into an issue. Rotate any key that has previously been shared in chat or another public surface.

The existing `GOOGLE_SERVICE_ACCOUNT_JSON` secret and `OUTREACH_SPREADSHEET_ID` variable are reused to load private Lead data and the private Instantly command/result transport.

## Leads-specific ChatGPT -> GitHub command route

Create an issue owned by `Yolol100` with title exactly:

`INSTANTLY BRIDGE`

Examples:

### Connection test

```text
COMMAND=CONNECTION_TEST
```

### Campaign status

```text
COMMAND=CAMPAIGN_STATUS
CAMPAIGN_ID=<campaign-id>
```

### Dry-run selected leads to a list

```text
COMMAND=SYNC_SELECTED_TO_LIST
LIST_ID=<list-id>
EXPECTED_COUNT=2
LEAD_ID=<opaque-lead-id-1>
LEAD_ID=<opaque-lead-id-2>
APPLY=false
```

### Apply selected leads to a paused/draft campaign

```text
COMMAND=SYNC_SELECTED_TO_CAMPAIGN
CAMPAIGN_ID=<campaign-id>
EXPECTED_COUNT=2
LEAD_ID=<opaque-lead-id-1>
LEAD_ID=<opaque-lead-id-2>
APPLY=true
```

Because this repository is public, issue commands must contain only opaque lead IDs and destination IDs. Never place email addresses, names, message copy, API keys, or other private lead data in the issue body.

## Leads-specific safety gates

Before an Instantly lead-staging write, every selected row must already pass the existing Leadscanner `OutreachQueue` validation gate, including suppression and V17.2 copy validation.

For campaign staging writes the Leads-specific bridge reads the campaign state first and refuses to add leads unless the campaign is `draft` or `paused`. It never changes campaign status.

After an apply, the bridge queries Instantly again and requires readback for every selected email. If exact readback is missing, the command fails closed.

Public GitHub feedback contains only status, counts, and campaign state. It does not echo prospect PII or email content.

## Full API v2 parity layer

In addition to the Leads-specific commands, `scripts/instantly_api_v2.py`, `scripts/instantly_private_request.py` and `.github/workflows/instantly-full-api-command.yml` expose every operation present in Instantly's official API v2 OpenAPI document at runtime. The full-surface route is intended to approximate the complete administrative/action capability available through Instantly's API/MCP ecosystem when direct ChatGPT MCP is unavailable.

The runtime source for capability discovery is:

`https://api.instantly.ai/openapi/api_v2.json`

A method/path is rejected unless it exists in that official v2 schema. This avoids a stale handwritten allowlist and automatically follows documented v2 additions.

Because this repository is public, full request/response payloads are never transported through public issue content. The private Google Sheet tabs `InstantlyCommands` and `InstantlyResults` carry request bodies and private results. The public issue contains only an opaque `REQUEST_ID` and uses title `INSTANTLY API`.

Writes default to plan-only. `.github/workflows/instantly-full-api-command.yml` runs `scripts/instantly_command_guard.py` before the API executor. The guard matches the requested operation against the current official OpenAPI schema and requires the exact `CONFIRM-...` token for destructive/high-impact operations. This includes AI Agent changes, lead adds/moves/assignment/lifecycle changes, live campaign edits/control, sender-account changes, webhook changes, workspace membership/administration and suppression changes. Existing executor-level confirmation rules remain as an additional safety layer.

This parity layer does not change Project Leads ownership or policy. For prospect/outreach behavior, live Project Leads validation, suppression, evidence and copy gates remain binding even though the generic API layer is technically capable of broader account administration.

See `docs/INSTANTLY-API-V2-FULL-SURFACE.md` for the private transport, risk model and request format.

## Dynamic product-surface audit

The Instantly UI changes faster than a static integration document. `scripts/instantly_surface_audit.py` compares the current official OpenAPI schema against the main product surfaces and reports each surface as `read_write`, `read_only` or `not_proven`.

Run locally:

```bash
PYTHONPATH=scripts python3 scripts/instantly_surface_audit.py --report instantly-surface-report.json
```

Or create a GitHub issue owned by `Yolol100` with title exactly:

`INSTANTLY SURFACE AUDIT`

The issue workflow needs no Instantly API key because it audits the public official schema only. The safe public result contains capability classifications, not account data.

The audit intentionally distinguishes AI Agent configuration from Instantly AI/Copilot memory. A live 2026-09-16 schema audit proved public v2 administration for AI Sales Agent and its guidance rules, Inbox Manager and its guidance, AI Lead Finder, AI Deliverability Agent and SuperSearch saved searches. It did not prove current public v2 control for Copilot Business Details, Customer Profiles, Saved memories, Copilot chats/tasks, native Automations, CRM Calls/SMS/Tasks or Website Visitors configuration. Re-run the audit before relying on this snapshot.

See `docs/INSTANTLY-SURFACE-COVERAGE.md` for the control boundary and operating guidance.
