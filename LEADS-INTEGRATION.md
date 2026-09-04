# Leads integration contract

`Yolol100/Leadscanner` is de enige GitHub-runtime die de Leads Skill voor discovery, optionele technische website-evidence en gecontroleerd outreachtransport nodig heeft. De repository neemt geen inhoudelijke Leadbeslissingen over.

## Capability 1 — prospect_discovery

Workflow: `.github/workflows/prospect-discovery.yml`.

Input is `ProspectSources`; output is `ProspectCandidates` plus een run receipt. Alleen expliciet goedgekeurde bronnen mogen worden gecrawld.

Discovery behoudt officiële company/domain-controle, dedupe, include/exclude terms, robots.txt, pacing, SSRF/private-network blokkering, timeouts, byte limits, kandidaatlimieten en Google Sheet-integratie. Modi: `validate`, `bootstrap`, `discover`.

Discovery mag nooit:

- e-mailadressen of contactpersonen harvesten;
- Leadscore/Customer Potential bepalen;
- mailcopy maken;
- compliance of toestemming bepalen;
- SMTP/IMAP-credentials ontvangen;
- e-mail verzenden.

## Capability 2 — website_evidence_scan

De bestaande website-scanner blijft optioneel en read-only. Gebruik hem alleen bij een expliciete auditvraag of een specifiek technisch bewijs-gat dat Leads niet eenvoudiger kan bewijzen.

Input per run: één bevestigde publieke officiële bedrijfs-URL via `requests/scan.json` of expliciete `workflow_dispatch`. `sites.txt` blijft uitsluitend handmatige lokale batchinput.

Veiligheidsgrens:

- read-only `GET`/`HEAD`;
- blokkeer localhost, private/link-local/metadata-ranges en riskante actie-URL's;
- respecteer robots/sitemaproute;
- geen formulieren, login, bestelling, betaling, boeking of andere state-changing actie;
- TLS blijft streng;
- `401`, `403` en `429` zijn toegangsblokkades, geen salesbevindingen.

Uitvoer blijft `scan-results/leads-handoff.json`. Crawlee, Playwright, Axe, Lighthouse, LanguageTool, Linkinator en tech-detect leveren alleen evidence/context. Scannerbevindingen veranderen nooit zelfstandig fit, Customer Potential, prioriteit, compliance, send permission of outreachstatus.

## Capability 3 — outreach_delivery

Workflow: `.github/workflows/outreach-smtp.yml`.

De runtime accepteert uitsluitend reeds door Leads aangeleverde/goedgekeurde transportstate. Zij genereert geen nieuwe mailcopy en kiest geen prospect of commerciële verzendgrond.

Actieve volgorde:

```text
campaign policy
-> sender preflight
-> extended Sheet contract preflight
-> compliance preflight
-> direct mijn.host SMTP runtime
-> IMAP reply/bounce/opt-out readback
-> reporting
```

Handmatige workflowruns hebben `validate` als standaard. `live` is een expliciete keuze. Geplande runs kunnen alleen live wanneer `OUTREACH_ENABLED=true` is gezet. CI bevat geen production secrets en voert geen live workflow uit.

De huidige actieve direct-SMTP-route heeft geen Reoon-dependency. `REOON_API_KEY` is daarom geen configuratievereiste voor deze runtime. Legacy `verification_status`/`verification_checked_at` velden blijven compatibel met oudere/provider-routes maar geven nooit toestemming om te verzenden.

### Data-contracten

De runtime bewaakt minimaal:

- `Leadlijst`: `Bedrijf | Website | E-mail | Status`
- `ProspectSources`
- `ProspectCandidates`
- `OutreachQueue`
- `OutreachSequences`
- `ReplyInbox`
- `Suppression`
- `OutreachLog`
- `VariantAnalytics`
- `MailboxHealth`

Reply, bounce en opt-out stoppen vervolgstate fail-closed. Bounce en opt-out schrijven minimale suppression-evidence. Reporting blijft adviserend en overschrijft geen Leadbeslissing of copy.

## Compliance en transportgrenzen

Leads blijft eigenaar van country/jurisdiction, `compliance_basis`, `compliance_status`, contactbron en mailcopy. De runtime behoudt `approved/manual_review/blocked` en de bestaande Nederland/EER fail-closed gate. Een openbaar e-mailadres of technisch transportbewijs is nooit zelfstandig toestemming.

Sender-preflight controleert configuratie, Google Sheet-contract, SPF, DKIM, DMARC en in live mode SMTP/IMAP-authenticatie. Mailboxpool, daily limits, minimum waits, send windows, slow ramp, natural pacing, jitter, sticky sender en threading blijven actief.

## GitHub Actions Secrets

Alleen namen; secretwaarden horen nooit in code, logs of artifacts.

Verplicht voor de actieve runtime wanneer de betreffende capability werkelijk draait:

- `GOOGLE_SERVICE_ACCOUNT_JSON` — prospect discovery + outreach Sheet-toegang
- `OUTREACH_MAIL_PASSWORD` — live SMTP/IMAP voor single-mailboxconfiguratie

Optioneel:

- `OUTREACH_MAILBOXES_JSON` — multi-mailboxconfiguratie inclusief mailboxcredentials via één secret

Niet gebruikt door de actieve direct-SMTP-route:

- `REOON_API_KEY`

## GitHub Actions Variables

Discovery:

- `PROSPECT_DISCOVERY_ENABLED`
- `PROSPECT_DISCOVERY_MAX_TOTAL`
- `PROSPECT_DISCOVERY_TIMEOUT_SECONDS`
- `PROSPECT_DISCOVERY_MAX_BYTES`
- `PROSPECT_DISCOVERY_MIN_INTERVAL_SECONDS`
- `PROSPECT_DISCOVERY_USER_AGENT`
- `OUTREACH_SPREADSHEET_ID`

Outreach:

- `OUTREACH_ENABLED`
- `OUTREACH_MODE`
- `OUTREACH_SPREADSHEET_ID`
- `OUTREACH_TIMEZONE`
- `OUTREACH_SEND_WINDOW_START`
- `OUTREACH_SEND_WINDOW_END`
- `OUTREACH_DAILY_LIMIT`
- `OUTREACH_MAX_SENDS_PER_RUN`
- `OUTREACH_MAX_NEW_LEADS_PER_DAY`
- `OUTREACH_PRIORITIZE_NEW_LEADS`
- `OUTREACH_NATURAL_PACING`
- `OUTREACH_CAMPAIGN_START_DATE`
- `OUTREACH_CAMPAIGN_END_DATE`
- `OUTREACH_SLOW_RAMP_ENABLED`
- `OUTREACH_RAMP_START_DATE`
- `OUTREACH_RAMP_START_LIMIT`
- `OUTREACH_RAMP_INCREMENT_PER_DAY`
- `OUTREACH_RANDOM_JITTER_MINUTES`
- `OUTREACH_REPLY_LOOKBACK_DAYS`
- `OUTREACH_CAPTURE_OTHER_MAIL`
- `OUTREACH_VARIANT_MIN_SAMPLES`
- `OUTREACH_MAILBOX_BOUNCE_ALERT_RATE`
- `OUTREACH_MAILBOX_ID`
- `OUTREACH_MAILBOX_DAILY_LIMIT`
- `OUTREACH_MAILBOX_MIN_WAIT_MINUTES`
- `OUTREACH_SMTP_HOST`
- `OUTREACH_SMTP_PORT`
- `OUTREACH_IMAP_HOST`
- `OUTREACH_IMAP_PORT`
- `OUTREACH_MAIL_USER`
- `OUTREACH_SENDER_NAME`
- `OUTREACH_SENDER_EMAIL`
- `OUTREACH_DKIM_SELECTOR`
- `OUTREACH_REQUIRED_SPF_TOKEN`

De workflow bevat veilige projectdefaults voor de huidige primaire mijn.host-mailbox waar dat al in de bronruntime bestond; repository variables mogen die defaults gecontroleerd overschrijven.

## Runtime ownership

Leads gebruikt voor GitHub-uitvoering uitsluitend `Yolol100/Leadscanner`. Er is geen import, workflow-call of runtime-dispatch naar `Yolol100/Orchestrator` nodig. Orchestrator mag een duplicaat van de oude Lead-code behouden, maar is geen technische dependency.

## Hygiene

Secretwaarden, klantdata en run-specifieke artifacts blijven buiten `main`. GitHub Actions-resultaten blijven run-scoped. Bestaande Node/scanner-CI en de aparte Python Leads-runtime-CI moeten beide groen zijn voor merge.
