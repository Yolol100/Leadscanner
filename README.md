# Leadscanner — bedrijfsresearch (geen e-mail)

De actieve repository zoekt en verifieert Nederlandse lokale bedrijven en officiële websitegegevens. E-mailconcepten, Mijn.Host, IMAP, SMTP, mailboxbruggen en verzendacties zijn buiten gebruik gesteld op 10 november 2026.

## Beschikbare acties

- `LEADS_CHAT_V1:CHECK`: volledige historische uitsluitingscontrole, inclusief HMAC, LeadHistory en legacy DraftQueue (alleen lezen).
- `LEADS_CHAT_V2:HINTS_10/30/50/100:r-<32hex>`: zoekhints naar privé Candidates.
- `LEADS_CHAT_V2:VERIFIED_100:r-<32hex>`: officiële bedrijfsverificatie naar privé Approved.
- `LEADS_CHAT_V2:EVIDENCE:r-<32hex>` en `REVIEW_EVIDENCE_1..5`: broncontrole van bestaande bedrijfswebsites.

Bestaande opt-outs, bounces, dedupe en historische conceptgegevens blijven behouden als read-only uitsluiting of archief. Bij ontbrekende suppressiegegevens stopt het onderzoek. Geen prospectinformatie in publieke commits of logs.

## Herstel

Alle oorspronkelijke code en documenten: [archiefbranch](../../tree/archive/pre-myhost-mail-cleanup-2026-11-10). Herstel niet automatisch en activeer geen mailfuncties zonder nieuwe expliciete opdracht.
## Optionele video-handoff (afzonderlijke Video Skill)

De bestaande Leads-commando's, historische uitsluitingen, privé Approved/WebsiteEvidence en research-only grens blijven **ongewijzigd**. Voor een door de eigenaar gekozen shortlist van maximaal vijf reeds geverifieerde bedrijven kan een offline `scripts/video_candidate_handoff.py` de **private** bewijsexport gebruiken:

`python3 scripts/video_candidate_handoff.py --input /private/verified-video-candidates.json --output /private/video-review.json --limit 5`

Het bestand bevat reeds geselecteerde, door Leads geverifieerde records en aantoonbare public-site observaties (`verification_status`, `historical_suppression_checked`, `suppressed`, `local_business_fit`, `observations` met `source_url`, `verified`, `privacy_safe`, `observed_at`, `method`, `kind` en `finding`). De code maakt geen nieuwe leads, doet geen websiteverzoeken, toont geen privé-e-mailadressen in output, verzendt geen mails en schrijft geen GitHub-artefacten. Het resultaat is uitsluitend een **interne Video-reviewsuggestie**: geen bewezen SEO- of conversieresultaat en geen marketingtoestemming. Videobewijs, scènes, scripts en e-mailrecht worden afzonderlijk beoordeeld door de nieuwe `video`-skill en `webactueel-workflow`.

Het uitvoerbestand moet buiten de publieke repository blijven. Er worden geen GitHub Actions, cronjobs, mailcommando's of werkende scripts verwijderd of gewijzigd. Test met `python3 -m unittest discover -s tests -p 'test_video_candidate_handoff.py'`.
