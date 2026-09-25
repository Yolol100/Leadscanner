# Leadscanner

De standaardflow is compact:

**campagne -> Overture + Google Maps -> dedupe -> kandidatenbestand -> lichte verificatie/contactbasis -> korte Groeiabonnement-copy -> draft/export -> reactie**

## Groeiabonnement

De Leadscanner ondersteunt één product: **Groeiabonnement**, normaal **€200-€500 per maand afhankelijk van scope**.

De zes servicegebieden zijn:

1. website/webshop verbeteren;
2. zoekbaarheid verbeteren;
3. social content verzorgen;
4. geschikte repetitieve bedrijfsprocessen automatiseren, met een doel tot circa 30% waar aantoonbaar haalbaar en meetbaar, nooit als garantie;
5. hosting overnemen/beheren wanneer passend;
6. Andrew als vast contactpersoon voor aanpassingen en ondersteuning binnen afgesproken scope.

Een campagne gebruikt altijd één product en één primaire ingang:
`website_webshop`, `search_visibility`, `social_content`, `automation`, `hosting` of `fixed_contact`.

## Standaard: Leads Batch - Groeiabonnement

Open **Actions -> Leads Batch - Groeiabonnement -> Run workflow**.

Geef op:

- regio;
- branche/keywords;
- doel aantal kandidaten, maximaal 5.000 per run;
- Google Maps depth;
- primaire ingang;
- of de prijsrange al in de campagnepreview mag staan.

De workflow doet:

`PDOK -> Overture + gosom/google-maps-scraper:v1.18.1 -> cross-source dedupe -> growth-batch.csv/json`

De output is bewust alleen een **kandidaten- en campagnepreview**. Discovery levert geen contacttoestemming op, maakt geen geadresseerde mail en verzendt niets.

## Contactcontrole

Publieke zakelijke e-mailcontrole blijft een aparte begrensde stap via `scripts/extract_public_contacts.py`.

Grenzen:

- alleen de officiële bedrijfswebsite;
- maximaal 3 pagina's per site;
- maximaal 100 kandidaten per gecontroleerde run;
- geen geraden of geconstrueerde e-mailadressen;
- een gevonden e-mailadres zet `contact_basis_status` nooit automatisch op `pass`;
- zonder geldige contactbasis geen geadresseerde copy, DraftQueue of send.

## Copy

`scripts/prepare_growth_batch.py` gebruikt één Groeiabonnement en één primaire campagnehoek.

- ongeveer 50-90 woorden;
- één kleine CTA;
- geen volledige website-audit vóór first touch;
- geen verzonnen prospectproblemen of resultaten;
- prijsrange €200-€500 p/m alleen wanneer de campagne bewust price-led is.

## Na positieve interesse

Pas na een reactie of expliciete shortlist worden specialistische analyses gebruikt:

- Design/UX voor website of webshop;
- SEO/search voor vindbaarheid;
- social evidence voor social;
- automation/WordPress/Elementor/programmeren voor uitvoering;
- hostinganalyse wanneer overname relevant is.

De zware audits zijn dus niet verwijderd; ze zijn uit de standaard bulk-first-touchflow gehaald.

## Legacy/kleine routes

`Hybrid Maps Discovery` en `Overture keyless discovery` blijven beschikbaar voor kleine discoveryruns.

De bestaande mijn.host IMAP-route blijft alleen voor kleine/manual conceptflows. De repo bevat geen standaard automatische bulk-sendroute.

## Veiligheidsgrenzen

- discovery-hints zijn geen prospectbewijs of contacttoestemming;
- Google Maps e-mail-, telefoon-, social- en reviewvelden worden niet naar discovery-output doorgegeven;
- prospecttargets en mailboxbewijs horen niet in de default branch;
- geen automatische verzending;
- provider-, bounce-, suppression-, afmeld- en contactbasisregels mogen niet worden omzeild.
