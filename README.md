# Leadscanner — uitsluitend nieuwe Nederlandse bedrijfsleads

De actieve repository zoekt passende Nederlandse lokale bedrijven in verschillende branches en regio's, verifieert hun bedrijfsactiviteiten en exacte algemene zakelijke e-mail op de officiële website, voorkomt herhaalde leads en bewaart uitsluitend nieuwe geverifieerde records in het bestaande privéregister.

## Werkwijze

1. **Zoeken:** gebruik de huidige PDOK/Overture Maps-discovery voor lokale bedrijven; roteer branches en regio's. Google Maps is alleen toegestaan als een werkelijk aanwezige en geautoriseerde provider is vastgesteld. De historische Maps-scraper/hybride workflow is niet actief op de huidige `main`. `overturemaps` is geen Google Maps-installatie.
2. **Ontdubbelen:** controleer vooraf alle historische HMAC/V2, DedupeRegistry, LeadHistory, eerder opgeslagen bedrijven, opt-outs, bounces en oude DraftQueue, uitsluitend read-only. Match naam, domein, e-mail en lead-ID. Eerder gevonden? Overslaan en een andere kandidaat zoeken.
3. **Verifiëren:** officiële site bevestigt lokale activiteit, branche, identiteit en exact publiek vermeld algemeen zakelijk e-mailadres. Maps/Overture zijn uitsluitend zoekhints, geen zelfstandig bewijs.
4. **Opslaan:** alleen unieke geverifieerde bedrijven atomair in privé `Approved`, `WebsiteEvidence` en `LeadHistory`, met bewijsbron en controledatum. Controleer readback en tel alleen nieuwe `verified_*` records.

`complete` alleen bij exact doel en geslaagde privé-readback; anders `partial` of `blocked` met reden. Geen website-audits, video-handoff, websiteabonnementen, offertes, mailconcepten of verzending. Bewaar oude uitsluitingen en herstelarchieven; geen privécontactdata in GitHub.

## Huidige eigenaargeautoriseerde uitvoering

- `LEADS_CHAT_V1:CHECK`: historische uitsluitingen controleren.
- `LEADS_CHAT_V2:HINTS_10/30/50/100:r-<32hex>`: nieuwe hints privé opslaan.
- `LEADS_CHAT_V2:VERIFIED_100:r-<32hex>` en `VERIFIED_GOAL_<1..1000>`: begrensd verifiëren en opslaan volgens bestaande runtimecontracten.

Historische extra scripts kunnen nog in de codebasis staan voor compatibiliteit, maar vallen buiten de actieve Leads-dienst. Geen automatische runs of campagnes.
