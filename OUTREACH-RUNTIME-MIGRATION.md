# Outreach runtime migration

Target architecture:

`webactueel-workflow -> leads -> Leadscanner -> outreach-runtime`

## Leadscanner remains owner of

- prospect discovery;
- source sanitation;
- signal discovery;
- Customer Potential / qualification;
- contact enrichment;
- website evidence scan;
- prospect intelligence;
- zero-touch prepare;
- deterministic LeadPromo queue preparation without send permission.

## outreach-runtime becomes owner of

- live/validate SMTP transport;
- sender/mailbox readiness;
- mailbox draft diagnostics;
- IMAP reply and opt-out readback;
- suppression before send;
- transport logging and deterministic send evidence.

## Safe cutover

The existing Leadscanner transport files are a temporary rollback path. Do not remove or disable them until `Yolol100/outreach-runtime` proves all of these on its own repository:

1. CI green without mailbox/Sheet secrets.
2. Runtime repository variables and secrets configured.
3. Manual validate proves the real Google Sheet contract.
4. Sender readiness proves SMTP/IMAP transport and authentication.
5. One bounded manual live run produces SMTP acceptance and matching IMAP/state readback.
6. Reply/opt-out suppression behavior is verified.

After those gates are green, remove Leadscanner transport workflows/scripts/tests that are not required by zero-touch prepare. Preserve the small shared queue/copy helpers needed by prepare or refactor them into prepare-only modules before deletion.

`outreach-runtime` is never allowed to perform prospect discovery, qualification or grant compliance approval. `webactueel-workflow` remains the sole controller and `leads` remains the domain owner.
