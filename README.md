# Leadscanner — bedrijfsresearch (geen e-mail)

De actieve repository zoekt en verifieert Nederlandse lokale bedrijven en officiële websitegegevens. E-mailconcepten, Mijn.Host, IMAP, SMTP, mailboxbruggen en verzendacties zijn buiten gebruik gesteld op 10 november 2026.

## Beschikbare acties

- `LEADS_CHAT_V1:CHECK`: volledige historische uitsluitingscontrole, inclusief HMAC, LeadHistory en legacy DraftQueue (alleen lezen).
- `LEADS_CHAT_V2:HINTS_10/30/50/100:r-<32hex>`: zoekhints naar privé Candidates.
- `LEADS_CHAT_V2:VERIFIED_100:r-<32hex>`: officiële bedrijfsverificatie naar privé Approved.
- `LEADS_CHAT_V2:EVIDENCE:r-<32hex>` en `REVIEW_EVIDENCE_1..5`: broncontrole van bestaande bedrijfswebsites.

Bestaande opt-outs, bounces, dedupe en historische conceptgegevens blijven behouden als read-only uitsluiting of archief. Bij ontbrekende suppressiegegevens stopt het onderzoek. Geen prospectinformatie in publieke commits of logs.

## Herstel

Alle oorspronkelijke code en documenten: [archiefbranch](../../tree/archive/pre-myhost-mail-cleanup-2026-11-10). Herstel niet automatisch en activeer geen mailfuncties zonder nieuwe expliciete opdracht.
