# Instantly command inbox

This directory is the GitHub-only control plane used by ChatGPT web.

ChatGPT creates a **new immutable JSON file** in `instantly-commands/inbox/`.
The existing `.github/workflows/leads-cold.yml` workflow validates the command,
uses the repository's Instantly secret, executes one allowlisted action, and
uploads a JSON result artifact. Existing command files must never be edited or
reused.

## Read-only archive audit

Use `audit_retired_archive` to verify the non-sending archived contact after the historical campaign was deleted. This audit does not re-open the deleted campaign or expose contact data; original-vs-copy equality can no longer be independently checked.

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

## Paused campaign safety and read-only source eligibility

The existing `Websiteadvies NL` and `Websiteadvies EN` campaigns may safely remain **Paused** (provider status 2); a provider PATCH does not turn Paused back into Draft. For reviewed-mail staging only, Leadscanner accepts **Draft 0 or Paused 2**, and refuses Active or any other state, any assigned sender, an unexpected campaign ID/name, changed steps, risky contacts, or disabled stop-on-reply. A paused campaign cannot send without separate, explicitly approved activation and a newly assigned verified sender. Fact-only `instantly_sequence` approval still requires Draft and an exact sequence fingerprint.

Check **all source contacts without writing any leads** by adding immutable read commands for NL and EN with action `audit_language_route_readiness` and args `{ "language": "nl" }` or `{ "language": "en" }`. Each command runs the same provider campaign/list/suppression/registry eligibility logic with `dry_run=true`; returns counts only; and performs no lead moves, mail sends, or campaign changes. The report distinguishes missing contact-basis proof, missing full sender identity `Andrew Baeten`, missing verified first-party website observation/action/source and remaining dedupe/suppression holds. A public company email, a reviewed first message or a simulated Preview is **not** contact-permission evidence.

A successful dry-run is **not** Instantly's live preview. With no eligible lead in either campaign, the real preview with filled variables is still pending; perform that in the Instantly Editor with an individually reviewed, eligible lead once available. Do not attach a sender, activate a campaign, or stage historical contacts just to make the preview work. No automatic send is authorized by this workflow.

## Evidence-only three-email campaign approval

An explicitly selected `instantly_sequence` preview does not generate a separate email. To stage an approved lead, first audit a **Draft** campaign using `audit_campaign_sequence`. The audit must show exactly one sequence and **three email steps**, no unresolved template fields, no `leadscanner_subject` or `leadscanner_body`, and both `leadscanner_observation` and `leadscanner_value_action` in the template. Review the actual subjects, bodies, variants and legal/contact basis in Instantly independently; the copy-free audit does not certify those.

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
`campaign_analytics`, `audit_language_route_readiness`, `list_leads`, `get_lead`, `list_emails`,
`get_email`, `count_unread_emails`, `list_accounts`, `get_account`,
`warmup_analytics`, `daily_account_analytics`, `list_blocklist`,
`get_blocklist_entry`, `get_background_job`.

Explicit writes:
`create_campaign_draft`, `update_campaign`, `pause_campaign`,
`activate_campaign`, `delete_campaign`, `update_lead`, `delete_lead`,
`update_interest`, `reply_email`, `forward_email`, `send_test_email`,
`mark_thread_read`, `update_account`, `pause_account`, `resume_account`,
`rename_source_lead_list`, `rename_retired_archive`,
`enable_warmup`, `disable_warmup`, `block_email`, `block_domain`,
`delete_blocklist_entry`, `stage_approved_lead`.

There is deliberately **no generic HTTP method/path action**.

## Rebrand the existing isolated lead list without touching recipients

The allowlisted `rename_source_lead_list` action is restricted to the exact already-imported source list ID `24deb187-59e0-43b5-86b8-fe37a7b21e2a`. It checks the old list name and expected lead count before the name-only PATCH, reads back the same ID, and verifies every lead ID is unchanged. It cannot stage, delete, send, or activate.

Use a **new immutable command file** with `args.list_id`, `args.expected_name`, and `args.expected_count` and the exact `confirm` string `EXECUTE rename_source_lead_list <list_id>`. Never repeat an unknown PATCH outcome without a new read-only reconciliation.

## Rename the one-contact historical archive

A separate exact action `rename_retired_archive` uses the same no-send control plane. It only changes the name of the unique preserved one-contact non-sending archive, after checking its current old label and archive identity. It verifies the same archived contact ID before and after the PATCH. There is no archive recreation, lead move or sending. The exact immutable confirmation is `EXECUTE rename_retired_archive` with empty `args`.

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

Only drafts created by Leadscanner with a valid `X-Leadscanner-Lead-ID` or historical legacy lead-ID tag are eligible. New drafts use the neutral header; old header values remain readable to preserve exact lead identity.
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

## Language-separated imported-draft routing

The allowlisted `route_language_drafts` action inspects every lead's source
subject/body, handles only confidently Dutch or English business addresses,
respects the live registry and blocklist, and **copies** approved rows to the
matching Draft campaign while preserving the original list. It requires an
empty sender list, a three-email sequence with exact reviewed subject/body
merge fields, strict command confirmation and provider job/readback evidence.
Ambiguous, suppressed, already-routed and consumer-mail rows stay on hold.

Example command args: `{"language":"nl","campaign_id":"<uuid>","max_leads":25}`.
Confirmation: `EXECUTE route_language_drafts nl|<uuid>|25`.
It never launches campaigns or sends, and it never accepts lead emails in a
public GitHub command. Avoid re-running an uncertain background write: audit
first, then issue a new exact command.

## Automatic language destination for newly approved Leadscanner leads

The normal review path is now `preview_copy_mode=reviewed_mail`. The
`instantly_stage` dispatch uses `instantly_campaign_id=auto_language` by
default and resolves an **exact approved reviewed subject/body** to one of the
existing NL or EN Draft campaigns after fresh registry revalidation. An
ambiguous or mismatched language is held rather than guessed from domain,
company location or names. Target campaigns must be Draft with **zero senders**,
matching exact names, a three-email sequence, approved first-step merge fields,
and no unsupported fields. No send or activation is performed.

The old fact-only `instantly_sequence` mode is explicitly opt-in and
requires a distinct exact destination ID and sequence fingerprint approval. It
cannot be silently staged through the automatic reviewed-mail route.

**Before any launch**, record genuine per-lead evidence for contact permission,
confirm suppression rules and reconnect/test the sender accounts. A successful
copy, staging action or review is never evidence of consent.
