# Leadscanner — vier stappen

1. **Bedrijf:** vind een lokaal Nederlands vakbedrijf; verifieer branche en officiële website.
2. **Contact:** zoek eerst een genoemde eigenaar/contactpersoon met expliciet gepubliceerd zakelijk adres; anders één officieel `info@`- of `contact@`-adres. Raad nooit een adres.
3. **Concept:** kies één van zes vaste branchemails, vul placeholders in en sla via privé Draft Queue en IMAP `\\Draft` op in Mijn.Host, met exacte readback.
4. **Controle:** de mens beoordeelt adres, claims en verzendrecht; nooit automatisch verzenden.

**Beveiliging:** Overture/PDOK levert eerst onbetrouwbare bedrijfshints. Alleen expliciet geverifieerde bedrijfscontacten worden apart in het privé Approved-tabblad opgeslagen. Historische dedupe, bounces en opt-outs blokkeren contact. GitHub bevat uitsluitend anonieme aantallen en willekeurige draft-ID's; nooit bedrijfs- of e-mailgegevens. Geen SMTP, websitescan, score, CRM, tracking, campagne of follow-up. Tot 100 aangevraagde Draft-ID's per batch; ongeldige, reeds uitgesloten en dubbele bedrijven worden per kandidaat overgeslagen. GitHub rapporteert alleen aantallen (aangevraagd, opgeslagen, overgeslagen), zonder persoonsgegevens. Het volledige historische register en HMAC blijven verplicht; een ontbrekend ID, corrupt register of IMAP/readback-fout stopt de run. Eén Sheets-read, register-read en IMAP-sessie, met exacte readback per opgeslagen concept.

**Snelste veilige bulkroute:** kies `Fresh Leads > fill_100` om maximaal 100 nieuwe bedrijven automatisch te vinden en op hun officiële website te verifiëren; de volledige historische/HMAC-uitsluiting blijft verplicht. De privé-tab `Approved` bevat uitsluitend bevestigde bedrijven; bij onvoldoende bewijs of uitgeputte bronnen meldt de run `partial`. Voor alleen onbevestigde Overture-hints blijft `discover` beschikbaar. Maak na menselijke broncontrole maximaal 100 concepten aan met één `LEADS_DRAFT_BATCH_ONLY` en exacte Mijn.Host-readback. Ongeldige, uitgesloten of dubbele bedrijven worden individueel overgeslagen; ontbrekende Draft-ID's, registerstoringen en IMAP-fouten stoppen veilig. Geen automatische verzending.

**Geautoriseerde trigger:** GitHub-issue [#1659](https://github.com/Yolol100/Leadscanner/issues/1659), uitsluitend:
- `LEADS_DRAFT_ONLY: draft-<32hex>`
- `LEADS_DRAFT_BATCH_ONLY: draft-<32hex>,draft-<32hex>,...` (2–100 ID's)

Een gepubliceerd adres bewijst geen recht op ongevraagde commerciële e-mail. Controleer [Telecommunicatiewet art. 11.7](https://wetten.overheid.nl/BWBR0009950) en [ACM](https://www.acm.nl/nl/telecom/zakelijk-abonnement-voor-bellen-en-internet/spam).


## Sneller bedrijfsonderzoek (optioneel)

Gebruik **geen aparte Google-zoekopdracht per bekende bedrijfswebsite**. `fresh-leads.yml` vindt kandidaten al met Overture/PDOK en controleert de officiële website met een begrensde parallelle HTTP-verifier. Na die verificatie kan `.github/workflows/fast-website-evidence.yml` maximaal 100 bestaande privé-leads tegelijk voorzien van broncitaten en hints over reeds genoemde sitefuncties. Het resultaat wordt uitsluitend teruggelezen uit `WebsiteEvidence` in het bestaande privé Sheet; hergebruik gecontroleerde records tot 24 uur. Onzekerheden of een afwijkend e-maildomein blijven handmatig te controleren.

De automatische mail-/IMAP-route verandert niet. De oude 450-taakscripts blijven bestaan zolang de afzonderlijke 450-chat actief is. Zie [opschoningsbesluit en gebruik](docs/leadscanner-cleanup-and-speed.md). De apart bestaande `browser-search`-repository is alleen een optionele zoekhulp, geen officiële bedrijfsverificatie.


### Automatische éénpass-route (15 oktober 2026)

- **Maandag 06:23 UTC:** bestaande `fresh-leads.yml` zoekt en verifieert maximaal 100 nieuwe bedrijven, met maximaal 240 officiële websitecontroles. De historische deduplicatie blijft verplicht.
- **Tijdens diezelfde verificatie** wordt de reeds gelezen officiële pagina direct in het bestaande privé Sheet als `WebsiteEvidence` opgeslagen; geen tweede site-fetch.
- **Maandag–vrijdag 07:17 UTC:** dezelfde privébron wordt met een 24-uurscache opnieuw gecontroleerd wanneer verouderd. Bronpassages en functie-vermeldingen zijn hints, geen bewezen ontbrekende features.
- **Geen automatisch verzenden of aanpassen van de 450-mails**. Het maken van commerciële tekst/Mijn.Host-concepten behoudt de bestaande geautoriseerde Draft Queue en menselijke eindcontrole.
- GitHub meldt alleen aantallen en webcontrole-latentie, geen prospectgegevens. Zie [precieze veiligheids- en terugvalvoorwaarden](docs/leadscanner-cleanup-and-speed.md).
