# Actieve Leadscanner-scope (2026-11-20)

Deze scope is uitsluitend voor nieuwe Nederlandse lokale bedrijfsleads.

- Zoek afwisselend in passende branches en regio's met de daadwerkelijk aanwezige PDOK/Overture Maps-bronnen.
- Google Maps mag uitsluitend als een actuele geautoriseerde provider is geverifieerd; historische scraper-workflows zijn geen actieve installatie. Kaartdata zijn alleen zoekhints.
- Laad vóór een sitebezoek alle historische HMAC/V2, DedupeRegistry, LeadHistory, eerdere Approved, bounces, opt-outs en oude DraftQueue read-only. Match bedrijfsnaam, domein, e-mail en lead-ID; sla dubbelen over en zoek verder.
- Controleer naam, activiteit, regio, branche en exact algemeen zakelijk e-mailadres op de officiële bedrijfswebsite. Geen geraden of persoonlijke e-mailadressen.
- Bewaar alleen nieuwe geverifieerde leads atomair in privé Approved, WebsiteEvidence en LeadHistory, inclusief bewijsbron en datum. Controleer readback en opnieuw op dubbelen.
- Rapporteer complete alleen bij het exact gevraagde aantal en geldige readback; anders partial of blocked.
- Geen website-audits, websiteabonnementen, videoselectie, offertes, mailconcepten of verzending.

Deze scope verandert bestaande historische suppressies, registers en mailarchieven niet. Oude video-/auditcode is niet meer een actieve Leads-taak en kan apart worden uitgefaseerd na compatibiliteitstests.

## Veilig opgeschoond

De oude videokandidaten-handoff en de bijbehorende tests zijn verwijderd. Officiële websiteverificatie en de privé `WebsiteEvidence`-registratie blijven bewust behouden: ze zijn nodig om bedrijfsactiviteit en zakelijke e-mailadressen te bewijzen. De bestaande `fast-website-evidence`-workflow wordt niet verwijderd zonder bewijs dat actieve registraties en readback onaangetast blijven. Website-audits en verkoopadvies zijn geen onderdeel van de Leads-dienst.

## Losse hercontrole uitgefaseerd

De handmatig te starten GitHub Actions-workflow `fast-website-evidence.yml` is verwijderd, inclusief de historische Review450-trigger. De bestaande privegegevens blijven onaangeraakt. `scripts/fast_website_evidence.py` blijft als gedeelde module voor de verplichte verificatie en atomaire registratie in `Approved`, `WebsiteEvidence` en `LeadHistory`. Nieuwe leads blijven via de bestaande, geautoriseerde leadroute werken. Geen aparte website-auditdienst of hercontroleactie meer.
