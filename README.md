# Leadscanner — nieuwe bedrijfshints

Deze **publieke** repo zoekt met Overture Maps/PDOK naar Nederlandse bedrijfshints en verwijdert historische dubbelen. Een hint is **geen geverifieerde lead**. Er worden geen e-mails gezocht, opgeslagen, opgesteld of verzonden in GitHub.

## Uitvoering

1. Lees eerst het **volledige** bestaande Lead Dedupe Registry, inclusief eerdere contacten, bounces, opt-outs en de onafhankelijke HistoricalHmacV2-controle. Ontbreekt iets? **Stop**.
2. Zoek bedrijfshints via de handmatige GitHub Actions-workflow **Fresh Leads** (regio, branche, limiet). `Nederland` betekent 12 regionale steekproeven, **geen** landelijke dekking.
3. Filter historische matches en nieuwe dubbelen. Publieke logs en artifacts bevatten **alleen tellingen**, nooit bedrijfsnamen, domeinen, e-mailadressen, concepten of geheimen.

Voor een geautoriseerde ChatGPT GitHub-connector zonder `workflow_dispatch` zijn uitsluitend de bestaande gecontroleerde commit-markers beschikbaar: `LEADS_PREFLIGHT_ONLY:` of `LEADS_DISCOVERY_ONLY: <regio>|<branches>|<limiet>`.

## Overdracht aan de Leads Skill

De **vier stappen** blijven: **bedrijf vinden → op officiële website één algemeen contactadres en het doel ervan verifiëren → privé een kort concept maken → handmatig beoordelen**. De Skill verifieert daarnaast rechtsvorm (bij voorkeur BV/NV, **niet** afleiden uit de bedrijfsnaam), actuele registeruitsluiting en aantoonbare wettelijke contactbasis. Een openbaar `info@`-adres is **geen toestemming**. Bij twijfel is een concept **niet verzendklaar**. Alleen een mens beslist later afzonderlijk over een rechtmatig bericht.

**Niet terugbrengen:** website-audits, 3–6 problemen, scores, CRM-exports, SMTP/IMAP, mailboxconcepten, automatische follow-ups, tracking of legacy campagnes. Geen nieuwe persoonsgegevens in publieke commits.

Het bestaande uitsluitingsregister, de privé-HMAC-sleutelkluis, externe herstelkopieën en de rollbackgeschiedenis blijven **ongewijzigd**. Geen wijzigingen aan broncode of uitsluitingsgegevens bij documentatie-opschoning.

Wetgeving: [Telecommunicatiewet art. 11.7](https://wetten.overheid.nl/BWBR0009950/2026-07-01) en [ACM spamregels](https://www.acm.nl/nl/verkoop-aan-consumenten/reclame-en-verleiden/spam-voorkomen-uw-reclame).
