# Leadscanner repository instructions

## Scope

- Dit is de centrale GitHub-runtime voor `leads`.
- Gebruik `toolkit-contract.json` als machineleesbaar capabilitycontract en `LEADS-INTEGRATION.md` als menselijke uitvoeringsgrens.
- Nieuwe prospecting verkoopt standaard `offer_family=ai_agent`; legacy website/webshop blijft compatibility-only.
- De zes goedgekeurde types zijn `front_desk_sales`, `lead_reactivation`, `review_concierge`, `customer_support`, `commerce` en `quote_intake`.
- `leads` bezit realness, Customer Potential, offerselectie, compliancebasis/status, LeadPromo-copy en interpretatie van readback.
- De repository mag policy deterministisch uitvoeren voor bounded qualification en prepare, maar mag nooit compliance automatisch goedkeuren of send permission creëren.
- `webactueel-workflow` bezit cross-skill routing, bronselectie en totale closure.
- `Yolol100/Orchestrator` is geen technische dependency.

## Capabilitygrenzen

- `prospect_discovery`: alleen goedgekeurde `ProspectSources`; company/domain-kandidaten; geen contacts, qualification, copy, compliance of mailcredentials.
- `prospect_signal_discovery`: bounded official-site signalen; evidencecontext en nooit toestemming.
- `prospect_qualification`: `scripts/prospect_agent_qualification.py`; officiële homepage; één primaire agent opportunity; score `ICP 0-3 + agent opportunity 0-3 + active signal 0-2 + value/integration fit 0-2`; A vereist evidence-bound fact + idea + agent/process/KPI-context; schrijft `AgentProspectQualifications`; geen compliance/send permission.
- Legacy `ProspectQualifications` blijft historische website/webshopstate en is niet de standaard nieuwe output.
- `contact_enrichment`: alleen `qualified`; begrensde officiële-site-evidence; nooit adressen raden/construeren.
- `prospect_intelligence`: afgeleide evidence/freshness/source/lookalike-laag; adviserend.
- `zero_touch_prepare`: discovery -> sanitizer -> signals -> agent qualification -> contact -> intelligence -> private config -> `outreach_agent_prepare`; alleen A `ai_agent` + ready contact; queue blijft `prepared/manual_review`, lege `compliance_basis`; geen mailboxsecrets of SMTP.
- `website_evidence_scan`: optioneel read-only en geen score/compliance/send permission.
- `sender_readiness`: technische senderdiagnostiek; `provider_managed` is geen per-IP reputatie/placementclaim.
- `inbox_placement`: handmatig seed-only, nooit `OutreachQueue`.
- `mailbox_draft`: self-only mijn.host IMAP `APPEND` + readback, nooit SMTP/Sheet.
- `outreach_delivery`: alleen afzonderlijk goedgekeurde state; manual default `validate`; nieuwe rows gebruiken `agent_offer:<JSON>`, legacy `website_scan:<JSON>` blijft compatibility-only; live vereist alle readiness/compliance/suppression/transportgates.
- `dashboard`: read-only aggregatie.

## Agentoffergrenzen

- Verkoop het bedrijfsproces/resultaat, niet de leverancier of tool.
- Kies exact één primaire agent per prospect op basis van officiële evidence.
- Geen generic FAQ-bot, algemene autonome AI employee of losse sales closer als standaardproduct.
- `front_desk_sales` omvat leadkwalificatie, eenvoudige salesvragen, booking/follow-up en menselijke overdracht.
- `lead_reactivation` vereist een door de klant goedgekeurde oude-lead/offertegroep; cold discovery alleen bewijst geen beschikbare reactivation database.
- `review_concierge` mag geen review gating, fake reviews of onderdrukking van negatieve klanten doen.
- `commerce` gebruikt echte catalogus/orderdata; verzin nooit prijs, voorraad, levertijd of producteigenschap.
- `quote_intake` mag concepten voorbereiden; bindende prijs/voorwaarden vereisen menselijke goedkeuring.
- Agentpricing is standaard `no_price`; leid geen prijs af uit YouTube, creators of vendors.
- Creator-/vendorclaims zijn hypotheses; gebruik ze niet als prospect-specifiek bewijs voor pijn, volume, omzet, ROI of besparing.

## Secret- en compliancegrenzen

- Commit, print, log of artifact nooit secretwaarden.
- Discovery/signal/qualification/contact/intelligence/prepare krijgen geen mailboxsecrets.
- `zero_touch_prepare` krijgt alleen `GOOGLE_SERVICE_ACCOUNT_JSON` en gewone vars.
- Productie-SMTP/IMAP-secrets zijn alleen beschikbaar in expliciete live/mailboxstappen.
- CI voert nooit live send uit.
- EER live outreach vereist altijd een afzonderlijk evidence-bound geldige compliancebasis; openbaar e-mailadres, A-score of ready contact is nooit genoeg.
- Nieuwe agentrows erven nooit een oude compliancebasis of oude live-cohortapproval.

## Voor wijzigingen

- Lees `LEADS-INTEGRATION.md`, `toolkit-contract.json`, `tool-registry.json`, relevante workflow en directe scriptclosure.
- Houd secrets, prospectdata en runtime-output buiten `main`.
- Voeg geen provider, verifier, warmup-netwerk of extra controller toe zonder aantoonbaar capabilitygat en tests.
- Qualificatie mag generieke signalen niet opstapelen tot kunstmatig hoge fit en moet evidence-onzekerheid fail-closed als hold/UNSCORED behandelen.
- Behoud legacy transportcompatibiliteit tenzij migratiebewijs en rollback aantoonbaar zijn.

## Validatie

```bash
python3 -m pip install -r requirements-outreach.txt
python3 -m compileall -q scripts
PYTHONPATH=scripts python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Behoud daarnaast `Toolkit Contract`, `Leads Runtime CI` en `Scanner Smoke Test` voor capabilitydekking, no-send prepare, agent evidence, fail-closed livevolgorde en secretisolatie.

## Evidencegrenzen

- Discovery maakt kandidaten, geen goedgekeurde leads.
- `AgentProspectQualifications` is een reproduceerbaar offer-/kwalificatiebesluit, geen compliance- of resultaatbewijs.
- `agent_offer:` is transportevidence metadata, geen bewijs dat beloofde bedrijfsresultaten zijn gerealiseerd.
- Prepared mailcopy is reviewstate, geen sendbewijs.
- Scanneroutput, sender readiness en seed placement zijn afzonderlijke technische bewijssoorten.
- Groene repositorytests bewijzen code/contracts; live Sheet/mailbox readiness vereist aparte readback.