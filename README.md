# Leadscanner — vier stappen

1. **Bedrijf:** vind een lokaal Nederlands vakbedrijf; verifieer branche en officiële website.
2. **Contact:** zoek eerst een genoemde eigenaar/contactpersoon met expliciet gepubliceerd zakelijk adres; anders één officieel `info@`- of `contact@`-adres. Raad nooit een adres.
3. **Concept:** kies één van zes vaste branchemails, vul placeholders in en sla via privé Draft Queue en IMAP `\\Draft` op in Mijn.Host, met exacte readback.
4. **Controle:** de mens beoordeelt adres, claims en verzendrecht; nooit automatisch verzenden.

**Beveiliging:** Overture/PDOK levert uitsluitend onverifieerde bedrijfshints via het privé Candidates-blad. Historische dedupe, bounces en opt-outs blokkeren contact. GitHub bevat uitsluitend anonieme aantallen en willekeurige draft-ID's; nooit bedrijfs- of e-mailgegevens. Geen SMTP, websitescan, score, CRM, tracking, campagne of follow-up. Tot 100 aangevraagde Draft-ID's per batch; ongeldige, reeds uitgesloten en dubbele bedrijven worden per kandidaat overgeslagen. GitHub rapporteert alleen aantallen (aangevraagd, opgeslagen, overgeslagen), zonder persoonsgegevens. Het volledige historische register en HMAC blijven verplicht; een ontbrekend ID, corrupt register of IMAP/readback-fout stopt de run. Eén Sheets-read, register-read en IMAP-sessie, met exacte readback per opgeslagen concept.

**Snelste veilige bulkroute:** start de bestaande GitHub Actions-workflow `Fresh Leads` met `execution_mode=discover` (tot 100 **onbevestigde** bedrijfshints per run in het privé Candidates-blad). Verifieer per bedrijf de officiële website, branche en het daar gepubliceerde zakelijke adres, en toets daarna de **volledige** historische uitsluitingslijst inclusief HMAC vóór het schrijven naar de privé Draft Queue. Vul de selectie zo nodig vanuit een volgende discovery-run aan tot 50 **echt geverifieerde** bedrijven. Trigger vervolgens bij voorkeur **één** `LEADS_DRAFT_BATCH_ONLY` met 2–100 unieke, anonieme IDs en wacht op `MYHOST_DRAFT=green`. Een ongeldige of uitgesloten kandidaat kan nog steeds de volledige batch veilig blokkeren; herstel dan alleen de getroffen privé-queue-items en probeer dezelfde IDs opnieuw (idempotent), nooit uitsluitingen omzeilen. De GitHub-wachtrij behoudt nu wachtende runs, maar losse overlappende triggers blijven onnodig traag. Geen verzending.

**Geautoriseerde trigger:** GitHub-issue [#1659](https://github.com/Yolol100/Leadscanner/issues/1659), uitsluitend:
- `LEADS_DRAFT_ONLY: draft-<32hex>`
- `LEADS_DRAFT_BATCH_ONLY: draft-<32hex>,draft-<32hex>,...` (2–100 ID's)

Een gepubliceerd adres bewijst geen recht op ongevraagde commerciële e-mail. Controleer [Telecommunicatiewet art. 11.7](https://wetten.overheid.nl/BWBR0009950) en [ACM](https://www.acm.nl/nl/telecom/zakelijk-abonnement-voor-bellen-en-internet/spam).
