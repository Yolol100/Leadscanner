# Draft sync recovery contract

This contract captures the fail-closed recovery path for a legacy mijn.host IMAP draft that blocks the normal selected-draft synchronization.

## Scope

Use the recovery path only for one explicitly selected lead whose existing sender draft is legacy or does not satisfy the current Webactueel draft identity contract. It is not a bulk-delete mechanism and never grants send permission.

## Required invariants

Before mutation:

- resolve the current OutreachQueue row for the exact `lead_id`;
- reload suppression state;
- require a draft-eligible compliance state and valid mailbox configuration;
- require exactly one existing sender draft for the recipient;
- refuse the legacy route if that draft already has a valid safe Webactueel draft ID;
- accept only legacy transport `""` or `imap-draft-only`;
- require the existing subject to match OutreachQueue exactly;
- keep SMTP completely outside the path.

## Safe mutation order

1. Preflight all invariants without deleting or appending anything.
2. Append the new draft with a safe Webactueel draft ID.
3. Read the new draft back and compare it with the current queue content.
4. Delete the single proven legacy draft only after the new readback succeeds.
5. Reselect Drafts and perform a final provider scan.
6. Require exactly one final sender draft with the safe ID and matching content.

If append or new-draft readback fails, the old draft must remain. If any invariant cannot be proven, stop fail-closed.

## Batch completion after recovery

A successful one-lead migration is only a repair step. The original selected lead set must then be run again through `SYNC_SELECTED_MYHOST_DRAFTS`.

For a requested target `N`, completion requires:

`target=N | final_readback=N | SMTP_SEND=not_invoked`

`create`, `replace`, and `unchanged` are diagnostic mutation counts only. A green workflow or a green one-lead migration without the full selected-batch provider readback is not batch completion evidence.

## Runtime evidence

- `scripts/outreach_legacy_draft_migrate.py`
- `.github/workflows/migrate-legacy-myhost-draft-command.yml`
- `.github/workflows/sync-selected-myhost-drafts-command.yml`
- `MYHOST_LEGACY_DRAFT_MIGRATION=green ... final_readback=1 ... smtp_send=not_invoked`
- `MYHOST_SELECTED_DRAFT_SYNC=green ... final_readback=N ... smtp_send=not_invoked`

The repository provides execution and evidence. Live Project Leads remains the project source of truth.