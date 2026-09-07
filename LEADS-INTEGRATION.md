# Leads integration contract

`Yolol100/Leadscanner` is de enige GitHub-runtime voor de repository-capabilities van Leads. Dit bestand is de menselijke canonieke integratiebron; `toolkit-contract.json` is de machineleesbare canonieke bron. README en AGENTS verwijzen hiernaar.

De Leads-policy blijft bron van waarheid voor bedrijfsrealness, Customer Potential, kwalificatiegrenzen, contactbewijs, LeadPromo-copy, compliance en verzendgates. De repository mag die policy deterministisch uitvoeren voor een begrensde zero-touch prepare-route, maar mag nooit zelfstandig een compliancebasis verzinnen, `compliance_status=approved` zetten of live send permission creëren.

De zichtbare keten blijft:

`VIND -> KWALIFICEER -> CONTACT + MAIL -> VERSTUUR + LEER`

Zero-touch automatisering loopt zelfstandig tot en met prepare. `VERSTUUR + LEER` blijft een aparte fail-closed transportroute.

## Capability 1 — prospect_discovery

Workflow: `.github/workflows/prospect-discovery.yml`.

- Leest alleen expliciet goedgekeurde `ProspectSources` en schrijft company/domain-kandidaten naar `ProspectCandidates`; geen contactharvesting, compliance, mailcopy of send permission.
- Ondersteunt `seed_site`, `directory_page`, `directory_index` en `directory_sitemap`.
- `directory_sitemap` accepteert alleen begrensde publieke XML `urlset`/`sitemapindex`, volgt maximaal drie same-host child-sitemaps en blokkeert externe child-sitemaps, DTD/entities en private-network targets.
- Huidig targetbeleid laat `NL` standaard toe. Prioriteit is `US` eerst, `NL` tweede en daarna overige geconfigureerde landen. `webactueel.nl` en subdomeinen blijven self-excluded.
- Agency/providerfilter staat standaard aan.
- Source-semantics blokkeert directory-provider-infrastructuur, duidelijke navigatie/institutionele identiteiten en manufacturing-directory drift. Manufacturing-directory kandidaten moeten op de officiële site manufacturing/industrial evidence hebben.
- Bekende domeinen worden vóór source-outputquota overgeslagen. Navigatie/providerlinks worden gedeprioriteerd; source-owned parent/subdomains tellen niet als prospect.
- Standalone runtime heeft veilige projectdefaults: canonical `OUTREACH_SPREADSHEET_ID` fallback, `PROSPECT_DISCOVERY_TARGET_NEW=10`, hard max total 25, timeout 10 s, max 2 MiB per fetch en minimuminterval 0,5 s. Repo-variabelen mogen deze bounded defaults aanscherpen/instellen. Als het bounded doel niet wordt gehaald, wordt dat eerlijk als `target_gap` gerapporteerd; er wordt geen completion verzonnen.
- `ProspectObservations` bewaart provenance/freshness en `ProspectSourceRuns` bronstatus/yield/duplicates/duration/error. Dit is bewijscontext, nooit kwalificatie of send permission.
- Modi: `validate`, `bootstrap`, `discover`. Weekdays blijven `validate` tenzij `PROSPECT_DISCOVERY_ENABLED=true`.
- Ontvangt `GOOGLE_SERVICE_ACCOUNT_JSON`, maar nooit mailbox-, SMTP/IMAP-, seed- of verifiersecrets.

## Capability 2 — contact_enrichment

Workflow: `.github/workflows/contact-enrichment.yml`.

- Alleen `ProspectCandidates.status=qualified`.
- Inspecteert bounded de officiële homepage plus maximaal drie contact/about/team-achtige pagina's.
- Raad of construeer nooit een e-mailadres; no-reply, systeem- en free-mailadressen worden niet als ready gepromoveerd.
- Domeinalignment en MX worden gecontroleerd. `ContactCandidates.ready` is contactbewijs, nooit toestemming of send permission.
- Default maximaal 10, hard maximaal 25 per run; canonical Sheet fallback en bounded timeout/pacing blijven actief.
- Ontvangt alleen Sheetcredential, geen mailboxcredentials.

## Capability 3 — website_evidence_scan

Workflow: `.github/workflows/scan.yml`.

Optioneel read-only browser/crawlbewijs voor een expliciete audit of een technisch bewijs-gat.

- Publieke officiële website vereist; GET/HEAD-only.
- Geen login, submit, bestelling, betaling, boeking of andere state-changing actie.
- SSRF/private-network, redirect, TLS, robots en byte/timeout-grenzen blijven actief.
- `401`, `403`, `429` zijn toegangsblokkades, geen salesbevindingen.
- Uitvoer: `scan-results/leads-handoff.json` plus run-scoped evidence.
- Scannerbewijs verandert nooit zelfstandig score, compliance of transportpermission.

## Capability 4 — sender_readiness

Workflow: `.github/workflows/sender-readiness.yml`.

Technische diagnostiek: SPF, DKIM, DMARC, MX, SMTP TLS/STARTTLS, IMAP TLS, mailboxauth wanneer beschikbaar, en optioneel exact PTR/FCrDNS/DNSBL voor een expliciet outbound IP.

Voor mijn.host kan de gedeelde relay als `provider_managed` worden vastgelegd wanneer `include:spf.mijn.host` aantoonbaar via SPF groen is en geen vast egress-IP eerlijk kan worden bewezen. `provider_managed` betekent niet dat per-IP reputatie, DNSBL-clearance of globale inboxplaatsing bewezen is. Een expliciet outbound IP heeft voorrang en activeert exacte PTR/FCrDNS/DNSBL-controles.

Harde DNS/auth/TLS/PTR/FCrDNS/DNSBL-fouten blokkeren. Sender readiness is nooit compliancebewijs.

## Capability 5 — inbox_placement

Workflow: `.github/workflows/inbox-placement.yml`.

- Handmatige seedtest; geen warmup-netwerk.
- Default `validate` en dan geen verzending.
- `test` vereist expliciete bevestiging en geconfigureerde seedcredentials.
- Maximaal vijf vooraf geconfigureerde seed-inboxen; nooit `OutreachQueue`-ontvangers.
- Readback: `inbox | spam | missing | error` naar `InboxPlacement`.
- Een seedresultaat is geen globale placementgarantie of send permission.

## Capability 6 — mailbox_draft

Workflow: `.github/workflows/myhost-draft-test.yml`.

- Expliciete self-only mijn.host-concepttest.
- Alleen IMAP `APPEND` met `\\Draft`; geen SMTP-send.
- Detecteert special-use Drafts en alleen ondubbelzinnige Drafts/Concepten fallback of expliciet bestaande map.
- Unieke `X-Webactueel-Draft-Test-ID` moet in dezelfde map read-only teruggevonden worden.
- Geen Sheetmutatie, Leadstate, schedule of send permission.

## Capability 7 — outreach_delivery

Workflow: `.github/workflows/outreach-smtp.yml`.

Voor een afzonderlijke read-only controle van een exacte US-cohort gebruik `.github/workflows/outreach-cohort-validation.yml` handmatig met `expected_lead_ids`. De Sheet komt uitsluitend uit `OUTREACH_SPREADSHEET_ID`; cohort-ID's en Sheet-fallbacks horen niet in broncode. Deze controle dispatcht geen outreach en verstuurt niets. De bestaande guard en live-preflights blijven van toepassing.

De runtime accepteert alleen vooraf voorbereide en afzonderlijk goedgekeurde transportstate. De relevante fail-closed volgorde is:

```text
campaign policy
-> private Config load + masking
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

De kern-livegate blijft:

```text
-> live sender readiness gate
-> website target + evidence preflight
-> LeadPromo copy preflight
```

- Handmatige default is `validate`. Scheduled live vereist bovendien `OUTREACH_ENABLED=true`.
- Relevante push naar `main` wordt hard naar validate-only geforceerd en ontvangt geen live mailboxsecret.
- Private fysieke adresconfig wordt uit de private Config Sheet geladen, direct gemaskeerd en alleen in de huidige jobomgeving gezet; geen plaintext repositoryvariabele is nodig.
- Iedere `approved` queue-row vereist `source=website_scan:<JSON>` met same-domain `evidence_url`, `analysis_type=website|webshop`, exacte evidence-bound fact/idea in de body en actuele officiële-targetcontrole.
- Nederland/EER blijft fail-closed zonder aantoonbare geldige compliancebasis; een openbaar adres, A-score of ready contact is nooit genoeg.
- `US` vereist het private fysieke postadres in de body plus duidelijke commercial/advertising-identificatie en de overige opt-out/evidence/compliancegates.
- `GB` unsolicited route vereist bewezen corporate-subscribercontext plus duidelijke Ltd/Limited/LLP/PLC-vorm; onzekerheid blokkeert.
- LeadPromo blijft gecontroleerd NL/EN, CTA A/B, initial + één canonieke follow-up.
- Suppression wordt vóór send gecontroleerd; reply, bounce en opt-out stoppen vervolg fail-closed.
- Direct SMTP vereist geen Reoon.

## Capability 8 — dashboard

Google Sheet `Webactueel Leadlijst` bevat één read-only `Dashboard`.

- Aggregatie uit ProspectCandidates, ContactCandidates, OutreachQueue, Suppression, MailboxHealth, SenderReadiness en InboxPlacement.
- Lege diagnostiek = `not_tested`, nooit automatisch groen.
- Formules muteren geen Lead-, kwalificatie-, compliance- of transportstate.

## Capability 9 — prospect_intelligence

Workflow: `.github/workflows/prospect-intelligence.yml`.

- Modi `validate`, `bootstrap`, `refresh`; weekday schedule blijft `validate` tenzij `PROSPECT_INTELLIGENCE_ENABLED=true`.
- Veilige standalone defaults: canonical Sheet fallback en stale-days 30.
- Krijgt alleen Sheetcredential, geen mailcredentials.
- Bouwt entities, source metrics, evidence edges, freshness en lookalikes uit bestaande evidence-bound state.
- Deze afgeleide intelligence-views wijzigen nooit zelfstandig Customer Potential, compliance, contactpromotie, copy of send permission.

## Capability 10 — prospect_signal_discovery

Workflow: `.github/workflows/prospect-signal-discovery.yml`.

- Modi `validate`, `discover`; weekday schedule blijft validate tenzij `PROSPECT_SIGNAL_DISCOVERY_ENABLED=true`.
- Veilige standalone defaults: canonical Sheet fallback, max 10 per run, hard max 25, timeout 10 s, max 524288 bytes, minimuminterval 0,5 s.
- Alleen bestaande discovered/qualified/hold candidates; rejected wordt niet gescand.
- Detecteert alleen evidence-bound `hiring`, `technology_wordpress`, `technology_woocommerce` op officiële site.
- Signal strength is bewijscontext, nooit zelfstandig toestemming, kwalificatie of send permission.

## Capability 11 — prospect_qualification

Script: `scripts/prospect_qualification.py`; georkestreerd door `.github/workflows/leads-autopilot.yml`.

- Nieuwe/onbeoordeelde candidates krijgen voorrang. Eerder beoordeelde discovered/hold/qualified/rejected rows kunnen alleen bounded opnieuw worden beoordeeld na de ingestelde leeftijd of via expliciete force-recheck.
- Maximaal 25 assessments per run; default recheck 30 dagen.
- Iedere assessment herhaalt de self/agency/source-semantic firewall. Een eerder door directory/provider/navigation/manufacturing-noise afgekeurde kandidaat kan niet door scoring opnieuw qualified worden.
- Officiële homepage wordt via bounded HTTP/robots/SSRF gelezen. Fetch/evidence-onzekerheid wordt `UNSCORED` + `hold`, niet een verzonnen C-beslissing.
- Customer Potential: `ICP 0-3 + één primaire evidence-bound websitekans 0-3 + actief signaal 0-2 + offer fit 0-2`.
- A=8-10 -> qualified; B=6-7 -> hold; C=0-5 -> rejected.
- Generieke kleine hiaten worden niet opgeteld tot kunstmatig 3 punten. Manufacturer-only pagina's gebruiken conservatievere ICP/offer-fit. A vereist officiële-page fact + idea.
- `ProspectQualifications` bewaart scorecomponenten, totaalscore, tier, evidence URL, fact, idea, analysis type, status en reden.
- Kwalificatie verandert nooit compliance, contactpermission of send permission.

`ProspectQualifications` contract:

`candidate_id | assessed_at | company | website | country | icp_score | website_opportunity_score | signal_score | offer_fit_score | customer_potential | tier | evidence_url | fact | idea | analysis_type | status | reason`

## Capability 12 — zero_touch_prepare

Workflow: `.github/workflows/leads-autopilot.yml`.

Automatische prepare-keten:

```text
prospect_discovery
-> prospect_candidate_sanitizer
-> prospect_signal_discovery
-> prospect_qualification
-> contact_enrichment
-> prospect_intelligence
-> private_outreach_config
-> outreach_prepare
```

- Handmatig `validate|prepare`, default validate; weekday schedule draait bounded prepare.
- Een gecontroleerde `ops/leads-autopilot-request.txt` push kan prepare/prepare-recheck activeren wanneer de connector geen workflow-dispatch write biedt.
- Ontvangt `GOOGLE_SERVICE_ACCOUNT_JSON` maar geen `OUTREACH_MAIL_PASSWORD`, `OUTREACH_MAILBOXES_JSON` of seedsecret; roept nooit SMTP aan en heeft `send_permission=none`.
- Alleen current A-qualified + `ContactCandidates.ready` kan prepared copy opleveren.
- Source-semantic sanitizer draait vóór qualification; explicit bounded recheck kan stale kwalificaties opnieuw beoordelen.
- Private runtimeconfig wordt uit `Webactueel Outreach Config Private` geladen en gemaskeerd voordat US copy wordt opgebouwd.
- Nieuwe automated queue-state is altijd `status=prepared`, `compliance_status=manual_review`, lege `compliance_basis`.
- Bestaande automated prepared rows die niet langer A+ready zijn, worden fail-closed naar `manual_review` gereconcilieerd.
- US prepared copy vereist de private postal address en commercial-message-identificatie.
- Prepared lead kan als `gevonden` in de minimale Leadlijst staan; alleen Capability 7 kan later na actuele gates live transport uitvoeren.

## Data-contracten

Minimaal bewaakt: `Leadlijst`, `ProspectSources`, `ProspectCandidates`, `ProspectObservations`, `ProspectSourceRuns`, `ProspectSignals`, `ProspectQualifications`, `ProspectEntities`, `ProspectSourceMetrics`, `ProspectEvidence`, `ProspectLookalikes`, `ContactCandidates`, `OutreachQueue`, `OutreachSequences`, `ReplyInbox`, `Suppression`, `OutreachLog`, `VariantAnalytics`, `MailboxHealth`, `SenderReadiness`, `InboxPlacement`, `Dashboard`.

`mailbox_draft` schrijft bewust niet naar de Sheet; bewijs is de IMAP same-folder readback.

## Compliance- en transportgrenzen

- Leads-policy bezit geldige waarden/reglementen voor jurisdiction, `compliance_basis`, `compliance_status` en LeadPromo-copy.
- De repository mag score/copyregels uitvoeren maar vult nooit juridische basis op basis van alleen openbaar e-mailadres, land of technisch signaal.
- Nederland/EER: live alleen met geldige evidence-bound basis en approved state.
- Verenigde Staten: postadres/commercial-identificatie/opt-outgates zijn aanvullend; technische sender-green vervangt ze niet.
- Verenigd Koninkrijk: corporate-subscribermetadata is aanvullende targetgate en vervangt overige toepasselijke verplichtingen niet.
- Creator-/vendorclaims zijn adviserend; primaire regels en eigen provider-/klantreadback hebben voorrang.

## GitHub Actions Secrets en private config

- `GOOGLE_SERVICE_ACCOUNT_JSON`: Sheettoegang voor operationele capabilities.
- `OUTREACH_MAIL_PASSWORD`: uitsluitend live SMTP/IMAP, mailbox-connectivity, mailbox_draft en expliciete seedtest.
- `OUTREACH_MAILBOXES_JSON`: optioneel multi-mailbox, nooit discovery/qualification/prepare.
- `OUTREACH_SEED_INBOXES_JSON`: uitsluitend expliciete seed-placement.
- `REOON_API_KEY`: niet nodig voor actieve direct-SMTP-route.
- `OUTREACH_CONFIG_SPREADSHEET_ID`: optionele niet-geheime locator van de private Config Sheet. De fysieke adreswaarde zelf blijft buiten repositoryvariables, code, logs en artifacts.

## Belangrijkste runtimevariabelen

- Sheet: `OUTREACH_SPREADSHEET_ID` met canonical projectfallback in actieve Leads-workflows.
- Discovery: `PROSPECT_DISCOVERY_*`.
- Signals: `PROSPECT_SIGNAL_*`.
- Qualification: `PROSPECT_QUALIFICATION_*` inclusief recheck-days/force-recheck.
- Contact: `CONTACT_ENRICHMENT_*`.
- Prepare: `OUTREACH_PREPARE_MAX_PER_RUN`, `OUTREACH_CONFIG_SPREADSHEET_ID`, sender-id zonder password.
- Intelligence: `PROSPECT_INTELLIGENCE_*`.
- Sender readiness: `OUTREACH_OUTBOUND_IP`, `OUTREACH_DNSBL_ZONES` optioneel voor expliciete-IPbewijzen; mijn.host shared relay kan provider-managed zijn.
- Outreach: enable/mode/timezone/sendwindow/limits/pacing/ramp/jitter plus SMTP/IMAP/DKIM/SPF-config.

Gebruik de workflows zelf als waarheid voor exacte actuele defaults en hard caps.

## Runtime ownership en hygiene

- Leads gebruikt voor GitHub-uitvoering uitsluitend `Yolol100/Leadscanner`; een externe orchestrator is geen technische dependency.
- Klant-, secret- en runstate blijft buiten permanente broncode.
- Runtime-output gaat naar Sheets/artifacts en niet terug naar main.
- Relevante main-pushes blijven outreach validate-only.
- Node/scanner-CI, Leads Runtime CI en Toolkit Contract moeten groen zijn vóór releaseclaims.
- Branch protection/rulesets zijn change-control-hygiene; runtimeveiligheid hangt er niet van af. Als het GitHub-plan enforcement niet ondersteunt, blijft dat expliciet als adminbeperking staan.

## Live activering

1. Zero-touch prepare mag zelfstandig draaien; dit verzendt niets.
2. Houd live transport uit zonder expliciete live-opdracht.
3. Vereis actuele sender-readiness en mailboxauth.
4. Vereis per row aantoonbare `compliance_basis` + `compliance_status=approved` en schone suppression.
5. Draai outreach eerst in `validate` en controleer target/evidence, LeadPromo-copy en compliance.
6. Start alleen na expliciete live/autopilot-sendopdracht een gecontroleerde live-run.
7. Accepteer alleen echte SMTP acceptance plus IMAP/reply/bounce/opt-out readback als transportbewijs.

Cohort validation rejects empty expected sets, duplicate queue identities (regardless of row order), and approved rows without a lead ID. It never selects the last duplicate row as authoritative and never creates send permission.
