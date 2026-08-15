# Leadscanner

Private Webactueel lead-scanner voor het read-only controleren van publieke websites met Crawlee + Playwright.

## Wat de scanner doet

- gebruikt `PlaywrightCrawler` voor begrensde parallelle verwerking van websites;
- opent iedere website in Chromium;
- controleert desktop (1440x900) en mobiel met iPhone 13-emulatie;
- bepaalt per website eerst het waarschijnlijke sitetype `service`, `shop` of `booking`;
- kiest daarna de belangrijkste routepagina's, bijvoorbeeld homepage -> hoofddienst -> contact/offerte, of product -> winkelwagen -> checkout;
- bekijkt maximaal vier kernpagina's per website en stopt voor formulierverzending, bestelling, betaling of boekingsbevestiging;
- blokkeert niet-GET/HEAD-verzoeken tijdens de scan;
- signaleert onder andere HTTP-fouten, JavaScript-fouten, kapotte afbeeldingen, mobiele overflow, placeholderteksten en generieke CTA-labels;
- draait axe op serieuze/kritieke toegankelijkheidsproblemen;
- kan optioneel Lighthouse draaien op websites waar al een sterke browserbevinding is gevonden;
- maakt per bezochte kernpagina een compacte screenshot als browserbewijs;
- maakt hashgebonden `controlled_browser_capture`-records met desktop- en mobile-evidence-ID's die aansluiten op de Webactueel Leads-workflow;
- bewaart per website JSON en daarnaast een gezamenlijk `summary.md` en `results.json`.

## Veiligheidsgrens

De scanner is read-only. Hij verstuurt geen formulieren, plaatst geen bestellingen, bevestigt geen boekingen en wijzigt niets op doelwebsites. Verzoeken anders dan GET/HEAD worden tijdens de scan geblokkeerd.

## Schaalbegrenzing

De standaard full scan gebruikt maximaal vier websites tegelijk en maximaal 30 Crawlee-startrequests per minuut. `maxRequestsPerCrawl` wordt begrensd op de ingevoerde websitebatch. Crawlee mag de leadkwalificatie niet zelfstandig beslissen: `candidate: true` is alleen een technisch browsersignaal.

## Websites toevoegen

Zet één website per regel in `sites.txt`, bijvoorbeeld:

```text
https://voorbeeldbedrijf.nl/
https://anderbedrijf.nl/
```

Een wijziging aan `sites.txt` op `main` start automatisch de workflow **Website Scan**. Je kunt de workflow ook handmatig uitvoeren en optioneel één `target_url` invullen.

## Scan starten

1. Zet de te controleren URLs in `sites.txt`.
2. Commit de wijziging op `main`, of open in GitHub **Actions -> Website Scan -> Run workflow**.
3. Laat Lighthouse standaard uit voor de eerste batch; gebruik het alleen als extra tweede controle.
4. Na afloop staat onder de run een artifact `leadscanner-results-...` met screenshots, JSON-bewijs en `summary.md`.

Artifacts blijven 7 dagen bewaard.

## Interpretatie voor Project Leads

De scanner levert browserbewijs en triagesignalen. De uiteindelijke kwalificatie blijft eigendom van de Webactueel Leads-workflow:

1. registry-voorcheck / expliciete rescan;
2. officiële bedrijfswebsite bevestigen;
3. desktop + mobiel kernroutebewijs beoordelen;
4. maximaal drie bewezen observaties kiezen;
5. `problem_severity`, `webactueel_fit` en score 1-5 bepalen;
6. alleen score 3-5 met `qualified=true` gaat door naar contactcontrole.

Een openbaar e-mailadres is geen toestemming en de scanner maakt of verstuurt geen e-mail.
