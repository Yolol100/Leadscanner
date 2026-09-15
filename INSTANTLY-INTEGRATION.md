# Instantly integration

This repository contains a controlled Instantly API v2 bridge for Project Leads.

## Ownership

- `webactueel-workflow` remains the controller.
- Live Project Leads remains canonical policy.
- `Yolol100/Leadscanner` is execution/evidence only.
- Normal outreach remains `send_permission=none`.

## What the bridge can do

The bridge supports four commands:

1. `CONNECTION_TEST` — read-only API connectivity probe.
2. `CAMPAIGN_STATUS` — read-only campaign status check.
3. `SYNC_SELECTED_TO_LIST` — dry-run or explicit apply of already validated OutreachQueue leads to an Instantly lead list.
4. `SYNC_SELECTED_TO_CAMPAIGN` — dry-run or explicit apply of already validated OutreachQueue leads to an Instantly campaign only when the campaign is `draft` or `paused`.

The bridge does **not** activate campaigns, resume campaigns, send emails, edit sequences, or bypass the Leads validation/suppression/copy gates.

## Secret setup

Create a GitHub Actions repository secret named:

`INSTANTLY_API_KEY`

Never commit the key to the repository or paste it into an issue. Rotate any key that has previously been shared in chat or another public surface.

The existing `GOOGLE_SERVICE_ACCOUNT_JSON` secret and `OUTREACH_SPREADSHEET_ID` variable are reused to load the private OutreachQueue and Suppression sheets.

## ChatGPT -> GitHub command route

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

## Safety gates

Before an Instantly write, every selected row must already pass the existing Leadscanner `OutreachQueue` validation gate, including suppression and V17.2 copy validation.

For campaign writes the bridge reads the campaign state first and refuses to add leads unless the campaign is `draft` or `paused`. It never changes campaign status.

After an apply, the bridge queries Instantly again and requires readback for every selected email. If exact readback is missing, the command fails closed.

Public GitHub feedback contains only status, counts, and campaign state. It does not echo prospect PII or email content.
