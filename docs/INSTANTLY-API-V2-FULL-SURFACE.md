# Instantly API v2 full-surface bridge

## Purpose

`Yolol100/Leadscanner` can use the official Instantly API v2 surface through a controlled, schema-validated executor. This exists for ChatGPT users who cannot use Instantly's hosted MCP server directly.

The bridge is an execution/evidence capability only. `webactueel-workflow` remains controller and live Project Leads remains the policy source for prospect/outreach decisions.

## Source of truth for capabilities

The executor downloads Instantly's official OpenAPI document at runtime:

- `https://api.instantly.ai/openapi/api_v2.json`

A request is rejected unless its HTTP method and concrete path match an operation in that document. This means newly documented API v2 endpoints become available without adding one hard-coded command per endpoint, while invented/non-v2 paths fail closed.

Current official API documentation exposes resources including accounts, campaign/account mappings, campaigns and subsequences, leads/lists/labels, emails, analytics, blocklist, custom tags, API keys, audit logs, background jobs, CRM actions, inbox placement, SuperSearch/enrichment, webhooks/events, workspace/billing/members/groups, OAuth and related workspace/admin resources. Availability still depends on the active Instantly plan, API-key scopes, workspace permissions and what Instantly exposes through API v2.

## Public/private boundary

This repository is public. Never put Instantly request bodies, email addresses, message copy, API keys, reply contents or other private account data into a GitHub issue.

Private requests live in the private Google Sheet `Webactueel Leadlijst`:

### `InstantlyCommands`

`request_id | status | method | path | query_json | body_json | apply | confirmation | verify_json | note | result_status | result_summary`

### `InstantlyResults`

`request_id | recorded_at | status | method | path | risk | applied | response_json | verification_json`

The public GitHub issue contains only:

```text
REQUEST_ID=<opaque-id>
```

with title exactly:

```text
INSTANTLY API
```

The private result can contain PII/account data and must stay in the private Sheet. Public GitHub feedback contains only safe status/operation/count metadata.

## Risk model

- `GET`: read-only and may execute immediately.
- normal `POST/PATCH/PUT`: write; default is plan-only until `apply=true` is placed in the private request.
- `DELETE`: destructive; requires `apply=true` plus the exact generated confirmation token.
- high-impact operations such as email reply/forward/test-send, campaign/subsequence resume/activation, account resume/warmup changes, workspace ownership/removal, API-key management, DFY/order, enrichment, inbox-placement tests and OAuth mutations require `apply=true` plus the exact generated confirmation token.

A plan-only request returns `CONFIRM-...` without making the API mutation. Put that exact token in the private row and rerun only when the action is intentionally approved.

Where a stable read endpoint exists, set `verify_json` to force a read-only readback after the mutation. Verification itself is blocked unless it resolves to an official GET operation.

## Examples

Read campaigns:

```json
{
  "method": "GET",
  "path": "/campaigns",
  "query": {"limit": 10},
  "apply": false
}
```

Plan a campaign update without applying it:

```json
{
  "method": "PATCH",
  "path": "/campaigns/<campaign-id>",
  "body": {"name": "Webactueel - Quote Intake"},
  "apply": false
}
```

A destructive or high-impact plan returns a confirmation token. Only a second private request with the exact same method/path/query/body, `apply=true`, and that exact token can execute it.

## Relationship to the earlier Leads-specific bridge

The existing `INSTANTLY BRIDGE` workflow remains the safest shortcut for staging already validated OutreachQueue leads into a list or draft/paused campaign. It enforces Project Leads validation and suppression gates.

The full-surface `INSTANTLY API` workflow is the administrative/API parity layer. It must not be used to bypass Project Leads evidence, compliance, suppression or copy gates for prospecting/outreach. Direct send/activation is technically available only because the user requested API/MCP parity; it remains a high-impact action with explicit confirmation.

## What cannot be promised

This bridge can only mirror what Instantly publishes in API v2 and permits for the current API key/workspace/plan. A dashboard-only or hosted-MCP-only feature with no API v2 operation cannot be implemented through API v2. The dynamic catalog command is the authoritative runtime check for current coverage.
