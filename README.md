# Leadscanner

> **Status:** centrale GitHub-runtime voor Webactueel Leads.

Deze repository levert acht strikt begrensde capabilities. De machineleesbare waarheid staat in `toolkit-contract.json`; de menselijke uitvoeringsgrenzen staan in `LEADS-INTEGRATION.md`. Deze README blijft bewust kort om dubbele documentatie te voorkomen.

## Capabilities

1. `prospect_discovery` — begrensde company/domain discovery uit goedgekeurde `ProspectSources` naar `ProspectCandidates`.
2. `contact_enrichment` — qualified-only openbare zakelijke contact-evidence van officiële websites naar `ContactCandidates`.
3. `website_evidence_scan` — optionele read-only Crawlee/Playwright/Axe/Lighthouse/Linkinator/tech-detect evidence.
4. `sender_readiness` — SPF/DKIM/DMARC/MX/TLS/auth/PTR/FCrDNS/DNSBL diagnostiek; geen send permission.
5. `inbox_placement` — handmatige seed-only placementtest, standaard `validate`, maximaal vijf seed-inboxen.
6. `mailbox_draft` — expliciete self-addressed mijn.host IMAP-concepttest via `APPEND` + readback; geen SMTP en geen Sheet.
7. `outreach_delivery` — gecontroleerde mijn.host SMTP + IMAP readback voor vooraf goedgekeurde Leads-state.
8. `dashboard` — read-only Google Sheet-controlpanel.

Leads/ChatGPT blijft eigenaar van bedrijfsrealness, Customer Potential, contactkeuze, compliancebasis, copy en interpretatie. Repositorytools leveren alleen discovery-, evidence-, diagnostiek- en transport/readback-capabilities.

## Hoofdroute

```text
ProspectSources
-> prospect_discovery
-> ProspectCandidates
-> Leads kwalificatie
-> contact_enrichment / optioneel website_evidence_scan
-> Leads contact + compliance + copy
-> sender_readiness
-> OutreachQueue / OutreachSequences
-> outreach_delivery
-> SMTP / IMAP readback
-> ReplyInbox / Suppression / OutreachLog / VariantAnalytics / MailboxHealth
-> Dashboard / Leads
```

`mailbox_draft` en `inbox_placement` zijn aparte testcapabilities en liggen niet in de normale prospect->send-route.

## Kernveiligheid

- Scanner: publieke officiële sites, GET/HEAD-only, geen formulieren/login/order/payment/booking.
- Discovery: geen contactharvesting, mailcopy, compliancebesluit of mailboxcredentials.
- Contact enrichment: geen geraadde/geconstrueerde adressen en geen send permission.
- Sender readiness: technische diagnostiek, nooit commerciële toestemming.
- Inbox placement: alleen expliciete seedadressen, nooit `OutreachQueue`.
- Mailbox draft: uitsluitend mijn.host IMAP `APPEND` naar Drafts/Concepten, self-only test, unieke readback-ID, nooit SMTP.
- Outreach delivery: manual default `validate`; live vereist expliciete `live`, geldige compliance, suppressioncheck, sender readiness en mailboxauth.
- CI krijgt geen production secrets en voert geen live e-mail uit.
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
- `OUTREACH_MAIL_PASSWORD`
- optioneel `OUTREACH_MAILBOXES_JSON`
- optioneel `OUTREACH_SEED_INBOXES_JSON` voor de handmatige seedtest

Exacte vars, modes, Sheet-contracten en gatevolgorde: zie `LEADS-INTEGRATION.md`.

## Hygiene

Geen klant-, request-, secret- of run-specifieke state op `main`. Actions-evidence blijft run-scoped; concrete runtimeverzoeken horen alleen in expliciete tijdelijke requeststate. `Yolol100/Orchestrator` is geen technische dependency van Leadscanner.
