# Instantly surface coverage

This repository does not assume that every visible Instantly screen is controllable through API v2.

The source of truth for machine-control capability is Instantly's current official API v2 OpenAPI document:

`https://api.instantly.ai/openapi/api_v2.json`

Run:

```bash
PYTHONPATH=scripts python3 scripts/instantly_surface_audit.py --report instantly-surface-report.json
```

The audit classifies each product surface as:

- `read_write` - the current official schema proves at least one matching mutating operation;
- `read_only` - matching operations exist but the matched surface has no proven mutating operation;
- `not_proven` - no sufficiently specific official v2 operation was found.

The audit is deliberately conservative. `not_proven` means the repository must not claim control over that surface. It does not mean Instantly can never expose it later.

## Surfaces checked

The current audit tracks campaigns, leads, lead labels/lists, email accounts, Unibox email, reports/analytics, custom tags, workspace/billing/members, blocklist, webhooks, audit logs, API keys, SuperSearch and saved searches, Inbox Placement, Website Visitors, AI Sales Agent, AI Sales guidance, Inbox Manager and guidance, Lead Finder Agent, Deliverability Agent, Instantly AI Business Details/Customer Profiles/Saved memories/Tasks/Chats, native Automations, CRM Opportunities/Calls/SMS/Tasks and Preferences.

## Important capability split

The current public v2 schema can expose more AI Agent control than the Instantly AI/Copilot memory UI.

The runtime audit is designed to distinguish, for example:

- AI Sales Agent CRUD from Instantly AI Business Details;
- AI Sales Agent guidance rules from Copilot Saved memories;
- Inbox Manager guidance from Copilot Customer Profiles;
- SuperSearch saved-search CRUD from UI-only discovery state.

Never collapse those categories into a generic `AI memory` capability claim.

A live runtime audit on 2026-09-16 proved current official v2 operations for AI Sales Agent administration/guidance, Inbox Manager administration/guidance, AI Lead Finder, AI Deliverability Agent and SuperSearch saved searches. The same audit did not prove public v2 control for Copilot Business Details, Customer Profiles, Saved memories, Copilot chat/task state, native Automations, CRM Calls/SMS/Tasks or Website Visitors configuration. Re-run the audit before relying on this snapshot because Instantly can add or rename endpoints.

## Safety boundary

Surface coverage never bypasses Project Leads policy.

- Live Project Leads remains the policy source.
- SuperSearch/AI/CRM data is discovery or execution context, not prospect qualification proof.
- Generic API writes are plan-first.
- The full API workflow additionally runs `scripts/instantly_command_guard.py` before any external request.
- Destructive actions and high-impact changes such as AI Agent changes, lead staging/moves, live campaign edits/control, sender-account changes, webhook changes, workspace membership changes and suppression changes require the exact confirmation token before `apply=true` can proceed.
- Public GitHub issues contain only opaque request IDs; private payloads/results remain in the private command/result transport.

## Current official operating guidance

When configuring cold outreach, re-check Instantly's current Help Center before applying settings. As of the validation date used for this adapter, official guidance supported:

- Stop sending follow-ups on reply.
- Campaign slow ramp for gradual volume growth.
- Text-only first email / delivery optimization for deliverability.
- BounceShield/BounceProtect kept enabled.
- AI smart pause/resume for out-of-office when automatic reply tagging is enabled and Stop on auto-reply is disabled.
- SuperSearch `Skip already owned` and `One lead per company` as available discovery controls.
- 2-3 day spacing as a normal follow-up recommendation.

These are operating defaults, not permanent API assumptions. Runtime API capability and live Project Leads policy must be re-read before a write.
