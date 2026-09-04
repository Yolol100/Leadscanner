# Leadscanner

> **Portfoliostatus:** actieve centrale GitHub-runtime voor Webactueel Leads

`Yolol100/Leadscanner` combineert drie strikt gescheiden capabilities:

1. **`prospect_discovery`** — begrensde company/domain discovery vanuit expliciet goedgekeurde `ProspectSources` naar `ProspectCandidates`.
2. **`website_evidence_scan`** — de bestaande optionele read-only Crawlee/Playwright/Axe/Lighthouse/Linkinator/tech-detect scanner.
3. **`outreach_delivery`** — gecontroleerde transport-runtime voor reeds door Leads goedgekeurde state: preflight, compliancegate, sequences, SMTP, IMAP reply/bounce/opt-out, suppression en reporting.

De repository genereert geen Leadscore, kiest geen contactpersoon, bepaalt geen commerciële verzendgrond en schrijft geen nieuwe mailcopy. Die beslissingen blijven bij de Leads Skill/projectbronnen.

## Hoofdroute

```text
ProspectSources
  -> prospect_discovery
  -> ProspectCandidates
  -> Leads kwalificatie/contact/compliance/copy
  -> optioneel website_evidence_scan
  -> OutreachQueue / OutreachSequences
  -> outreach_delivery
  -> SMTP / IMAP readback
  -> ReplyInbox / Suppression / OutreachLog / VariantAnalytics / MailboxHealth
  -> Leads
```

De actieve outreach-route is de huidige directe mijn.host SMTP/IMAP-runtime. Zij heeft geen actieve Reoon-dependency. Legacy verificatievelden blijven alleen backward-compatible transportvelden; ze geven nooit toestemming om te mailen.

## Prospect discovery

Workflow: `.github/workflows/prospect-discovery.yml`

Scripts:

- `scripts/prospect_discovery.py`
- `scripts/prospect_discovery_runtime.py`

Modi: `validate`, `bootstrap`, `discover`.

Discovery:

- leest alleen expliciet goedgekeurde `ProspectSources`;
- schrijft kandidaten naar `ProspectCandidates`;
- dedupliceert tegen bestaande kandidaten en `Leadlijst`;
- respecteert robots.txt, pacing, timeouts, byte- en kandidaatlimieten;
- blokkeert private/loopback/link-local targets;
- bevestigt publieke bedrijfs-/domeinkandidaten;
- verzamelt geen e-mailadressen;
- bepaalt geen Customer Potential/Leadscore;
- maakt geen mailcopy;
- krijgt geen SMTP/IMAP-credentials;
- kan niets versturen.

Geplande discovery draait alleen wanneer `PROSPECT_DISCOVERY_ENABLED=true` is gezet.

## Website evidence scan

Workflow: `.github/workflows/scan.yml`

Deze bestaande capability blijft **optioneel en read-only**. Gebruik hem alleen wanneer:

1. de gebruiker expliciet een website-audit/scan/rescan vraagt; of
2. Leads na de lichte officiële-sitecheck een specifiek technisch bewijs-gat heeft dat niet eenvoudiger bewezen kan worden.

De scanner behoudt Crawlee, Playwright, Axe, Lighthouse, Linkinator, robots/sitemap en tech-detect en levert `scan-results/leads-handoff.json` terug. Scannerbevindingen veranderen nooit zelfstandig leadfit, prioriteit, compliance, send permission of outreachstatus.

Veiligheidsgrens: maximaal begrensde kernpagina's, GET/HEAD-only, geen formulieren/bestellingen/betalingen/boekingen, publieke officiële website vereist en bestaande netwerk-/TLS-/robotsgrenzen blijven actief.

## Outreach delivery

Workflow: `.github/workflows/outreach-smtp.yml`

Actieve runtime:

- `scripts/outreach_campaign_policy.py`
- `scripts/outreach_preflight.py`
- `scripts/outreach_extended_preflight.py`
- `scripts/outreach_compliance_preflight.py`
- `scripts/outreach_direct_smtp_runtime.py`
- `scripts/outreach_campaign_runtime.py`
- `scripts/outreach_sender.py`
- `scripts/outreach_mailboxes.py`
- `scripts/outreach_sequences.py`
- `scripts/outreach_replyhub.py`
- `scripts/outreach_optout.py`
- `scripts/outreach_reporting.py`

Handmatige workflowruns staan standaard op `validate`. `live` is alleen een expliciete keuze. Geplande live-runs vereisen daarnaast `OUTREACH_ENABLED=true`.

De runtime behoudt:

- Google Sheet-contracten voor `OutreachQueue`, `OutreachSequences`, `ReplyInbox`, `Suppression`, `OutreachLog`, `VariantAnalytics` en `MailboxHealth`;
- sender-preflight inclusief SPF, DKIM, DMARC, SMTP/IMAP en mailboxconfiguratie;
- single- en multi-mailboxcapaciteit, daily limits, minimum waits, send windows, slow ramp, pacing en jitter;
- deterministic Message-ID, `In-Reply-To` en `References`;
- fail-closed compliance voor land/jurisdictie, `compliance_basis` en `compliance_status`;
- onmiddellijke sequence-stop bij reply, bounce of opt-out;
- suppression en evidence-bound reporting.

Reporting mag geen Leadbeslissing of mailcopy zelfstandig overschrijven.

## Python dependencies

De Lead-runtimedependencies staan apart in `requirements-outreach.txt`. De bestaande Node/npm/Playwright/Crawlee-stack blijft ongewijzigd voor website scanning.

## Tests

- bestaande scanner/Node-tests blijven via de bestaande workflows draaien;
- `.github/workflows/leads-runtime-ci.yml` compileert de Python-runtime en draait de gemigreerde Lead-tests zonder production secrets;
- de CI-job bevat geen mailbox- of Google-credentials en kan daardoor geen live e-mail versturen;
- workflowtests bewaken secret isolation tussen discovery, preflights, reporting en SMTP.

## GitHub Actions configuratie

Secretwaarden horen uitsluitend in GitHub Actions Secrets, nooit in repositorybestanden of artifacts.

Benodigde secretnamen voor de actieve runtime:

- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `OUTREACH_MAIL_PASSWORD`
- optioneel `OUTREACH_MAILBOXES_JSON`

De actieve directe SMTP-route gebruikt geen `REOON_API_KEY`.

Belangrijke variables zijn onder andere `OUTREACH_SPREADSHEET_ID`, `OUTREACH_ENABLED`, mailbox/sender SMTP/IMAP-instellingen, pacing/campaignlimieten en de `PROSPECT_DISCOVERY_*` limieten. Zie `LEADS-INTEGRATION.md` voor de volledige lijst.

## Repository hygiene

Klant-, site-, request- en run-specifieke input/evidence blijft tijdelijk of run-scoped. `sites.txt` blijft lokale tijdelijke input en staat in `.gitignore`; `requests/scan.json` hoort alleen op een tijdelijke runtimebranch; Actions-resultaten blijven artifacts en worden niet naar `main` gecommit.

Orchestrator is geen technische dependency van deze repository. De migratie laat `Yolol100/Orchestrator` bewust intact; Leadscanner bevat zijn eigen Lead-specifieke runtimeclosure.
