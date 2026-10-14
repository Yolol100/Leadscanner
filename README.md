# Leadscanner — vier stappen

1. **Bedrijf zoeken:** Nederlandse lokale vakbedrijven, geen marketing/web/IT/consultancy.
2. **E-mail zoeken:** één exact gepubliceerd algemeen adres op de officiële bedrijfswebsite.
3. **Mijn.Host-concept maken:** korte vaste mail; via IMAP naar Drafts, met readback.
4. **Menselijke controle:** de gebruiker beslist zelf of hij ooit verzendt.

Techniek: Overture/PDOK levert hints die alleen in een privé Candidates-overdrachtsblad komen; het historische uitsluitingsregister blokkeert dubbelen en eerdere contacten. Een prospect is pas geschikt na officiële website- en e-mailverificatie. De privé Google Draft Queue bewaart tekst en ontvangers; **GitHub krijgt uitsluitend willekeurige draft-ID's**. Eén geautoriseerde trigger ondersteunt één ID of een batch van maximaal 100 ID's. Batch hergebruikt één Sheets-read, één register-read en één IMAP-verbinding. Elke mail wordt individueel teruggelezen en blijft concept. Geen SMTP, verzending, tracking, follow-up, campagnes, websitescans of scores.

Trigger via issue #1659:
- `LEADS_DRAFT_ONLY: draft-<32hex>`
- `LEADS_DRAFT_BATCH_ONLY: draft-<32hex>,draft-<32hex>,...` (2–100 verschillende ID's)

De privacy- en broncontrole blijft verplicht; openbare logs bevatten uitsluitend aantallen. Een gepubliceerd adres is geen automatische toestemming voor commerciële verzending.

Bronnen: [Telecommunicatiewet art. 11.7](https://wetten.overheid.nl/BWBR0009950) en [ACM](https://www.acm.nl/nl/telecom/zakelijk-abonnement-voor-bellen-en-internet/spam).
