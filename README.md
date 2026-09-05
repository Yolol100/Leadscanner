# Leadscanner

> **Status:** centrale GitHub-runtime voor Webactueel Leads.

Deze repository levert twaalf strikt begrensde capabilities. De machineleesbare waarheid staat in `toolkit-contract.json`; de menselijke uitvoeringsgrenzen staan in `LEADS-INTEGRATION.md`. Deze README blijft bewust kort om dubbele documentatie te voorkomen.

## Capabilities

1. `prospect_discovery` — begrensde company/domain discovery uit goedgekeurde `ProspectSources` naar `ProspectCandidates`.
2. `contact_enrichment` — qualified-only openbare zakelijke contact-evidence van officiële websites naar `ContactCandidates`.
3. `website_evidence_scan` — optionele read-only Crawlee/Playwright/Axe/Lighthouse/Linkinator/tech-detect evidence.
4. `sender_readiness` — SPF/DKIM/DMARC/MX/TLS/auth plus exact-IP of bewezen mijn.host shared-relaydiagnostiek; geen send permission.
5. `inbox_placement` — handmatige seed-only placementtest, standaard `validate`, maximaal vijf seed-inboxen.
6. `mailbox_draft` — expliciete self-addressed mijn.host IMAP-concepttest via `APPEND` + readback; geen SMTP en geen Sheet.
7. `outreach_delivery` — gecontroleerde mijn.host SMTP + IMAP readback voor afzonderlijk goedgekeurde Leads-state.
8. `dashboard` — read-only Google Sheet-controlpanel.
9. `prospect_intelligence` — afgeleide entity/freshness/source-performance/evidence/lookalike-laag; adviserend.
10. `prospect_signal_discovery` — begrensde official-site hiring en WordPress/WooCommerce signalen.
11. `prospect_qualification` — deterministische bounded Customer Potential-kwalificatie met audit trail in `ProspectQualifications`.
12. `zero_touch_prepare` — automatische weekday-keten van discovery tot `status=prepared` LeadPromo-copy, zonder mailboxcredential of send permission.

Leads-policy blijft eigenaar van de regels voor realness, Customer Potential, copy, compliance en verzendgates. Repositorytools mogen die regels begrensd uitvoeren voor kwalificatie en prepare, maar mogen nooit een ontbrekende compliancebasis verzinnen of live verzendpermission creëren.

## Hoofdroute

```text
ProspectSources
-> prospect_discovery
-> ProspectCandidates
-> prospect_signal_discovery
-> prospect_qualification
-> ProspectQualifications
-> contact_enrichment
-> ContactCandidates
-> prospect_intelligence
-> zero_touch_prepare / outreach_prepare
-> OutreachQueue status=prepared + compliance_status=manual_review
-> afzonderlijke compliance-goedkeuring
-> sender_readiness
-> outreach_delivery validate/live
-> SMTP / IMAP readback
-> ReplyInbox / Suppression / OutreachLog / VariantAnalytics / MailboxHealth
-> Dashboard / Leads
```

`mailbox_draft`, `inbox_placement` en `website_evidence_scan` zijn aparte test/evidencecapabilities en zijn niet nodig voor iedere normale prepare-run.

## Kernveiligheid

- Scanner: publieke officiële sites, GET/HEAD-only, geen formulieren/login/order/payment/booking.
- Discovery: geen contactharvesting, mailcopy, compliancebesluit of mailboxcredentials.
- Qualification: alleen bounded official-site evidence; één primaire opportunityseverity; A vereist brongebonden fact + idea; geen compliance/send permission.
- Contact enrichment: geen geraadde/geconstrueerde adressen en geen send permission.
- Zero-touch prepare: alleen A + `ContactCandidates.ready`; queue blijft `prepared/manual_review`; geen SMTP/IMAP-secret.
- Sender readiness: technische diagnostiek; mijn.host shared relay kan alleen als `provider_managed` worden vastgelegd wanneer SPF-delegatie bewezen is. Dat is geen per-IP reputatie- of placementclaim.
- Inbox placement: alleen expliciete seedadressen, nooit `OutreachQueue`.
- Mailbox draft: uitsluitend mijn.host IMAP `APPEND` naar Drafts/Concepten, self-only test, unieke readback-ID, nooit SMTP.
- Outreach delivery: manual default `validate`; live vereist expliciete `live`, geldige compliance, suppressioncheck, groene sender readiness en mailboxauth.
- Pushes/CI krijgen geen production mailboxsecrets en voeren geen live e-mail uit.
- De actieve direct-SMTP-route heeft geen Reoon-dependency.

## Tests

Python Leads-runtime:

```bash
python3 -m pip install -r requirements-outreach.txt
python3 -m compileall -q scripts
PYTHONPATH=scripts python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Scanner/runtime checks blijven in de bestaande Node- en Actions-workflows. `Toolkit Contract`, `Leads Runtime CI` en `Scanner Smoke Test` moeten groen zijn voor releaseclaims.

## Configuratie

Secretwaarden horen alleen in GitHub Actions Secrets. De actieve routes gebruiken waar van toepassing:

- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `OUTREACH_MAIL_PASSWORD` alleen voor mailbox/live transport
- optioneel `OUTREACH_MAILBOXES_JSON` alleen voor mailbox/live transport
- optioneel `OUTREACH_SEED_INBOXES_JSON` alleen voor de handmatige seedtest

`zero_touch_prepare` gebruikt alleen de Sheetcredential en niet-geheime vars. Exacte vars, modes, Sheet-contracten en gatevolgorde: zie `LEADS-INTEGRATION.md`.

## Hygiene

Geen klant-, secret- of runoutput op `main`. Actions-evidence blijft run-scoped; een tijdelijke `ops/leads-autopilot-request.txt` mag alleen als expliciete eenmalige connector-trigger worden gebruikt en wordt daarna verwijderd. `Yolol100/Orchestrator` is geen technische dependency van Leadscanner.
