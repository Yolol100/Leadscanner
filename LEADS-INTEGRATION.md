# Leads integration contract

`Yolol100/Leadscanner` is de enige GitHub-runtime voor de repository-capabilities van Leads. Dit bestand is de **menselijke canonieke integratiebron**; `toolkit-contract.json` is de machineleesbare canonieke bron. README en AGENTS verwijzen hiernaar en herhalen de volledige contractdetails niet.

Leads/ChatGPT blijft eigenaar van bedrijfsrealness, Customer Potential, contactkeuze/promotie, compliancebasis/status, mailcopy en interpretatie van resultaten. Repositorycapabilities leveren alleen discovery, evidence, technische diagnostiek, testtransport en readback.

## Capability 1 — prospect_discovery

Workflow: `.github/workflows/prospect-discovery.yml`.

- Leest alleen expliciet goedgekeurde `ProspectSources`.
- Schrijft company/domain-kandidaten naar `ProspectCandidates`.
- Behoudt robots.txt, pacing, timeouts, byte/kandidaatlimieten en private-network/SSRF-blokkering.
- Verzamelt geen contactadressen, bepaalt geen Customer Potential/compliance, maakt geen copy en ontvangt geen mailboxcredentials.
- Modi: `validate`, `bootstrap`, `discover`.
- Handmatige default: `validate`.
- Geplande weekday-runs blijven actief voor contractvalidatie en draaien standaard `validate`; alleen `PROSPECT_DISCOVERY_ENABLED=true` promoveert een geplande run naar `discover`.

## Capability 2 — contact_enrichment

Workflow: `.github/workflows/contact-enrichment.yml`.

- Draait uitsluitend op `ProspectCandidates.status=qualified`.
- Inspecteert begrensd de officiële homepage plus maximaal drie contact/about/team-achtige pagina's.
- Raad, construeer of extrapoleer nooit een e-mailadres.
- Blokkeer no-reply/systeem/free-mail; controleer domeinalignment en MX.
- Schrijft alleen `ContactCandidates`; `ready` is contactbewijs, nooit commerciële toestemming of send permission.
- Standaard max 10 kandidaten per handmatige run, hard max 25.

## Capability 3 — website_evidence_scan

Workflow: `.github/workflows/scan.yml`.

Optioneel read-only bewijs voor een expliciete website-audit of een specifiek technisch bewijs-gat.

- Publieke officiële website vereist.
- GET/HEAD-only; geen login, formulieren, bestelling, betaling, boeking of andere state-changing actie.
- Behoud private/link-local/metadata-blokkering, TLS en robots/sitemapgrenzen.
- `401`, `403` en `429` zijn toegangsblokkades, geen salesbevindingen.
- Uitvoer: `scan-results/leads-handoff.json` plus run-scoped evidence.
- Scannerbevindingen veranderen nooit zelfstandig fit, prioriteit, compliance, copy of send permission.

## Capability 4 — sender_readiness

Workflow: `.github/workflows/sender-readiness.yml`.

Technische diagnostiek per ingeschakelde mailbox:

- SPF, DKIM, DMARC en MX;
- SMTP-TLS/STARTTLS en IMAP-TLS;
- mailboxauth wanneer secret aanwezig is;
- optioneel PTR/FCrDNS via `OUTREACH_OUTBOUND_IP`;
- optioneel configureerbare DNSBL-zones via `OUTREACH_DNSBL_ZONES`.

`green` betekent alleen dat de beschikbare vereiste technische bewijslagen groen zijn. Ontbrekende optionele externe bewijzen blijven `review/not_configured`; harde DNS/auth/TLS/PTR/FCrDNS/DNSBL-fouten worden `blocked`. Readiness is geen commerciële toestemming en geen globale placementgarantie.

## Capability 5 — inbox_placement

Workflow: `.github/workflows/inbox-placement.yml`.

Dit is geen warmup-netwerk maar een handmatige gecontroleerde seedtest.

- Alleen `workflow_dispatch`.
- Default `validate`; dan wordt niets verzonden.
- `test` vereist expliciet `confirm_test_send=true` en `OUTREACH_PLACEMENT_TEST_ENABLED=true`.
- Maximaal vijf vooraf geconfigureerde seed-inboxen uit `OUTREACH_SEED_INBOXES_JSON`.
- Nooit `OutreachQueue`-ontvangers.
- Readback: `inbox | spam | missing | error` naar `InboxPlacement`.
- Eén seedtest is nooit bewijs voor globale placement.

## Capability 6 — mailbox_draft

Workflow: `.github/workflows/myhost-draft-test.yml`.

Deze capability bewijst dat een concept **in de geconfigureerde mijn.host-mailbox zelf** kan worden opgeslagen zonder te verzenden.

- Alleen expliciete handmatige bevestiging of een éénmalige request-trigger.
- Self-addressed testboundary; geen prospectrecipient.
- Alleen IMAP `APPEND` met `\\Draft`; er wordt geen SMTP-verbinding geopend.
- Detecteer eerst de IMAP special-use `\\Drafts`-map; gebruik alleen een ondubbelzinnige Drafts/Concepten-fallback of expliciet bestaande `OUTREACH_DRAFT_FOLDER`.
- Elk concept krijgt een unieke `X-Webactueel-Draft-Test-ID`.
- Na APPEND moet dezelfde map read-only worden geselecteerd en moet die ID worden teruggevonden; zonder readback geen `MYHOST_DRAFT=green`.
- Geen Google Sheet-toegang, geen Leadstate-mutatie, geen schedule en `send_permission=none`.
- Een Outlook-concept is geen geldig substituut voor deze mijn.host-readback.

## Capability 7 — outreach_delivery

Workflow: `.github/workflows/outreach-smtp.yml`.

De runtime accepteert alleen reeds door Leads beoordeelde transportstate. Zij genereert geen nieuwe mailcopy en kiest geen prospect of verzendgrond.

Actieve live-volgorde:

```text
campaign policy
-> sender preflight
-> extended Sheet contract preflight
-> live sender readiness gate
-> LeadPromo copy preflight
-> compliance preflight
-> direct mijn.host SMTP runtime
-> IMAP reply/bounce/opt-out readback
-> reporting
```

- Handmatige default: `validate`.
- `live` is expliciet; scheduled live vereist daarnaast `OUTREACH_ENABLED=true`.
- Push/CI mag nooit naar live promoveren en krijgt geen production mailboxsecret.
- Suppression wordt vóór send gecontroleerd; reply, bounce en opt-out stoppen vervolgstate fail-closed.
- Mailboxpool, limits, minimum waits, send windows, slow ramp, pacing, jitter, sticky sender en threading blijven actief.
- De actieve direct-SMTP-route vereist geen Reoon. Legacy `verification_status`/`verification_checked_at` blijven alleen providercompatibele velden.

## Capability 8 — dashboard

De Google Sheet `Webactueel Leadlijst` bevat één read-only `Dashboard`.

- Aggregatie uit ProspectCandidates, ContactCandidates, OutreachQueue, Suppression, MailboxHealth, SenderReadiness en InboxPlacement.
- Lege readiness-, placement- of mailbox-healthbron = `not_tested`, nooit automatisch `green`.
- Placement `missing` en `error` = unresolved/review.
- Dashboardformules mogen geen Lead- of transportstate muteren.

## Data-contracten

Minimaal bewaakt:

- `Leadlijst`: `Bedrijf | Website | E-mail | Status`
- `ProspectSources`
- `ProspectCandidates`
- `ContactCandidates`
- `OutreachQueue`
- `OutreachSequences`
- `ReplyInbox`
- `Suppression`
- `OutreachLog`
- `VariantAnalytics`
- `MailboxHealth`
- `SenderReadiness`
- `InboxPlacement`
- `Dashboard`

`mailbox_draft` schrijft bewust niet naar de Sheet; de bewijslaag is de IMAP same-folder readback in de workflowrun.

## Compliance- en transportgrenzen

- Leads bezit `country/jurisdiction`, `compliance_basis`, `compliance_status`, contactbron en mailcopy.
- Nederland/EER blijft fail-closed: een openbaar zakelijk adres, `ContactCandidates.ready`, sender-readiness, seed-placement of draft-readback is nooit zelfstandig toestemming voor commerciële outreach.
- Compliance-, copy-, suppression- en sendergates blijven vóór live SMTP.
- Creatorvideo's/comments zijn adviserend bewijs. Actuele wet/providerregels en echte Webactueel-resultaten hebben voorrang.

## GitHub Actions Secrets

Secretwaarden horen nooit in code, logs of artifacts.

- `GOOGLE_SERVICE_ACCOUNT_JSON` — nodig voor de capabilities die de operationele Sheet lezen/schrijven.
- `OUTREACH_MAIL_PASSWORD` — mailboxauth voor live SMTP/IMAP, mailbox-connectivity, `mailbox_draft` en de single-mailbox seedtest waar van toepassing.
- `OUTREACH_MAILBOXES_JSON` — optioneel voor multi-mailboxconfiguratie.
- `OUTREACH_SEED_INBOXES_JSON` — alleen voor de expliciete seed-placementtest.
- `REOON_API_KEY` — niet gebruikt door de actieve direct-SMTP-route.

Belangrijk: `mailbox_draft` krijgt **geen** `GOOGLE_SERVICE_ACCOUNT_JSON`; discovery/contact-only routes krijgen **geen** mailboxsecrets.

## Belangrijkste variabelen

De workflows bevatten veilige projectdefaults waar die al bestonden. Relevante variabelen zijn onder meer:

- discovery: `PROSPECT_DISCOVERY_*`, `OUTREACH_SPREADSHEET_ID`;
- contact enrichment: `CONTACT_ENRICHMENT_*`, `OUTREACH_SPREADSHEET_ID`;
- sender readiness: `SENDER_READINESS_ENABLED`, `OUTREACH_OUTBOUND_IP`, `OUTREACH_DNSBL_ZONES`;
- placement: `OUTREACH_PLACEMENT_POLL_SECONDS`, `OUTREACH_PLACEMENT_MAX_WAIT_SECONDS`;
- mailbox draft: `OUTREACH_DRAFT_FOLDER`, plus de gewone IMAP/mailboxconfiguratie;
- outreach: `OUTREACH_ENABLED`, `OUTREACH_MODE`, timezone/sendwindow, daily/run/new-lead limits, pacing/ramp/jitter, mailbox/sender SMTP/IMAP- en DKIM/SPF-instellingen.

Gebruik de workflows zelf als waarheid voor exacte defaults en bounds; kopieer die lijsten niet naar extra docs.

## Runtime ownership en hygiene

- Leads gebruikt voor GitHub-uitvoering uitsluitend `Yolol100/Leadscanner`; `Yolol100/Orchestrator` is geen technische dependency.
- Klant-, request-, secret- en run-specifieke state blijft buiten `main` of run-scoped.
- GitHub Actions-evidence blijft in artifacts/Sheets; commit geen runtime-output naar `main`.
- Verwijder capabilities alleen wanneer machinecontract, callsites en tests aantonen dat ze werkelijk ongebruikt zijn.
- Bestaande Node/scanner-CI en Python Leads-runtime-CI moeten groen zijn vóór merge/releaseclaims.
