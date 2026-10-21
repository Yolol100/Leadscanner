# Leadscanner — vier stappen

**Actuele bediening sinds 16 oktober 2026:** uitsluitend via eigenaargeautoriseerde, handmatige ChatGPT-opdrachten op [issue #1720](https://github.com/Yolol100/Leadscanner/issues/1720). `LEADS_CHAT_V1:CHECK` en `LEADS_CHAT_V1:DRAFTS_AUDIT` blijven read-only. Zoek- en website-evidence-opdrachten vereisen `LEADS_CHAT_V2:<MODE>:r-<32hex>`; kies alleen `HINTS_10`, `HINTS_30`, `HINTS_50`, `HINTS_100`, `VERIFIED_100` of `EVIDENCE` als MODE. Hergebruik hetzelfde willekeurige ID bij retry; een duplicate is een no-op. De oude `schedule`/cron en automatische eerste-conceptroute zijn via [PR #1719](https://github.com/Yolol100/Leadscanner/pull/1719) verwijderd. Zonder volledige historische/HMAC-, LeadHistory- en DraftQueue-check geen scan. Nooit automatisch verzenden.

1. **Bedrijf:** vind een lokaal Nederlands vakbedrijf; verifieer branche en officiële website.
2. **Contact:** zoek eerst een genoemde eigenaar/contactpersoon met expliciet gepubliceerd zakelijk adres; anders één officieel `info@`- of `contact@`-adres. Raad nooit een adres.
3. **Concept:** gebruik voor alle NIEUWE gewone leads uitsluitend de korte feitelijke mail: `Goedendag,` + `Ik zag dat ...` + `Zou het handig zijn als ...?` + vaste afmeldzin + `Groet, Andrew`. Onderwerp kort en neutraal; geen verkoop-/social-voorbeeldpitch. Bewijs de observatie op een officiële bedrijfsbron, controleer volledige historische uitsluitingen en sla alleen via privé Draft Queue en IMAP `\\Draft` met exacte readback op. Geen verzending.
4. **Controle:** de mens beoordeelt adres, claims en verzendrecht; nooit automatisch verzenden.

**Apart concept B:** de letterlijke eigenaarstekst staat uitsluitend in de [actuele Leads-projectbron](https://drive.google.com/file/d/1gb_ThUS2nkKmTO-bn8UFRz2kTzfIu5cE/view). Alleen op expliciet verzoek tonen. Dit is geen nieuwe writer-, concept-, mail- of campagnemodus. Verplichte maandkosten en reclamespecifieke toestemming moeten vóór werkelijk gebruik juridisch worden getoetst.

**Sjabloonbeleid (nieuwe concepten):** de zes oude brancheteksten zijn niet langer geldige invoer voor nieuwe Mijn.Host-drafts. De schrijfroute weigert oude tekststructuren. Historische 450-reviewcode en reeds opgeslagen concepten blijven voor herkenning/controle intact; dit is geen bulkvervanging, geen opdracht om archieven te wissen en geen automatische mailverzending. De controle op officiële bron, privéhistorie/HMAC en de menselijke eindcheck blijft van kracht.

**Beveiliging:** Overture/PDOK levert eerst onbetrouwbare bedrijfshints. Alleen expliciet geverifieerde bedrijfscontacten worden apart in het privé Approved-tabblad opgeslagen. Historische dedupe, bounces en opt-outs blokkeren contact. GitHub bevat uitsluitend anonieme aantallen en willekeurige draft-ID's; nooit bedrijfs- of e-mailgegevens. Geen SMTP, CRM, tracking, campagne of follow-up. Voor gewone leads geen uitgebreide websiteaudit of algemene leadscore; hoogstens vijf apart geselecteerde, geverifieerde videokandidaten mogen later een diepgaande audit en interne videoscore krijgen. De video-uitbreiding in [PR #1757](https://github.com/Yolol100/Leadscanner/pull/1757) is nog niet actief. Tot 100 aangevraagde Draft-ID's per batch; ongeldige, reeds uitgesloten en dubbele bedrijven worden per kandidaat overgeslagen. GitHub rapporteert alleen aantallen (aangevraagd, opgeslagen, overgeslagen), zonder persoonsgegevens. Het volledige historische register en HMAC blijven verplicht; een ontbrekend ID, corrupt register of IMAP/readback-fout stopt de run. Eén Sheets-read, register-read en IMAP-sessie, met exacte readback per opgeslagen concept.

**Snelste veilige bulkroute:** gebruik de bestaande ChatGPT-opdracht `LEADS_CHAT_V2:VERIFIED_100:r-<32hex>` (geen handmatige workflow-start nodig) in plaats van `Fresh Leads > fill_100` om maximaal 100 nieuwe bedrijven automatisch te vinden en op hun officiële website te verifiëren; de volledige historische/HMAC-uitsluiting blijft verplicht. De privé-tab `Approved` bevat uitsluitend bevestigde bedrijven; bij onvoldoende bewijs of uitgeputte bronnen meldt de run `partial`. Voor alleen onbevestigde Overture-hints blijft `discover` beschikbaar. Maak na menselijke broncontrole maximaal 100 concepten aan met één `LEADS_DRAFT_BATCH_ONLY` en exacte Mijn.Host-readback. Ongeldige, uitgesloten of dubbele bedrijven worden individueel overgeslagen; ontbrekende Draft-ID's, registerstoringen en IMAP-fouten stoppen veilig. Geen automatische verzending.

**Geautoriseerde trigger:** GitHub-issue [#1659](https://github.com/Yolol100/Leadscanner/issues/1659), uitsluitend:
- `LEADS_DRAFT_ONLY: draft-<32hex>`
- `LEADS_DRAFT_BATCH_ONLY: draft-<32hex>,draft-<32hex>,...` (2–100 ID's)

Een gepubliceerd adres bewijst geen recht op ongevraagde commerciële e-mail. Controleer [Telecommunicatiewet art. 11.7](https://wetten.overheid.nl/BWBR0009950) en [ACM](https://www.acm.nl/nl/telecom/zakelijk-abonnement-voor-bellen-en-internet/spam).


## Sneller bedrijfsonderzoek (optioneel)

Gebruik **geen aparte Google-zoekopdracht per bekende bedrijfswebsite**. `fresh-leads.yml` vindt kandidaten al met Overture/PDOK en controleert de officiële website met een begrensde parallelle HTTP-verifier. Na die verificatie kan `.github/workflows/fast-website-evidence.yml` maximaal 100 bestaande privé-leads tegelijk voorzien van broncitaten en hints over reeds genoemde sitefuncties. Het resultaat wordt uitsluitend teruggelezen uit `WebsiteEvidence` in het bestaande privé Sheet; hergebruik gecontroleerde records tot 24 uur. Onzekerheden of een afwijkend e-maildomein blijven handmatig te controleren.

De bestaande uitsluitend op aanvraag te starten mailconcept-/IMAP-route verandert niet. De oude 450-taakscripts blijven bestaan zolang de afzonderlijke 450-chat actief is. De apart bestaande `browser-search`-repository is alleen een optionele zoekhulp, geen officiële bedrijfsverificatie.


