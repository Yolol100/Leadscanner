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
