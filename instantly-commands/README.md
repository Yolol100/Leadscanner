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

For a compact, copy-free decision on the current Instantly sequence, use
`action: "audit_campaign_sequence"` with `args: {"campaign_id": "..."}`.
This read-only action returns step/variant counts, referenced merge-field names,
whether reviewed Leadscanner mail copy is still required, the SHA-256
sequence fingerprint, unmapped template variable names, and whether the
campaign is Draft/Paused. It does not return email subjects, bodies or leads.
An `evidence_only_template_candidate` decision is structural only: it is not
permission to change the campaign, bypass review or send email.

## Evidence-only three-email campaign approval

A default `instantly_sequence` preview does not generate a separate email. To stage an approved lead, first audit a **Draft** campaign using `audit_campaign_sequence`. The audit must show exactly one sequence and **three email steps**, no unresolved template fields, no `leadscanner_subject` or `leadscanner_body`, and both `leadscanner_observation` and `leadscanner_value_action` in the template. Review the actual subjects, bodies, variants and legal/contact basis in Instantly independently; the copy-free audit does not certify those.

The command `stage_approved_lead` accepts an additional `args.sequence_approval` value:

```text
APPROVE_INSTANTLY_SEQUENCE <campaign_id> <sequence_fingerprint>
```

Use the exact fingerprint returned by the read-only audit. The existing exact command confirmation and exact lead approval token are **also required**. Each lead write re-reads the campaign and rejects changed fingerprints, unsafe campaign status or missing variables. A fact-only review can never stage into an Active or Paused campaign. Legacy reviewed-mail approvals also cannot stage into evidence-only campaigns without their approved copy placeholders, so they cannot bypass fingerprint approval. No campaign is activated or email sent by staging. **Separate activation safety:** `audit_activation_readiness` reads the campaign and exact leadset without sending, returning SHA-256 fingerprints and counts. For Leadscanner-linked campaigns `activate_campaign` requires `args.activation_approval` = `APPROVE_INSTANTLY_ACTIVATION <campaign_id> <sequence_fingerprint> <leadset_fingerprint>` plus independently documented contact permission on every lead (`leadscanner_contact_basis` = `consent_verified` or `existing_customer_related_verified`, with nonempty opaque `leadscanner_contact_basis_ref`). A public business email is not proof. Sequence/leadset changes, suppressed or missing canonical registry identities, invalid provider lead status, or missing permission block activation even when the ordinary command confirmation is present. Each Leadscanner lead must still be uniquely `instantly_staged` in the fresh canonical registry immediately before activation.

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
`list_campaigns`, `get_campaign`, `audit_campaign_sequence`, `campaign_sending_status`,
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

## Repository visibility

The allowlisted control plane works whether the repository is public or private.
Repository visibility does not disable lead/email/account reads or confirmed
writes. When the repository is public, command JSON and short-lived Actions
result artifacts can also be visible publicly, so authentication secrets must
never be placed in command payloads.

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


## mijn.host Drafts -> isolated Instantly list (no sending)

Only drafts created by Leadscanner with a valid X-Webactueel-Lead-ID are eligible.
The source mailbox is opened read-only and original drafts are retained. Duplicate
lead IDs and email addresses, invalid drafts, suppressed registry identities,
Instantly blocklisted addresses/domains and emails already in the workspace are
skipped. The import preserves each approved source draft's subject/body as
lead custom variables in an isolated Instantly **lead list**, not a campaign.
No SMTP send, campaign activation, list-to-campaign move or registry edit occurs.

Run the read-only inventory first by adding a new immutable command file:
{"schema_version":"leadscanner-instantly-command/1.0","command_id":"20261009-audit-myhost-001","action":"audit_myhost_drafts","args":{},"requested_by":"chatgpt"}

Only after validating the count-only audit, run the separately authorized
non-sending import using a NEW immutable command file:
{"schema_version":"leadscanner-instantly-command/1.0","command_id":"20261009-import-myhost-001","action":"import_myhost_drafts","args":{"max_imports":25},"confirm":"EXECUTE import_myhost_drafts isolated-list-no-send:25","requested_by":"chatgpt"}

The result artifact contains counts and the destination list ID, **never emails,
names, subjects or bodies**. A list is not a sendable campaign. The existing
approval and legal-basis gates still apply before any subsequent campaign use.

Imports are bounded to 1-250 leads per command. Use max_imports=1 for a real provider smoke test. Every fresh command rechecks source IMAP, live suppression, Instantly workspace duplicates, and destination list before writing. Commands do not continue after a failed/unknown write result; reconciliation requires a new read-only audit.
