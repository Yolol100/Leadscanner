# Leads integration contract

`Yolol100/Leadscanner` is de geregistreerde GitHub-uitvoeringslaag voor Leads. Live Project Leads v16 is beleidswaarheid; `webactueel-workflow` blijft controller. De repository mag bewijs, queue-state en mijn.host-transport uitvoeren, maar kiest niet zelfstandig een andere commerciële strategie.

## Nieuwe standaardroute — v16 signal-first

`VIND -> BEGRIJP -> SIGNAAL -> EEN AANBOD -> OFFICIEEL CONTACT -> KORTE MAIL -> MIJN.HOST CONCEPT -> REPLY HANDOFF`

Voor een normaal nieuw concept zijn formele Customer Potential-score, A/B/C-tier en campaign-gate niet verplicht.

### Prospect en pagina's

- Begin op de officiële homepage.
- Lees daarna alleen maximaal 2-3 pagina's die het belangrijkste klantproces bewijzen.
- Diensten: dienst/prijzen/offerte/contact/booking.
- Webshops: categorie/product/cart/FAQ/retour/service.
- Lokaal: dienst/locatie/contact/reviews.
- About/Team/Contact alleen wanneer nodig voor een betrouwbare naam of zakelijk e-mailadres.
- Geen duidelijk publiek signaal of passend aanbod: prospect overslaan.

### Eén aanbod

Ondersteunde agentoffers:
`front_desk_sales`, `lead_reactivation`, `review_concierge`, `customer_support`, `commerce`, `quote_intake`.

Ondersteunde niet-agentoffers:
`website_webshop_improvement`, `search_visibility`, `social_management`.

`lead_reactivation` vereist een goedgekeurde first-party lijst. `search_visibility` vereist publieke zoekresultaatevidence plus site-evidence. `social_management` vereist publiek bewijs uit officiële social/contentkanalen. Pitch in de eerste mail exact één aanbod.

### Easy yes + mailcopy

Het eerste aanbod is klein: mini-flow, voorbeeld, mock-up, twee vindbaarheidskansen, drie postideeën of vergelijkbaar. De eerste mail is ongeveer 50-100 woorden, gebruikt één echte observatie, één concrete verbetering en één permission CTA zoals `Zal ik het voorbeeld sturen?`. Vraag niet direct om een lange meeting. Reviews/cases alleen kort wanneer echt en exact relevant; volledige proof hoort vooral in vervolg of landingspagina.

### Contact

Gebruik uitsluitend een publiek zakelijk adres dat op de officiële site aantoonbaar is gevonden. Raad of construeer geen adres. Een persoonsnaam mag alleen worden gebruikt wanneer naam en adres betrouwbaar aan elkaar gekoppeld zijn.

## Mijn.host drafttransport

Voorkeursroute voor nieuwe v16-concepten is de bestaande geselecteerde IMAP-sync (`sync-selected-myhost-drafts-command.yml` / `outreach_queue_imap_draft_sync_selected.py`). Die accepteert queueconcepten in `manual_review` of `approved`, schrijft alleen Drafts/Concepten, doet same-folder readback en roept geen SMTP aan.

De queue bevat minimaal stabiele `lead_id`, bedrijf, website, evidence/signaal, offer metadata, ontvanger, onderwerp en body. Dedupe op lead-id, ontvanger en inhoud. `send_permission=none` blijft de default.

De oudere single-draft-, Customer Potential-, A/B/C-, campaign-first- en agent-only paden blijven voorlopig bestaan voor historische state, live-sendcompatibiliteit en rollback. Ze zijn niet de standaardroute voor nieuwe v16 drafts en worden pas verwijderd na aantoonbare parity, callsite-cleanup en rollbackbewijs.

## Positieve replies

`scripts/outreach_reply_triage.py` kan replies adviserend classificeren, waaronder `positive_interest`, `question`, `not_interested`, referral en out-of-office. V16-doel na bewezen positieve reply:

1. Andrew informeren;
2. een kort vervolgconcept voorbereiden met het beloofde voorbeeld of één gerichte vervolgstap;
3. niet autonoom verzenden.

Zolang notificatie + vervolgconcept niet end-to-end met mailboxreadback zijn bewezen, blijft deze replyfase `not_fully_automated`.

## Live verzending blijft apart

Alle bestaande sender-readiness-, suppression-, compliance- en live-SMTP-gates blijven voor daadwerkelijke verzending gelden. Een goede prospect, publiek e-mailadres, draft of `manual_review` creëert nooit send permission.

## Evidencegrenzen

- Creator-/vendorcases zijn research/hypothese, geen prospect-specifiek bewijs.
- Verzin geen pijn, volume, omzet, besparing, ROI, reviews, namen of resultaten.
- Repositorytests bewijzen code/contracts; live Sheet- en mailboxwerking vereist aparte runtime/readback.
- Prospect-, campagne- en mailboxstate hoort niet als runtimewaarheid op `main`.
