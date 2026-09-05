# Leads integration contract

`Yolol100/Leadscanner` is de enige GitHub-runtime voor de repository-capabilities van Leads. Dit bestand is de **menselijke canonieke integratiebron**; `toolkit-contract.json` is de machineleesbare canonieke bron. README en AGENTS verwijzen hiernaar en herhalen de volledige contractdetails niet.

De Leads-policy blijft de bron van waarheid voor bedrijfsrealness, Customer Potential, kwalificatiegrenzen, contactbewijs, LeadPromo-copy, compliance en verzendgates. De repository mag die policy nu voor een **begrensde zero-touch prepare-route** deterministisch uitvoeren: officiële-sitebewijs verzamelen, Customer Potential berekenen, A/B/C classificeren, een brongebonden contact zoeken en LeadPromo-copy voorbereiden. Deze automatisering mag **nooit** zelfstandig een compliancebasis verzinnen, `compliance_status=approved` zetten of live verzendpermission creëren.

De zichtbare keten blijft:

`VIND -> KWALIFICEER -> CONTACT + MAIL -> VERSTUUR + LEER`

De zero-touch automatisering loopt zelfstandig tot en met **prepare**. `VERSTUUR + LEER` blijft een aparte fail-closed transportroute met eigen live-gates.

## Capability 1 — prospect_discovery

Workflow: `.github/workflows/prospect-discovery.yml`.

- Leest alleen expliciet goedgekeurde `ProspectSources`.
- Ondersteunt `seed_site`, `directory_page`, `directory_index` en `directory_sitemap`.
- `directory_sitemap` accepteert alleen begrensde publieke XML `urlset`/`sitemapindex`-bronnen, volgt uitsluitend same-host profiel-URLs en maximaal drie same-host child-sitemaps; externe child-sitemaps worden genegeerd.
- XML blijft onder dezelfde robots-, public-network/SSRF-, timeout-, pacing- en bytegrenzen als HTML discovery; DTD/entity-declaraties worden geblokkeerd.
- Huidig targetbeleid laat `NL` standaard toe. De standaard bronprioriteit is `US` eerst, `NL` tweede en daarna de overige geconfigureerde landen.
- `webactueel.nl` en alle subdomeinen blijven self-excluded.
- Agency-/concurrentfilter staat standaard aan voor duidelijke web/design/development/app/software/UX/marketing/advertising/SEO/branding/digital/commerce providers.
- Schrijft alleen company/domain-kandidaten naar `ProspectCandidates`; geen contactharvesting, Customer Potential, compliance of mailcopy.
- `PROSPECT_DISCOVERY_TARGET_NEW` probeert begrensd een doelvolume te vullen; `PROSPECT_DISCOVERY_MAX_TOTAL` blijft hard bovengrens.
- `ProspectObservations` bewaart verwerkings/provenancebewijs en rediscovery-freshness.
- `ProspectSourceRuns` bewaart per werkelijk verwerkte bron status, seen, new, duplicates, duration en begrensde fouttekst.
- Modi: `validate`, `bootstrap`, `discover`. De losse weekday schedule blijft `validate` tenzij `PROSPECT_DISCOVERY_ENABLED=true`.
- Ontvangt `GOOGLE_SERVICE_ACCOUNT_JSON`, maar nooit mailbox-, SMTP/IMAP-, seed- of verifiersecrets.

## Capability 2 — contact_enrichment

Workflow: `.github/workflows/contact-enrichment.yml`.

- Draait uitsluitend op `ProspectCandidates.status=qualified`.
- Inspecteert begrensd de officiële homepage plus maximaal drie contact/about/team-achtige pagina's.
- Raad, construeer of extrapoleer nooit een e-mailadres.
- Blokkeert no-reply/systeem/free-mail en controleert domeinalignment + MX.
- `ContactCandidates.ready` betekent uitsluitend officieel-sitecontactbewijs; het is nooit commerciële toestemming of send permission.
- Standaard maximaal 10 kandidaten, hard maximaal 25 per run.
- Ontvangt uitsluitend Sheetcredential, geen mailboxcredentials.

## Capability 3 — website_evidence_scan

Workflow: `.github/workflows/scan.yml`.

Optioneel read-only browser/crawlbewijs voor een expliciete website-audit of een concreet technisch bewijs-gat.

- Publieke officiële website vereist.
- GET/HEAD-only; geen login, formulier, bestelling, betaling, boeking of andere state-changing actie.
- Private/link-local/metadata-adressen, onveilige redirects en relevante robots/TLS-grenzen blijven geblokkeerd.
- `401`, `403` en `429` zijn toegangsblokkades, geen salesbevindingen.
- Uitvoer: `scan-results/leads-handoff.json` plus run-scoped evidence.
- Scannerbevindingen veranderen nooit zelfstandig compliance of transportpermission.

## Capability 4 — sender_readiness

Workflow: `.github/workflows/sender-readiness.yml`.

Technische diagnostiek per ingeschakelde mailbox:

- SPF, DKIM, DMARC en MX;
- SMTP-TLS/STARTTLS en IMAP-TLS;
- mailboxauth wanneer het secret aanwezig is;
- exact PTR/FCrDNS via een expliciet `OUTREACH_OUTBOUND_IP`;
- configureerbare IPv4 DNSBL-zones via `OUTREACH_DNSBL_ZONES` wanneer een expliciet IP beschikbaar is.

Voor mijn.host is daarnaast shared-relay-bewijs ingebouwd. Wanneer `OUTREACH_REQUIRED_SPF_TOKEN=include:spf.mijn.host` aantoonbaar via SPF groen is en geen expliciet vast uitgaand IP is geconfigureerd, wordt het netwerkdeel als `provider_managed` vastgelegd. Dit betekent alleen: de uitgaande relaypool wordt door mijn.host beheerd en één vast egress-IP kan vooraf niet eerlijk worden geclaimd. Het betekent **niet** dat per-IP reputatie, DNSBL-clearance of globale inboxplaatsing bewezen is. Een expliciet `OUTREACH_OUTBOUND_IP` heeft altijd voorrang en activeert de exacte PTR/FCrDNS/DNSBL-route. Een onbekende andere provider zonder IP blijft `review/not_configured`.

Een harde DNS/auth/TLS/PTR/FCrDNS/DNSBL-fout blokkeert. Sender readiness is nooit compliancebewijs.

## Capability 5 — inbox_placement

Workflow: `.github/workflows/inbox-placement.yml`.

- Handmatige seedtest, geen warmup-netwerk.
- Default `validate`; dan wordt niets verzonden.
- `test` vereist expliciete bevestiging, `OUTREACH_PLACEMENT_TEST_ENABLED=true`, mailboxauth en `OUTREACH_SEED_INBOXES_JSON`.
- Maximaal vijf vooraf geconfigureerde seed-inboxen; nooit `OutreachQueue`-ontvangers.
- Readback: `inbox | spam | missing | error` naar `InboxPlacement`.
- Eén seedresultaat is geen globale placementgarantie.

## Capability 6 — mailbox_draft

Workflow: `.github/workflows/myhost-draft-test.yml`.

- Expliciete self-only testcapability voor een concept in de echte mijn.host-mailbox.
- Uitsluitend IMAP `APPEND` met de `\Draft`-flag; er wordt geen SMTP-send uitgevoerd.
- Detecteert eerst special-use `\Drafts`, daarna alleen ondubbelzinnige `Drafts`/`Concepten` fallback of een expliciet bestaande `OUTREACH_DRAFT_FOLDER`.
- Elk concept krijgt een unieke `X-Webactueel-Draft-Test-ID`; dezelfde map moet die ID read-only terugvinden.
- Geen Sheetmutatie, geen Leadstate, geen schedule en `send_permission=none`.

## Capability 7 — outreach_delivery

Workflow: `.github/workflows/outreach-smtp.yml`.

De runtime accepteert alleen vooraf voorbereide én afzonderlijk goedgekeurde transportstate. De live-volgorde is:

```text
campaign policy
-> sender preflight
-> extended Sheet contract preflight
-> live sender readiness gate
-> website target + evidence preflight
-> LeadPromo copy preflight
-> compliance preflight
-> direct mijn.host SMTP runtime
-> IMAP reply/bounce/opt-out readback
-> reporting
```

- Handmatige default: `validate`.
- `live` is expliciet; scheduled live vereist bovendien `OUTREACH_ENABLED=true`.
- Push naar `main` wordt hard naar `validate` geforceerd en krijgt geen production mailboxsecret.
- Iedere `approved` queue-row moet `source=website_scan:<JSON>` bevatten met een officiële same-domain `evidence_url`, `analysis_type=website|webshop` en een concrete `idea` die exact in de mailtekst terugkomt.
- De officiële target-homepage wordt vóór SMTP opnieuw begrensd gecontroleerd op self-/agencyprovideruitsluiting.
- Nederland/EER blijft live fail-closed zonder aantoonbare geldige compliancebasis.
- `US` vereist fysiek postadres, aanwezigheid van dezelfde geconfigureerde adreswaarde in de mail en duidelijke commercial/advertising-identificatie.
- `GB` unsolicited route vereist bewezen corporate subscriber-context plus een duidelijke Ltd/Limited/LLP/PLC-vorm; onzekerheid blokkeert.
- LeadPromo-copy blijft NL/EN gecontroleerd, CTA A/B, initial + één canonieke follow-up, geen gemengde CTA/opt-out/signaturetaal.
- Suppression wordt vóór send gecontroleerd; reply, bounce en opt-out stoppen vervolg fail-closed.
- Direct SMTP vereist geen Reoon.

## Capability 8 — dashboard

De Google Sheet `Webactueel Leadlijst` bevat één read-only `Dashboard`.

- Aggregatie uit ProspectCandidates, ContactCandidates, OutreachQueue, Suppression, MailboxHealth, SenderReadiness en InboxPlacement.
- Lege readiness/placement/mailbox-healthbron = `not_tested`, nooit automatisch `green`.
- Dashboardformules muteren geen Lead-, kwalificatie-, compliance- of transportstate.

## Capability 9 — prospect_intelligence

Workflow: `.github/workflows/prospect-intelligence.yml`.

- Modi: `validate`, `bootstrap`, `refresh`; losse weekday schedule blijft `validate` tenzij `PROSPECT_INTELLIGENCE_ENABLED=true`.
- Krijgt alleen `GOOGLE_SERVICE_ACCOUNT_JSON`.
- `ProspectObservations` levert provenance/freshnessinput.
- `ProspectSignals` is evidence-bound input; onbekende kandidaat, ongeldige timestamp/URL/strength/confidence faalt gesloten.
- `ProspectEntities` normaliseert domeinentiteiten en aliases.
- `ProspectSourceMetrics` koppelt bronrendement aan bestaande kandidaat/contact/outcome-evidence.
- `ProspectEvidence` bouwt reproduceerbare source -> candidate/entity -> signal/contact/outcome edges.
- `ProspectLookalikes` gebruikt uitsluitend bewezen klantseeds.
- Deze laag is adviserend en wijzigt niet zelfstandig Customer Potential, compliance, contactpromotie, copy of send permission.

## Capability 10 — prospect_signal_discovery

Workflow: `.github/workflows/prospect-signal-discovery.yml`.

- Modi: `validate`, `discover`; losse weekday schedule blijft `validate` tenzij `PROSPECT_SIGNAL_DISCOVERY_ENABLED=true`.
- Alleen bestaande `discovered`, `qualified` of `hold` candidates; `rejected` wordt niet gescand.
- Standaard maximaal 10, hard maximaal 25 kandidaten per run.
- Zelfde robots-, public-network-, pacing-, timeout- en bytegrenzen als bounded discovery.
- Detecteert alleen evidence-bound `hiring`, `technology_wordpress`, `technology_woocommerce`.
- Externe joblinks gelden niet als official-site hiringbewijs.
- Signal `strength` is 0/1/2 bewijscontext, nooit zelfstandig toestemming.
- De collector mag alleen eigen `source_id=official-site-signal` rows lifecycle-beheren.

## Capability 11 — prospect_qualification

Script: `scripts/prospect_qualification.py`; georkestreerd door `.github/workflows/leads-autopilot.yml`.

Dit sluit de eerdere handmatige kloof tussen discovery en contact op een fail-closed manier.

- Alleen `discovered`/`hold` kandidaten komen in aanmerking.
- De officiële homepage wordt met de bestaande bounded HTTP/robots/SSRF-laag gelezen.
- Selftargets en duidelijke agency/providers worden opnieuw geblokkeerd.
- Customer Potential blijft exact: `ICP 0-3 + bewezen websitekans 0-3 + recent signaal 0-2 + aanbod/prijsfit 0-2`.
- A=8-10 -> `qualified`; B=6-7 -> `hold`; C=0-5 -> `rejected`.
- De websitekans gebruikt één primaire evidence-severity; generieke kleine hiaten worden niet opgeteld om kunstmatig 3 punten te maken.
- Een ontbrekende checkout telt alleen zwaar wanneer de homepage eerst duidelijke webshop/shoppingcontext bewijst; alleen het woord “product” is daarvoor onvoldoende.
- A vereist een concrete officiële-page `fact` én `idea`; zonder brongebonden idee wordt niet automatisch A-gekwalificeerd.
- `ProspectQualifications` bewaart per kandidaat alle vier componenten, totaalscore, tier, evidence URL, fact, idea, analysis type, status en reden.
- Deze capability mag kwalificatiestatus automatiseren, maar wijzigt nooit compliance, contactpermission of send permission.

`ProspectQualifications` contract:

`candidate_id | assessed_at | company | website | country | icp_score | website_opportunity_score | signal_score | offer_fit_score | customer_potential | tier | evidence_url | fact | idea | analysis_type | status | reason`

## Capability 12 — zero_touch_prepare

Workflow: `.github/workflows/leads-autopilot.yml`.

Dit is de automatische prepare-controller:

```text
prospect_discovery
-> prospect_signal_discovery
-> prospect_qualification
-> contact_enrichment
-> prospect_intelligence
-> outreach_prepare
```

- Handmatig: `validate|prepare`, default `validate`.
- Weekday schedule draait automatisch in `prepare`-modus.
- Een gecontroleerde eenmalige `ops/leads-autopilot-request.txt` push kan `prepare` activeren wanneer een connector geen workflow-dispatch ondersteunt.
- Ontvangt alleen `GOOGLE_SERVICE_ACCOUNT_JSON` en gewone niet-geheime configuratie.
- Ontvangt **geen** `OUTREACH_MAIL_PASSWORD`, `OUTREACH_MAILBOXES_JSON` of seedsecret.
- Roept nooit `outreach_direct_smtp_runtime.py` aan en heeft `send_permission=none`.
- Alleen A-qualified + `ContactCandidates.ready` kan mailcopy opleveren.
- `scripts/outreach_prepare.py` maakt uitsluitend deterministic LeadPromo NL/EN copy en valideert die opnieuw met de bestaande copy-preflightfuncties.
- Nieuwe queue-state is altijd `status=prepared`, `compliance_status=manual_review`, lege `compliance_basis` en dus niet sendable.
- US prepare vereist `OUTREACH_POSTAL_ADDRESS` en voegt een duidelijke commercial-message-identificatie plus het geconfigureerde adres toe.
- Prepared leads worden minimaal in `Leadlijst` vastgelegd als `gevonden` als het domein nog niet bestaat.
- Alleen de aparte outreach_delivery-route kan later na actuele compliance- en sendergates naar live.

## Data-contracten

Minimaal bewaakt:

- `Leadlijst`: `Bedrijf | Website | E-mail | Status`
- `ProspectSources`
- `ProspectCandidates`
- `ProspectObservations`
- `ProspectSourceRuns`
- `ProspectSignals`
- `ProspectQualifications`
- `ProspectEntities`
- `ProspectSourceMetrics`
- `ProspectEvidence`
- `ProspectLookalikes`
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

`mailbox_draft` schrijft bewust niet naar de Sheet; de bewijslaag is de IMAP same-folder readback.

## Compliance- en transportgrenzen

- Leads-policy bezit de geldige waarden en regels voor `country/jurisdiction`, `compliance_basis`, `compliance_status` en LeadPromo-copy.
- De repository mag de score/copyregels deterministisch uitvoeren, maar mag nooit een ontbrekende juridische basis invullen op basis van alleen een openbaar e-mailadres, land of technisch signaal.
- Nederland/EER blijft fail-closed: `ContactCandidates.ready`, qualification A, sender-readiness, seed-placement, prospect-intelligence of prepared copy is nooit zelfstandig toestemming voor commerciële outreach.
- Verenigde Staten: CAN-SPAM-content/opt-out/postadresgates zijn aanvullend; technische sender-green vervangt die niet.
- Verenigd Koninkrijk: corporate-subscribermetadata is een extra targetgate en vervangt geen overige toepasselijke privacy/lawful-basisverplichtingen.
- Creatorvideo's/comments zijn adviserend; actuele primaire regels en echte provider-/klantreadback hebben voorrang.

## GitHub Actions Secrets

Secretwaarden horen nooit in code, logs of artifacts.

- `GOOGLE_SERVICE_ACCOUNT_JSON` — nodig voor capabilities die de operationele Sheet lezen/schrijven.
- `OUTREACH_MAIL_PASSWORD` — uitsluitend live SMTP/IMAP, mailbox-connectivity, mailbox_draft en geconfigureerde seedtest.
- `OUTREACH_MAILBOXES_JSON` — optioneel voor multi-mailbox, nooit voor discovery/qualification/prepare.
- `OUTREACH_SEED_INBOXES_JSON` — uitsluitend voor expliciete seed-placement.
- `REOON_API_KEY` — niet gebruikt door de actieve direct-SMTP-route.

## Belangrijkste variabelen

- Sheet: `OUTREACH_SPREADSHEET_ID`.
- Discovery: `PROSPECT_DISCOVERY_*`.
- Signals: `PROSPECT_SIGNAL_*`.
- Qualification: `PROSPECT_QUALIFICATION_MAX_PER_RUN`, `PROSPECT_QUALIFICATION_TIMEOUT_SECONDS`, `PROSPECT_QUALIFICATION_MAX_BYTES`, `PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS`, `PROSPECT_QUALIFICATION_USER_AGENT`.
- Contact: `CONTACT_ENRICHMENT_*`.
- Prepare: `OUTREACH_PREPARE_MAX_PER_RUN`, `OUTREACH_POSTAL_ADDRESS`, sender-id vars zonder password.
- Intelligence: `PROSPECT_INTELLIGENCE_*`.
- Sender readiness: `OUTREACH_OUTBOUND_IP`, `OUTREACH_DNSBL_ZONES`; deze zijn optioneel voor mijn.host provider-managed shared-relaymode.
- Outreach: `OUTREACH_ENABLED`, mode, timezone/sendwindow, limits, pacing/ramp/jitter, SMTP/IMAP/DKIM/SPF-config.

Gebruik de workflows zelf als waarheid voor exacte defaults en harde bounds.

## Runtime ownership en hygiene

- Leads gebruikt voor GitHub-uitvoering uitsluitend `Yolol100/Leadscanner`; `Yolol100/Orchestrator` is geen technische dependency.
- Klant-, request-, secret- en run-specifieke state blijft buiten permanente broncode of run-scoped.
- GitHub Actions-evidence blijft in artifacts/Sheets; runtime-output wordt niet naar `main` teruggecommit.
- Relevante main pushes blijven veilig validate-only voor outreach.
- Bestaande Node/scanner-CI, Python Leads-runtime-CI en Toolkit Contract moeten groen zijn vóór releaseclaims.
- Repository-branchprotection is change-control-hygiene en staat los van de inhoudelijke sendgates; runtimeveiligheid mag er nooit van afhangen.

## Live activering

1. Zero-touch prepare mag zelfstandig blijven draaien; dit verzendt niets.
2. Houd `OUTREACH_ENABLED=false` zolang live niet expliciet gewenst is.
3. Vereis actuele `SenderReadiness` en mailboxauth.
4. Vereis per rij aantoonbare geldige `compliance_basis` + `compliance_status=approved`.
5. Draai `outreach-smtp.yml` eerst in `validate` en controleer target/evidence + LeadPromo + compliance.
6. Start alleen na expliciete live/autopilot-sendopdracht een gecontroleerde live-run.
7. Accepteer alleen echte SMTP acceptance + IMAP/reply/bounce/opt-out readback als transportbewijs.
