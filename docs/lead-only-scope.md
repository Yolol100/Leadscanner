# Leadscanner: een zoek- en controlecontract

Dit is de enige actuele werkwijze voor de repository. README en de Leads-skill verwijzen hiernaar. Historische bron- en suppressiedata blijven behouden.

## Zoekregels
1. Gebruik de bestaande **PDOK + Overture Maps**-discovery. Wissel toegestane Nederlandse branches en regio's af. Een bronhint is nog geen goedgekeurde lead.
2. Lees **voor elk websitebezoek** het complete historische HMAC/V2-, DedupeRegistry-, LeadHistory-, Approved-, bounce-, opt-out- en DraftQueue-uitsluitingsbeeld read-only. Onvolledig = blocked. Sla bestaande bedrijven op naam, domein, e-mail of ID over.
3. Filter ontbrekende bedrijfsnaam, officiële website, passende branche of regio al **voor** HTTP-verificatie. Dedupliceer dezelfde domeinen in geheugen en controleer bedrijven met de bestaande begrensde parallelle workers.
4. Bezoek uitsluitend de officiële site voor bewijs van actieve lokale activiteit en het **exact gepubliceerde algemene zakelijke e-mailadres**. Geen gegokte of persoonlijke e-mails. Een tijdelijke websitefout betekent niet dat een bedrijf gesloten is.
5. Sla alleen nieuwe, bewezen leads **atomair** in privé `Approved`, `WebsiteEvidence` en `LeadHistory` op. Lees terug en tel uitsluitend `verified_with_detail` of `verified_activity_only`. Geen publieke bedrijfsidentiteiten in GitHub.
6. Geef `complete` alleen bij het gevraagde aantal én succesvolle privé-readback; anders `partial` of `blocked` met reden. Geen e-mails, drafts, video, website-audits of abonnementen.

## Snelheid zonder kwaliteitsverlies
- Behoud de bestaande bronproviders, één workerpool, in-memory domeinfilter, branche-rotatie, korte batches, websitebewijs uit één bezoek en vroeg stoppen bij doel.
- Vermijd dubbel classificeren van dezelfde bronhint. Houd bestaande veiligheids- en verificatiestappen intact; voeg geen nieuwe meetvelden of netwerkverzoeken toe.
- Voeg **geen per-bedrijf kwaliteitsscore** of geplande hercontrole toe: beide zijn buiten scope en een score zou extra berekeningen/risico op verkeerde afwijzing toevoegen. Bestaande verificatiestatus is de kwaliteitsgrens.
- Het bestaande anonieme resultaat telt bronhints, bezochte sites, dubbelen, eerder gebruikte leads, onbewezen leads en goedgekeurde leads. Dit is het overzicht van **hoe leads worden gevonden**, niet Google Maps-data.
- Verwijder historische registers of compatibiliteitscode nooit alleen vanwege de naam; eerst aantonen dat de huidige code en tests ze niet nodig hebben.

## Niet-actief
Geen aparte website-hercontroleworkflow, video-handoff, verkoopmateriaal, mailconcepten of verzending. Oude privégeschiedenis blijft beschikbaar voor uitsluiting. Google Maps is geen geverifieerde actieve provider; PDOK en Overture Maps blijven de huidige bronnen.
