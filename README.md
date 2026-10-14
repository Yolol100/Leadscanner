# Leadscanner — schone start

Alleen **nieuwe bedrijfshints vinden** met Overture Maps/PDOK en controleren tegen het bestaande historische deduplicatieregister. Oude mailsjablonen, mailboxcode, campagnes, herstel- en herschrijfworkflows zijn verwijderd uit de actieve repository.

## Behouden
- Google Sheet **Lead Dedupe Registry**, inclusief historische uitsluitingen, opt-outs en privé-HMAC-v2-sleutelkluis; nooit wissen of omzeilen
- Bestaande mailboxconcepten en hun 509 geverifieerde herstelkopieën (buiten GitHub, ongewijzigd)
- Terugdraaibare codegeschiedenis op `archive/leads-before-clean-start-20261014`

## Werkwijze
1. Valideer de volledige live uitsluitingsregistratie vóór ontdekking, anders stop.
2. Zoek bedrijfshints op basis van regio en branche via Overture/PDOK.
3. Verwijder historisch uitgesloten identiteiten en duplicaten.
4. Toon in publieke GitHub Actions alleen anonieme aantallen; bedrijfshints zijn **niet** onafhankelijk geverifieerde nieuwe leads.
5. Controleer de officiële website later afzonderlijk vóór kwalificatie.

Gebruik GitHub Actions **Fresh Leads** handmatig voor een regio/branche. Bij `region=Nederland` doorzoekt de workflow twaalf regionale centra verspreid over alle provincies (een **landelijke steekproef**, geen volledige landelijke dekking). Controleer eerst de live preflight. 
Bij gebruik via een geautoriseerde ChatGPT GitHub-connector zonder `workflow_dispatch` ondersteunen twee expliciete, gecontroleerde commit-markerstarts dezelfde veilige route op `main`: `LEADS_PREFLIGHT_ONLY:` en `LEADS_DISCOVERY_ONLY: <regio>|<branches>|<limiet>`. Discovery blijft strikt alleen-lezen en resultaten in openbare Actions bevatten uitsluitend aantallen. Geen SMTP, geen mijn.host, geen automatische drafts of verzending. Deze repo activeert geen eerdere Leads-richtlijnen. Reclame-e-mail vereist afzonderlijke beoordeling van toestemming en de toepasselijke regels.

## Vierstappenroute van de Leads Skill

De volledige Webactueel first-touch-flow is: (1) nieuwe bedrijven vinden, (2) hoogstens een openbaar algemeen zakelijk e-mailadres vanaf de officiele bedrijfswebsite ophalen en publicatiedoel controleren, (3) prive een korte mail opstellen, (4) handmatige beoordeling. Deze publieke repository voert alleen bedrijfshint-discovery en verplichte historische deduplicatie uit. Een bedrijfshint is geen geverifieerde lead.

Bewaar geen bedrijfsnamen, e-mailadressen, bron-URL's of mailteksten in publieke GitHub logs, commits of artifacts. Een publiek info@-adres is nooit automatisch verzendtoestemming. Review is niet send-ready; uitgesloten of afgemelde contacten blijven geblokkeerd. De Leads Skill controleert een geldige wettelijke basis afzonderlijk. Geen automatische verzending, mailboxconcepten of opvolgcampagnes toevoegen.

De eerste mail vereist geen 3-6 websiteproblemen, analyses, scores, prijsregels of zes verkoopbullets. Deeper specialistische analyse volgt pas na interesse. De bestaande veilige preflight, historische registry, secret vault, landelijke steekproef en test-suite blijven intact. Herstel geen legacy campagnes of templates.

### Doelgroep- en acceptatiegrens

De Leads Skill selecteert downstream uitsluitend onafhankelijk geverifieerde Nederlandse rechtspersonen (zoals BV/NV) voor deze ICP. Een naam die op BV eindigt, een Overture-/PDOK-record of een gepubliceerde info@ bewijst geen rechtsvorm en zeker geen verzendgrond. Deze publieke repo blijft alleen hints leveren en dedupliceren. Echte registraties, zakelijke contactadressen, contactbasis, menselijke conceptreview en ieder besluit tot handmatige verzending blijven buiten GitHub.
