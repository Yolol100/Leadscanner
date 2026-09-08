# Leads integration contract

`Yolol100/Leadscanner` is de enige GitHub-runtime voor de repository-capabilities van Leads. Dit bestand is de menselijke canonieke integratiebron; `toolkit-contract.json` is de machineleesbare canonieke bron. README en AGENTS verwijzen hiernaar.

De Leads-policy blijft bron van waarheid voor bedrijfsrealness, Customer Potential, offerselectie, contactbewijs, LeadPromo-copy, compliance en verzendgates. De repository mag die policy deterministisch uitvoeren voor een begrensde prepare-route, maar mag nooit zelfstandig een compliancebasis verzinnen, `compliance_status=approved` zetten of live send permission creëren.

De zichtbare keten blijft:

`VIND -> KWALIFICEER -> CONTACT + MAIL -> VERSTUUR + LEER`

Voor nieuwe prospecting is `ai_agent` de standaard offer family. Legacy website/webshop-evidence blijft alleen bestaan voor rollback en reeds voorbereide transportstate.

## Goedgekeurde agentcatalogus

Nieuwe Leads-outreach selecteert exact één van deze zes productized agents:

1. `front_desk_sales` — **AI Front Desk & Sales Agent**: eerste telefoon/chat/berichtvragen beantwoorden uit goedgekeurde kennis, aanvraaggegevens verzamelen, kwalificeren, CRM-context vastleggen, afspraken boeken/verplaatsen waar gekoppeld, afgesproken follow-up en menselijke overdracht.
2. `lead_reactivation` — **AI Comeback Agent**: uitsluitend een door de klant goedgekeurde oude-lead/offertegroep opnieuw benaderen, interesse herkennen, herkwalificeren, terug naar sales/afspraak routeren en direct stoppen bij opt-out/no-interest/bounce.
3. `review_concierge` — **AI Review Agent**: na een vastgelegde completion-trigger een reviewverzoek en maximaal één nette follow-up uitvoeren; reviewreacties mogen alleen binnen goedgekeurde regels worden voorbereid; geen review gating of fake reviews.
4. `customer_support` — **AI Customer Support Agent**: standaardvragen beantwoorden vanuit goedgekeurde kennis en toegestane account/ordercontext, tickets/context verzamelen en complexe gevallen met samenvatting overdragen.
5. `commerce` — **AI Commerce Agent**: product discovery/comparison en order/retourhulp op basis van echte catalogus-, prijs-, voorraad- en orderdata; nooit waarden verzinnen.
6. `quote_intake` — **AI Quote & Intake Agent**: intake/offertegegevens verzamelen, ontbrekende informatie navragen, CRM/projectcontext vastleggen en concept-intake/offerte voorbereiden; bindende prijs/voorwaarden vereisen menselijke goedkeuring.

Een generieke FAQ-bot, volledig autonome algemene AI-medewerker, losse `sales closer` of willekeurige cold-calling agent is geen standaardproduct. Salesvragen en kwalificatie zitten in `front_desk_sales`.

## Customer Potential voor agentverkoop

Kwalificatie gebruikt uitsluitend officiële evidence en één primaire agentkans:

`ICP 0-3 + agent opportunity 0-3 + active signal 0-2 + value/integration fit 0-2`

- A = 8-10 -> `qualified`
- B = 6-7 -> `hold`
- C = 0-5 -> `rejected`

A vereist een brongebonden `fact`, concrete `idea`, goedgekeurde `agent_type`, `business_process`, `kpi_candidate` en integratiecontext. Generieke contactmogelijkheid alleen is onvoldoende voor automatische A-kwalificatie. Fetch/evidence-onzekerheid wordt `UNSCORED` + `hold`, niet een verzonnen afwijzing.

Creator-, YouTube- en vendorcases zijn research/hypothese. Ze mogen geen prospect-specifieke pijn, volume, besparing, omzet of ROI bewijzen en bepalen geen prijs.

## Capability 1 — prospect_discovery

Workflow: `.github/workflows/prospect-discovery.yml`.

- Leest alleen goedgekeurde `ProspectSources` en schrijft company/domain-kandidaten naar `ProspectCandidates`.
- Geen contactharvesting, kwalificatie, mailcopy, compliance of send permission.
- Ondersteunt `seed_site`, `directory_page`, `directory_index` en begrensde `directory_sitemap`.
- Agency/provider-, self- en source-semantic filters blijven fail-closed.
- Bekende domeinen worden vóór quota overgeslagen; target gaps blijven expliciet. `PROSPECT_DISCOVERY_TARGET_NEW` bepaalt alleen een begrensd gewenste nieuwe-candidate-output en dwingt nooit verzonnen filler af.
- `ProspectSourceRuns`, source metrics en target-gap-readback zijn discovery/intelligencebewijs en geven nooit kwalificatie of send permission.
- Weekday schedule blijft validate-only tenzij `PROSPECT_DISCOVERY_ENABLED=true`.
- Krijgt alleen Sheetcredential, geen mailboxsecrets.

## Capability 2 — contact_enrichment

Workflow: `.github/workflows/contact-enrichment.yml`.

- Alleen `ProspectCandidates.status=qualified`.
- Begrensde officiële-sitecontactevidence; e-mail wordt nooit geraden of geconstrueerd.
- `ContactCandidates.ready` is bewijs dat een openbaar zakelijk contact bruikbaar is, nooit commerciële toestemming of send permission.

## Capability 3 — website_evidence_scan

Workflow: `.github/workflows/scan.yml`.

Optioneel read-only browser/crawlbewijs voor een expliciete audit of technisch bewijs-gat. Geen login/form/order/payment/booking. Scannerbewijs verandert nooit zelfstandig Customer Potential, compliance of transportpermission.

## Capability 4 — sender_readiness

Workflow: `.github/workflows/sender-readiness.yml`.

Technische diagnostiek voor SPF/DKIM/DMARC/MX/TLS/auth en waar bewijsbaar PTR/FCrDNS/DNSBL. Een bewezen mijn.host shared relay kan `provider_managed` zijn zonder per-IP reputatie of globale inboxplaatsing te claimen. Readiness is nooit compliancebewijs.

## Capability 5 — inbox_placement

Workflow: `.github/workflows/inbox-placement.yml`.

Handmatige seed-only test, standaard `validate`, maximaal vijf vooraf geconfigureerde seed-inboxen en nooit `OutreachQueue`-ontvangers. Geen warmup-netwerk en geen send permission voor prospects.

## Capability 6 — mailbox_draft

Workflow: `.github/workflows/myhost-draft-test.yml`.

Self-only mijn.host IMAP `APPEND` + same-folder readback. Geen SMTP, Sheetmutatie of commercial send permission.

## Capability 7 — outreach_delivery

Workflow: `.github/workflows/outreach-smtp.yml`.

De fail-closed livevolgorde blijft:

`campaign policy -> private config -> sender preflight -> extended contract -> sender readiness -> target/evidence -> LeadPromo copy -> compliance -> SMTP -> IMAP readback -> reporting`

- Manual default = `validate`.
- Push/CI naar `main` krijgt geen live mailboxsecret en verzendt nooit live.
- Nieuwe agentrows gebruiken `source=agent_offer:<JSON>` met same-domain `evidence_url`, exacte fact/idea, `offer_family=ai_agent`, goedgekeurde agent type, business process en KPI candidate.
- Legacy `source=website_scan:<JSON>` blijft uitsluitend voor bestaande website/webshop-transportcompatibiliteit.
- De officiële homepage wordt vóór SMTP opnieuw tegen target/providerregels gecontroleerd.
- Nederland/EER blijft fail-closed zonder actuele evidence-bound geldige compliancebasis; openbaar e-mailadres, A-score of ready contact is onvoldoende.
- US houdt private postal config buiten de publieke queue en injecteert de fysieke adreswaarde pas in-memory bij send; queue bevat alleen de placeholder plus commercial identification.
- GB unsolicited route vereist bewezen corporate-subscribercontext plus duidelijke Ltd/Limited/LLP/PLC-vorm.
- Suppression, reply, bounce en opt-out stoppen vervolg fail-closed.

## Capability 8 — dashboard

Google Sheet `Dashboard` is read-only aggregatie. Lege diagnostiek blijft `not_tested`; formules mogen geen Lead-, kwalificatie-, compliance- of transportstate muteren.

## Capability 9 — prospect_intelligence

Workflow: `.github/workflows/prospect-intelligence.yml`.

Afgeleide entity/freshness/source-performance/evidence/lookalike-laag. Adviserend; wijzigt nooit zelfstandig Customer Potential, compliance, contactpromotie, copy of send permission.

## Capability 10 — prospect_signal_discovery

Workflow: `.github/workflows/prospect-signal-discovery.yml`.

Bounded officiële-site hiring en WordPress/WooCommerce signalen. Signal strength is evidencecontext; punten tellen alleen mee via de gedeelde actuele recency policy en creëren nooit toestemming.

## Capability 11 — prospect_qualification

Script: `scripts/prospect_agent_qualification.py`; georkestreerd door `.github/workflows/leads-autopilot.yml`.

- Maximaal 25 assessments; default recheck 30 dagen.
- Herhaalt self/agency/source-semantic firewall per assessment.
- Leest officiële homepage bounded en fail-closed.
- Selecteert één primaire agentkans uit de zes goedgekeurde types.
- Schrijft audit naar `AgentProspectQualifications`.
- Verandert nooit compliance of send permission.

`AgentProspectQualifications` contract:

`candidate_id | assessed_at | company | website | country | icp_score | agent_opportunity_score | signal_score | value_integration_fit_score | customer_potential | tier | evidence_url | fact | idea | offer_family | agent_type | business_process | kpi_candidate | integration_hint | status | reason`

Legacy `ProspectQualifications` blijft bestaan voor historische website/webshoprecords maar is niet de standaard nieuwe qualification output.

## Capability 12 — zero_touch_prepare

Workflow: `.github/workflows/leads-autopilot.yml`.

Nieuwe prepare-keten:

`prospect_discovery -> prospect_candidate_sanitizer -> prospect_signal_discovery -> prospect_agent_qualification -> contact_enrichment -> prospect_intelligence -> private_outreach_config -> outreach_agent_prepare`

- Handmatig `validate|prepare`; weekday schedule draait bounded prepare.
- Krijgt alleen `GOOGLE_SERVICE_ACCOUNT_JSON` en gewone vars; nooit mailboxcredentials of SMTP.
- Alleen actuele A-qualified `ai_agent` + `ContactCandidates.ready` mag deterministic agentcopy produceren.
- Agentmail bevat geen verzonnen vaste prijs. De catalogus heeft standaard `pricing_mode=no_price` totdat Webactueel expliciet een prijsbeleid vastlegt.
- Nieuwe queue-state blijft `status=prepared`, `compliance_status=manual_review`, lege `compliance_basis`.
- Stale automated agentrows worden fail-closed naar `manual_review` gereconcilieerd.
- `send_permission=none`.

## Data-contracten

Minimaal bewaakt: `Leadlijst`, `ProspectSources`, `ProspectCandidates`, `ProspectObservations`, `ProspectSourceRuns`, `ProspectSignals`, `AgentProspectQualifications`, legacy `ProspectQualifications`, `ProspectEntities`, `ProspectSourceMetrics`, `ProspectEvidence`, `ProspectLookalikes`, `ContactCandidates`, `OutreachQueue`, `OutreachSequences`, `ReplyInbox`, `Suppression`, `OutreachLog`, `VariantAnalytics`, `MailboxHealth`, `SenderReadiness`, `InboxPlacement`, `Dashboard`.

## Compliance- en evidencegrenzen

- Leads-policy bezit juridische/commerciële interpretatie; de repository voert alleen de begrensde technische contracten uit.
- Nieuwe agentrows erven nooit een oude compliancebasis of oude live-cohortgoedkeuring.
- Geen missed-call-, workload-, omzet-, besparings- of ROI-claim zonder prospect-specifiek bewijs.
- Geen agentprijs afleiden uit YouTube, creators of vendorcases.
- Creator-/vendorresearch is adviserend; actuele primaire regels, officiële productdocumentatie en echte Webactueel-uitkomsten wegen zwaarder.
- `agent_offer:` is evidence metadata, geen bewijs dat het beloofde bedrijfsresultaat reeds is behaald.

## Secrets

- `GOOGLE_SERVICE_ACCOUNT_JSON`: operationele Sheettoegang.
- `OUTREACH_MAIL_PASSWORD`: uitsluitend mailbox/live transport en expliciete mailboxtests.
- `OUTREACH_MAILBOXES_JSON`: optionele mailboxpool, nooit discovery/qualification/prepare.
- `OUTREACH_SEED_INBOXES_JSON`: uitsluitend seed-placement.
- `REOON_API_KEY`: niet vereist voor de actieve direct-SMTP-route.
- Fysiek postadres blijft in private runtimeconfig, niet in repo/public queue.

## Releasebewijs

Voor releaseclaims moeten minimaal `Toolkit Contract`, `Leads Runtime CI` en `Scanner Smoke Test` groen zijn op de relevante code. Een groene test is code-/contractbewijs; live Sheet/mailbox-state vereist aparte runtime/readback en live prospectsend blijft alleen mogelijk na expliciete live-intentie plus alle huidige gates.