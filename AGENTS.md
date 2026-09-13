# Leadscanner repository instructions

## Scope

- Dit is de geregistreerde GitHub-uitvoeringslaag voor `leads`, niet de procescontroller.
- `webactueel-workflow` bezit cross-skill routing; live Project Leads bezit actuele leadpolicy.
- `toolkit-contract.json` is het machinecontract; `LEADS-INTEGRATION.md` de menselijke canonieke grens.
- Nieuwe standaardroute is Project Leads `16.0.0-signal-first-machine`.

## v16 default

`VIND -> BEGRIJP -> SIGNAAL -> EEN AANBOD -> OFFICIEEL CONTACT -> KORTE MAIL -> MIJN.HOST CONCEPT -> REPLY HANDOFF`

Voor een normaal nieuw draftconcept:

- geen verplichte Customer Potential-score, A/B/C-tier of campaign-gate;
- homepage + maximaal 2-3 procesrelevante pagina's;
- exact één publiek aantoonbaar signaal;
- exact één aanbod;
- exact één publiek zakelijk e-mailadres van de officiële site;
- korte research-backed mail met permission CTA;
- `send_permission=none` en geen SMTP.

## Aanbod

Agent: `front_desk_sales`, `lead_reactivation`, `review_concierge`, `customer_support`, `commerce`, `quote_intake`.

Niet-agent: `website_webshop_improvement`, `search_visibility`, `social_management`.

`lead_reactivation` vereist first-party approved data. Search vereist SERP + site-evidence. Social vereist publieke officiële content/social-evidence. Verzin nooit pijn, ROI, volume, prijs, review, resultaat of contactgegevens.

## Drafttransport

- Gebruik voor nieuwe v16 batches bij voorkeur `sync-selected-myhost-drafts-command.yml` en `scripts/outreach_queue_imap_draft_sync_selected.py`.
- De geselecteerde sync accepteert `manual_review` en `approved` draftstate, doet idempotente IMAP Drafts-sync + readback en roept geen SMTP aan.
- De oudere single-draftcommand en campaign/scorepaden blijven compatibility/rollback totdat parity en callsite-cleanup zijn bewezen.

## Reply

`scripts/outreach_reply_triage.py` blijft adviserend. Positieve reply moet uiteindelijk Andrew melden en een vervolgconcept voorbereiden; claim dit pas als mailboxdetectie, classificatie, notificatie en draftreadback end-to-end zijn getest. Geen automatische verzending.

## Live-sendgrens

Bestaande sender-readiness, suppression, compliance en SMTP-gates blijven uitsluitend voor expliciete live-sendroutes. Draftstatus of publiek adres is nooit commerciële toestemming of send permission.

## Voor wijzigingen

- Lees `LEADS-INTEGRATION.md`, `toolkit-contract.json`, `tool-registry.json` en de directe scriptclosure.
- Behoud legacy transport/state zolang rollback/parity niet bewezen zijn.
- Voeg geen extra controller, provider of verifier toe zonder aantoonbaar capabilitygat.
- Houd secrets, prospectdata en runtime-output buiten `main`.

## Validatie

```bash
python3 -m pip install -r requirements-outreach.txt
python3 -m compileall -q scripts
PYTHONPATH=scripts python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Voor releaseclaims blijven `Toolkit Contract`, `Leads Runtime CI` en `Scanner Smoke Test` relevante code-/contractgates. Live mijn.host of Sheetwerking vereist afzonderlijke readback.
