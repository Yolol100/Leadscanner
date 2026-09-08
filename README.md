# Leadscanner

> **Status:** centrale GitHub-runtime voor Webactueel Leads; nieuwe prospecting verkoopt standaard productized AI agents.

De machineleesbare waarheid staat in `toolkit-contract.json`; de menselijke uitvoeringsgrenzen staan in `LEADS-INTEGRATION.md`. Deze README blijft bewust kort om dubbele documentatie te voorkomen.

## Standaard aanbod

Nieuwe Leads-kwalificatie kiest één evidence-bound offer uit zes typen:

1. `front_desk_sales` — AI Front Desk & Sales Agent
2. `lead_reactivation` — AI Comeback Agent
3. `review_concierge` — AI Review Agent
4. `customer_support` — AI Customer Support Agent
5. `commerce` — AI Commerce Agent
6. `quote_intake` — AI Quote & Intake Agent

Geen generieke FAQ-bot of algemene autonome AI employee als standaardoffer. Agentprijzen worden niet uit creator/vendorcontent afgeleid; standaard `pricing_mode=no_price` totdat Leads-policy een prijs vastlegt.

## Capabilities

1. `prospect_discovery` — begrensde company/domain discovery uit goedgekeurde `ProspectSources`.
2. `contact_enrichment` — qualified-only officiële-site zakelijke contactevidence.
3. `website_evidence_scan` — optionele read-only website evidence.
4. `sender_readiness` — technische senderdiagnostiek; geen send permission.
5. `inbox_placement` — handmatige seed-only test.
6. `mailbox_draft` — self-only mijn.host IMAP-concepttest.
7. `outreach_delivery` — gecontroleerde mijn.host SMTP + IMAP readback voor afzonderlijk goedgekeurde state.
8. `dashboard` — read-only Google Sheet-controlpanel.
9. `prospect_intelligence` — afgeleide evidence/freshness/source/lookalike-laag.
10. `prospect_signal_discovery` — begrensde official-site signalen.
11. `prospect_qualification` — `scripts/prospect_agent_qualification.py`, Customer Potential en audit in `AgentProspectQualifications`.
12. `zero_touch_prepare` — discovery tot evidence-bound agentmail `status=prepared`, zonder mailboxcredential of send permission.

Leads-policy blijft eigenaar van realness, Customer Potential, offerselectie, copy, compliance en verzendgates. De repository voert alleen begrensde technische contracten uit.

## Hoofdroute

```text
ProspectSources
-> prospect_discovery
-> ProspectCandidates
-> prospect_signal_discovery
-> prospect_agent_qualification
-> AgentProspectQualifications
-> contact_enrichment
-> ContactCandidates
-> prospect_intelligence
-> outreach_agent_prepare
-> OutreachQueue status=prepared + compliance_status=manual_review
-> afzonderlijke compliance-goedkeuring
-> sender_readiness
-> outreach_delivery validate/live
-> SMTP / IMAP readback
-> Leads
```

Legacy `ProspectQualifications` en `website_scan:` blijven alleen voor historische website/webshopcompatibiliteit.

## Kernveiligheid

- Qualification: officiële evidence; één primaire agent opportunity; A vereist fact + idea + agent/process/KPI-context; geen compliance/send permission.
- Contact enrichment: geen geraadde/geconstrueerde adressen.
- Zero-touch prepare: alleen A + `ContactCandidates.ready`; queue blijft `prepared/manual_review`; geen SMTP/IMAP-secret.
- Agentmail: geen verzonnen ROI, workload, gemiste omzet of vaste prijs.
- Live target evidence: nieuwe rows gebruiken `agent_offer:<JSON>`; legacy `website_scan:<JSON>` blijft compatibility-only.
- EER live: aparte actuele geldige compliancebasis verplicht; openbaar adres/A-score/ready-contact is onvoldoende.
- Sender readiness, inbox placement en scanner evidence zijn technische bewijssoorten en nooit commerciële toestemming.
- Pushes/CI voeren geen live e-mail uit.

## Tests

```bash
python3 -m pip install -r requirements-outreach.txt
python3 -m compileall -q scripts
PYTHONPATH=scripts python3 -m unittest discover -s tests -p 'test_*.py' -v
```

`Toolkit Contract`, `Leads Runtime CI` en `Scanner Smoke Test` moeten groen zijn voor releaseclaims.

## Configuratie en hygiene

Secrets horen alleen in GitHub Actions Secrets. `zero_touch_prepare` gebruikt de Sheetcredential en geen mailboxcredentials. Geen klant-, secret- of runoutput op `main`. Volledige vars, data-contracten en gatevolgorde: zie `LEADS-INTEGRATION.md`.