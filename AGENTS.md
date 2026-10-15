# Leadscanner — vier stappen

Volg [README.md](README.md) en de actieve Leads Skill voor branchemapping, zes vaste mails en vierstappenworkflow.

1. Zoek lokale Nederlandse vakbedrijven; Overture/PDOK is uitsluitend kandidaatbewijs.
2. Verifieer de officiële website; kies eerst een aantoonbaar genoemde contactpersoon met gepubliceerd zakelijk e-mailadres, anders één gepubliceerd `info@`/`contact@`-adres.
3. Controleer historische dedupe/opt-out; vul alle placeholders in en sla maximaal 100 concepten via privé Draft Queue en IMAP `\\Draft` op, met exacte readback.
4. Stop voor menselijke beoordeling. Geen automatische verzending.

Nooit prospectgegevens in publieke GitHub-inhoud. Geen CRM, audits, scores, campagnes, tracking, follow-ups of SMTP. Stop bij ontbrekend bronbewijs of een onbetrouwbare register-/Drafts-readback.


## Brononderzoek zonder dubbele zoekactie

Als website + bedrijf al in de privé `Approved`- of `Review450`-bron staan, gebruik de optionele `fast-website-evidence.yml`-researchroute voor een nieuwe, brongebonden controle en hergebruik recent gecontroleerde records. Gebruik geen browser-search/Google als standaard voor reeds bekende officiële URL's. `WebsiteEvidence` bevat tekstvermeldingen, geen bewezen ontbreken of werking van websitefuncties. De bestaande vier stappen, historische dedupe, privacy, Mijn.Host-readback en menselijke eindcontrole blijven leidend. Verwijder tijdelijke 450-scripts pas na afsluiting van de aparte 450-taak.


### Automatische onderzoeksroute, zonder mailautomatisering

De geplande weekrun van `fresh-leads.yml` gebruikt het bestaande HMAC-/historische uitsluitingsregister vóór alle HTTP-aanvragen en maximaal 240 sitecontroles. Bij succesvolle verificatie worden de al gelezen pagina's eenmalig intern doorgegeven aan `WebsiteEvidence`; op werkdagen hergebruikt `fast-website-evidence.yml` de 24-uurscache. De route bewaart uitsluitend bronfeiten in het privé Sheet, doet geen SMTP/IMAP-writes en is geen vervanging voor de geautoriseerde Draft Queue, vierstappen-Leads-Skill of menselijke controle. De 450-mailworkflow blijft onaangetast.

### Geplande eerste concepten (nieuwe leads, streng begrensd)
De wekelijkse `auto_first_drafts`-job mag alleen werken op `Approved`-records met `run_id == GITHUB_RUN_ID`, bevestigde historische bronregistratie, een recent en exact gekoppeld `WebsiteEvidence`-detail, gelijk e-maildomein en een factueel passende branchecluster. Maximaal 25 nieuwe Mijn.Host IMAP-`\\Draft`-concepten per run; geen SMTP of uitgaande verzending. Hergebruik bij retry de al privé opgeslagen AutoDraftState-IDs en controleer de bestaande Draft Queue/HMAC-uitsluitingen opnieuw. Bewaar uitsluitend privacyveilige aantallen in GitHub-log. De lopende Review450 en eerdere mailboxconcepten zijn strikt read-only. De mens beoordeelt ieder concept vóór een eventuele handmatige verzending. Verdere voorwaarden: `docs/leadscanner-cleanup-and-speed.md`.
