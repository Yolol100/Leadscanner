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

Gebruik GitHub Actions **Fresh Leads** handmatig voor een regio/branche. Geen SMTP, geen mijn.host, geen automatische drafts of verzending. Deze repo activeert geen eerdere Leads-richtlijnen. Reclame-e-mail vereist afzonderlijke beoordeling van toestemming en de toepasselijke regels.
