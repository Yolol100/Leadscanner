# Leadscanner

Private Webactueel lead-scanner voor het read-only controleren van publieke websites.

## Wat de scanner doet

- opent iedere website in Chromium;
- controleert desktop (1440x900) en mobiel (iPhone 13-emulatie);
- bekijkt de homepage plus maximaal twee relevante interne pagina's, zoals contact, offerte, diensten, booking of checkout;
- signaleert onder andere HTTP-fouten, JavaScript-fouten, kapotte afbeeldingen, mobiele overflow, placeholderteksten en generieke CTA-labels;
- draait axe op serieuze/kritieke toegankelijkheidsproblemen;
- kan optioneel Lighthouse draaien op websites waar al een sterke browserbevinding is gevonden;
- maakt screenshots bij bevindingen met ernst 3 of hoger;
- bewaart per website JSON en daarnaast een gezamenlijk `summary.md` en `results.json`.

## Veiligheidsgrens

De scanner is read-only. Hij verstuurt geen formulieren, plaatst geen bestellingen en wijzigt niets op doelwebsites. Hij navigeert alleen via publieke GET-pagina's.

## Websites toevoegen

Zet één website per regel in `sites.txt`, bijvoorbeeld:

```text
https://voorbeeldbedrijf.nl/
https://anderbedrijf.nl/
```

Je kunt bij een handmatige run ook één losse URL invullen. Dan wordt `sites.txt` voor die run genegeerd.

## Scan starten

1. Open in GitHub het tabblad **Actions**.
2. Kies **Website Scan**.
3. Klik **Run workflow**.
4. Laat `target_url` leeg om `sites.txt` te gebruiken, of vul één website in.
5. Zet Lighthouse alleen aan wanneer je die extra controle wilt; dit kost meer runtime.
6. Na afloop staat onder de run een artifact `leadscanner-results-...` met het bewijs en de resultaten.

Artifacts blijven 7 dagen bewaard.

## Interpretatie

`candidate: true` betekent alleen dat de automatische browsercontrole minstens één bevinding met ernst 3+ heeft gevonden. Het is nog geen definitieve commerciële lead. De uiteindelijke kwalificatie hoort de Webactueel Leads-workflow te doen op basis van bewijs, relevantie en impact voor een echte bezoeker.
