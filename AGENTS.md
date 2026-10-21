# Leadscanner — vier stappen

Volg [README.md](README.md) en de actuele Leads Skill voor branchemapping, het enige actieve gewone feitelijke first-touch-sjabloon en de vierstappenworkflow. De zes oude commerciële branchemails zijn vervallen en mogen niet worden hergebruikt.

1. Zoek lokale Nederlandse vakbedrijven; Overture/PDOK is uitsluitend kandidaatbewijs.
2. Verifieer de officiële website; kies eerst een aantoonbaar genoemde contactpersoon met gepubliceerd zakelijk e-mailadres, anders één gepubliceerd `info@`/`contact@`-adres.
3. Controleer historische dedupe/opt-out; vul alle placeholders in en sla maximaal 100 concepten via privé Draft Queue en IMAP `\\Draft` op, met exacte readback.
4. Stop voor menselijke beoordeling. Geen automatische verzending.

Nooit prospectgegevens in publieke GitHub-inhoud. Geen CRM, audits, scores, campagnes, tracking, follow-ups of SMTP. Stop bij ontbrekend bronbewijs of een onbetrouwbare register-/Drafts-readback.


## Brononderzoek zonder dubbele zoekactie

Als website + bedrijf al in de privé `Approved`- of `Review450`-bron staan, gebruik de optionele `fast-website-evidence.yml`-researchroute voor een nieuwe, brongebonden controle en hergebruik recent gecontroleerde records. Gebruik geen browser-search/Google als standaard voor reeds bekende officiële URL's. `WebsiteEvidence` bevat tekstvermeldingen, geen bewezen ontbreken of werking van websitefuncties. De bestaande vier stappen, historische dedupe, privacy, Mijn.Host-readback en menselijke eindcontrole blijven leidend. Verwijder tijdelijke 450-scripts pas na afsluiting van de aparte 450-taak.


### Alleen op aanvraag: ChatGPT-commandokanaal

Leadscanner wordt uitsluitend op aanvraag gestart. Geen `schedule`/cron of automatische eerste concepten. Geplande eerste-conceptautomatisering is verwijderd; voeg geen scheduler toe.

Via bestaand issue #1720 accepteert `leads_chat_command.py` vaste eigenaargeautoriseerde commando's. `REVIEW_EVIDENCE_1` tot `REVIEW_EVIDENCE_5` worden via `LEADS_CHAT_V2:<MODE>:r-<32hex>` individueel op aanvraag gestart: vijf batches van maximaal 100 officiële websites uit het bestaande privé-Review450, uitsluitend naar WebsiteEvidence, zonder mailboxwijzigingen of automatische verzending. Een groen resultaat is alleen bronbewijs, geen toestemming om geblokkeerde bedrijven te benaderen. Alleen read-only `LEADS_CHAT_V1:CHECK` (volledige historische/HMAC, LeadHistory en DraftQueue) en `LEADS_CHAT_V1:DRAFTS_AUDIT` (Mijn.Host alleen lezen) behouden V1. Zoekopdrachten `HINTS_10/30/50/100`, `EVIDENCE` en `VERIFIED_100` vereisen `LEADS_CHAT_V2:<MODE>:r-<32hex>` met één cryptografisch willekeurig, daarna stabiel opdracht-ID. Herhaling van hetzelfde ID of GitHub-rerun start geen tweede scan; conflicterend hergebruik blokkeert. `Candidates` bevat alleen ongeverifieerde hints met exacte `GITHUB_RUN_ID` en privé-readback; geen bedrijfsdata in GitHub-issues of logs. Gebruik de nieuwe V2-ID niet om een nog lopende of onbewerkte opdracht dubbel uit te voeren.

Alleen geverifieerde, menselijk beoordeelde nieuwe leads mogen via het afzonderlijke opaque-ID-commandokanaal #1659 in Mijn.Host Drafts worden geplaatst. Oude concepten, 450-review en historische uitsluitingen niet stil wijzigen. Nooit SMTP, mail verzenden of nieuwe tijdschema's aanzetten. Webactueel-workflow blijft procescontroller en Leads Skill eigenaar.

## Tweede commercieel sjabloon: alleen buiten de huidige writer

De Leads Skill bevat een **apart generiek websiteabonnementen-sjabloon B** voor een aantoonbaar rechtmatig reclamecontact of een daadwerkelijk toepasselijke bestaande-klantuitzondering. De aanbieding noemt EUR 0 opstartkosten, Website EUR 75/maand, Webshop EUR 125/maand en begrensd maatwerk EUR 250/maand exclusief btw; externe hosting-, domein-, licentie- en betaalproviderkosten komen apart voor rekening van de klant. De voorgestelde eerste B2B-periode is 12 maanden, nog onderhevig aan juridische controle. Zeg niet dat de hele website gratis is.

**B is niet in deze repository als geautoriseerde mailmodus geïmplementeerd:** short_email_policy.py en de huidige Draft Queue/IMAP-writer blijven uitsluitend sjabloon A ondersteunen. Gebruik B niet in bestaande issues, DraftQueue, huidige Mijn.Host-Drafts, bulkverzendingen, SMTP, campagnes of automatische vervolgmails. Een gecontroleerde aparte privacy-/toestemmingsroute, juridische beoordeling en expliciete eigenaarstoestemming zijn vereist voordat er ooit een live B-integratie kan worden gebouwd. Bewaar historische lead-/mailboxbewijzen, alle HMAC-suppressie-, bounce- en opt-out-registraties en bijbehorende veiligheidsregressietests; verwijderen van de zes oude **actieve** verkoopvarianten betekent niet verwijderen van die historische gegevens.
