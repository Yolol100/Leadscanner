# Leadscanner — Nederlandse bedrijfsleads

De Leadscanner zoekt nieuwe Nederlandse lokale bedrijven via **PDOK en Overture Maps**, controleert het exacte algemene zakelijke e-mailadres op de officiële bedrijfswebsite en slaat alleen unieke, bewezen leads veilig op in privéregisters.

**Alle zoekregels, uitsluitingen, controlevoorwaarden en snelheidsregels staan op één plek:** [docs/lead-only-scope.md](docs/lead-only-scope.md).

## Uitvoering
- `LEADS_CHAT_V1:CHECK`: controleer de bestaande historische uitsluitingen.
- `LEADS_CHAT_V2:HINTS_10/30/50/100:r-<32hex>`: verzamel bronhints in privé.
- `LEADS_CHAT_V2:VERIFIED_100:r-<32hex>` en `VERIFIED_GOAL_<1..1000>`: verifieer en sla begrensde aantallen op.

De bestaande bronproviders, verificatie, atomair opslaan en readback blijven intact. De anonieme samenvatting toont aantallen en bestaande tijdmetingen plus berekende doorvoer zonder extra websiteverzoeken. Geen e-mailverzending, drafts, video, website-audits of abonnementen. Historische uitsluitingen blijven bewaard.
