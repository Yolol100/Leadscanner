# Leadscanner

De standaardflow is:

**campagne -> PDOK + Overture + Google Maps -> dedupe -> kandidaten -> minimale verificatie/contactbasis -> korte Groeiabonnement-copy -> export -> reactie**

## Groeiabonnement

Er is één product: **Groeiabonnement**, normaal **€200-€500 per maand afhankelijk van scope**.

De zes servicegebieden:

1. website/webshop verbeteren;
2. zoekbaarheid verbeteren;
3. social content verzorgen;
4. geschikte repetitieve werkzaamheden automatiseren, met een doel tot circa 30% waar aantoonbaar haalbaar en meetbaar;
5. hosting overnemen/beheren wanneer passend;
6. Andrew als vast contactpersoon voor aanpassingen en ondersteuning.

Een campagne kiest één primaire ingang: `website_webshop`, `search_visibility`, `social_content`, `automation`, `hosting` of `fixed_contact`.

## Enige standaardworkflow

Open **Actions -> Leads Batch - Groeiabonnement -> Run workflow**.

Input:

- regio;
- branche/keywords;
- maximaal 5.000 kandidaten;
- Google Maps depth;
- primaire ingang;
- prijsrange tonen ja/nee.

Technische route:

`PDOK -> Overture Maps Places + gosom/google-maps-scraper:v1.18.1 -> cross-source dedupe -> growth-batch.csv/json`

Discovery maakt geen contacttoestemming en verzendt niets.

## Contactcontrole

`scripts/extract_public_contacts.py` is een aparte, begrensde capability:

- alleen officiële bedrijfswebsite;
- maximaal 3 pagina's per site;
- maximaal 100 kandidaten per gecontroleerde run;
- geen geraden e-mailadressen;
- gevonden e-mail zet contactbasis nooit automatisch op groen.

## Copy

`scripts/prepare_growth_batch.py` maakt korte Groeiabonnement-copy:

- ongeveer 50-90 woorden;
- alle zes onderdelen kort benoemd;
- één primaire focus;
- €200-€500 p/m standaard zichtbaar, afhankelijk van scope;
- Andrew Baeten + andrewbaeten.nl;
- eenvoudige afmeldzin;
- geen onbewezen prospectproblemen of garanties.

## Na positieve interesse

Pas daarna specialistische verdieping via Webactueel:

- Design/UX;
- SEO/search;
- social evidence;
- automation/WordPress/Elementor/programmeren;
- hosting/migratie.

## Niet meer standaard

De oude refill-controller, DraftQueue/mijn.host-runtime, runtime-branch bridge en losse duplicate discovery-workflows zijn legacy en worden uit de compacte route verwijderd. De standaardrepo bereidt kandidaten en copy voor; live verzending is een afzonderlijke, expliciete stap buiten deze repo.

## Veiligheidsgrenzen

- discovery-hints zijn geen prospectbewijs of toestemming;
- prospecttargets en mailboxbewijs horen niet in de default branch;
- geen automatische verzending;
- actuele juridische/providerregels blijven leidend voor daadwerkelijke outreach.
