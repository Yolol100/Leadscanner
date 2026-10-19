# Leadscanner — één uitvoercontract

De actieve **Leads-skill** is inhoudelijk eigenaar; `webactueel-workflow` is uitsluitend procescontroller. De actuele Project Leads-bronnen zijn beleid; deze repo is de uitvoering. Lees [README.md](README.md) alleen voor actuele repo-opdrachten en technische gates.

## Bestaande route

1. Zoek Nederlandse lokale vakbedrijven; Overture/PDOK zijn hints, geen bevestigde leads.
2. Verifieer identiteit, officiële website en één expliciet gepubliceerd professioneel adres of algemeen bedrijfsadres. Controleer **alle** historische dedupe, HMAC, bounces, opt-outs, LeadHistory en DraftQueue.
3. Maak alleen na autorisatie een privé Mijn.Host-concept via DraftQueue, IMAP `\\Draft` en exacte same-folder readback; nooit SMTP/send.
4. Geef aan de mens voor inhoudelijke en wettelijke controle. Een openbaar e-mailadres is geen verzendtoestemming.

## Bestaande commandopoorten

- Issue **#1720**: `LEADS_CHAT_V1:CHECK` en `LEADS_CHAT_V1:DRAFTS_AUDIT` zijn read-only; zoeken en evidence alleen als `LEADS_CHAT_V2:<MODE>:r-<32hex>` met geautoriseerde mode, stabiel aanvraag-ID, private readback en geen dubbele run.
- Issue **#1659**: `LEADS_DRAFT_ONLY` of `LEADS_DRAFT_BATCH_ONLY`, uitsluitend opaque geverifieerde draft-ID's en met huidige issue-/actor-/IMAP-gates.
- De vroegere planning/cron is uitgeschakeld. `auto_draft_new.py` is geen alternatief om alsnog automatisch concepten te genereren.

## Afbakening en opschoning

- Gewone leads krijgen **geen** diepgaande websiteaudits, leadscores, Ahrefs-cijfers of video-pitch. De aparte **voorgestelde** videoroute mag tot vijf reeds geselecteerde leads verdiepen, maar is **niet** als nieuw GitHub-commando actief.
- De gewenste neutrale twee-alineamail is **nog niet geactiveerd**. De zes bestaande branchemails blijven het huidige repo-contract totdat bronnen, skill, code, tests en private readback formeel zijn gesynchroniseerd.
- `Review450`-historie, tijdelijke 450-scripts, oude concepten en suppressies niet verwijderen of herschrijven zolang de afzonderlijke taak niet is afgesloten en de herstelroute niet bewezen is.
- Nooit prospect-, contact- of maildata in publieke commits, issues, logs of artifacts. Weiger een mutatie bij ontbrekend bewijs/rechten; omzeil geen beveiliging. CI-groen is geen bewijs van een opgeslagen concept.
