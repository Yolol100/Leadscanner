# Instantly command inbox

This directory is the GitHub-only control plane used by ChatGPT web.

ChatGPT creates a **new immutable JSON file** in `instantly-commands/inbox/`.
The existing `.github/workflows/leads-cold.yml` workflow validates the command,
uses the repository's Instantly secret, executes one allowlisted action, and
uploads a JSON result artifact. Existing command files must never be edited or
reused.

## Read command

```json
{
  "schema_version": "leadscanner-instantly-command/1.0",
  "command_id": "20261007-list-campaigns-001",
  "action": "list_campaigns",
  "args": {
    "limit": 50
  },
  "requested_by": "chatgpt"
}
```

The file name must be exactly `<command_id>.json`.

## Write command

Every write needs an exact confirmation string bound to the action and its main
target.

```json
{
  "schema_version": "leadscanner-instantly-command/1.0",
  "command_id": "20261007-pause-campaign-001",
  "action": "pause_campaign",
  "args": {
    "campaign_id": "CAMPAIGN_ID"
  },
  "confirm": "EXECUTE pause_campaign CAMPAIGN_ID",
  "requested_by": "chatgpt"
}
```

Writes are refused on a GitHub Actions re-run because Instantly has no general
idempotency-key mechanism. Create a fresh command file for an intentional retry.

## Allowed actions

Read:
`list_campaigns`, `get_campaign`, `campaign_sending_status`,
`campaign_analytics`, `list_leads`, `get_lead`, `list_emails`,
`get_email`, `count_unread_emails`, `list_accounts`, `get_account`,
`warmup_analytics`, `daily_account_analytics`, `list_blocklist`,
`get_blocklist_entry`, `get_background_job`.

Explicit writes:
`create_campaign_draft`, `update_campaign`, `pause_campaign`,
`activate_campaign`, `delete_campaign`, `update_lead`, `delete_lead`,
`update_interest`, `reply_email`, `forward_email`, `send_test_email`,
`mark_thread_read`, `update_account`, `pause_account`, `resume_account`,
`enable_warmup`, `disable_warmup`, `block_email`, `block_domain`,
`delete_blocklist_entry`, `stage_approved_lead`.

There is deliberately **no generic HTTP method/path action**.

## Safety boundaries

- Leadscanner sourcing and prospect eligibility still use the canonical live
  dedupe registry before accepting a new company.
- `stage_approved_lead` still requires an immutable preview, exact approval
  token and live dedupe revalidation.
- Campaign activation performs a fresh preflight before the activate call.
- Reply/forward/test-send/activation can run only from an explicit confirmed
  command. Nothing in the scheduled sync sends mail.
- Never put SMTP/IMAP passwords, OAuth tokens, API keys, service-account JSON,
  or other secret material in a command file. Secrets stay in GitHub Actions
  Secrets.
- Existing account settings may be changed, but account credential onboarding
  is intentionally not accepted through committed command JSON.
- The scheduled Instantly sync only updates **existing** canonical registry rows
  and never creates a new lead or registry identity.

## Results

A command run uploads an Actions artifact named
`instantly-control-<github-run-id>`. It contains one JSON file per command plus
`summary.json`.

The scheduled reconciliation uploads
`instantly-sync-<github-run-id>`.
