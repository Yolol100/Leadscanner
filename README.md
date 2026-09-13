# Leadscanner

> **Status:** GitHub-uitvoeringslaag voor Webactueel Leads. Nieuwe standaard: signal-first v16; draft-first en nooit automatisch verzenden.

De machineleesbare waarheid staat in `toolkit-contract.json`; de menselijke grens in `LEADS-INTEGRATION.md`. Live Project Leads blijft beleidswaarheid.

## Standaardroute

```text
sterke prospect
-> officiële homepage + relevante procespagina's
-> één zichtbaar signaal
-> één klein passend aanbod
-> officieel zakelijk e-mailadres
-> korte research-backed mail
-> OutreachQueue manual_review
-> geselecteerde mijn.host IMAP Draft sync + readback
-> reply handoff
```

Normale nieuwe drafts hebben geen verplichte score, A/B/C-tier of campaign-gate.

## Aanbod

AI agents: `front_desk_sales`, `lead_reactivation`, `review_concierge`, `customer_support`, `commerce`, `quote_intake`.

Daarnaast: `website_webshop_improvement`, `search_visibility`, `social_management`.

Pitch per eerste mail exact één aanbod. Geef eerst kleine waarde: voorbeeld, mini-flow, mock-up, vindbaarheidskansen of postideeën. Geen verzonnen ROI/resultaten of geraadde contactgegevens.

## Mail en mijn.host

Eerste mail: grofweg 50-100 woorden, één echte observatie, één kleine verbetering, één permission CTA. Voorkeursdrafttransport is `sync-selected-myhost-drafts-command.yml`; dit is IMAP Drafts/Concepten + readback, geen SMTP.

Live verzending is een afzonderlijke expliciete route met bestaande readiness-, suppression-, compliance- en SMTP-gates.

## Legacy

Customer Potential, A/B/C, campaign-first agentprepare en historische website/webshoptransport blijven compatibility/rollback totdat v16-parity en callsite-cleanup zijn bewezen. Ze zijn niet meer de standaard voor nieuwe drafts.

## Tests

```bash
python3 -m pip install -r requirements-outreach.txt
python3 -m compileall -q scripts
PYTHONPATH=scripts python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Zie `LEADS-INTEGRATION.md` voor de volledige grens en `AGENTS.md` voor repository-instructies.
