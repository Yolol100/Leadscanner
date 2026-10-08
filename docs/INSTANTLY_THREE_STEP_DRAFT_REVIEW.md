# Instantly Leadscanner: drie e-mails, concept ter beoordeling

**Status: CONCEPT — NIET GOEDGEKEURD, NIET GEACTIVEERD.**

- Campagne: `Leadscanner 3-Step Concept`
- ID: `59c01c6e-86a6-4417-acab-76f114dca9c5`
- Instantly-status: `0` (Draft)
- Opzet: 1 sequence, 3 e-mailstappen, 2 varianten per stap (6 totaal)
- Variabelen: `{{companyName}}`, `{{leadscanner_observation}}`, `{{leadscanner_value_action}}`
- Geen `{{aiIdeas}}`, `{{firstName}}`, `{{sendingAccountFirstName}}` of lead-specifieke onderwerp/body-velden
- SHA-256 van de live teruggelezen sequence: `4321b2abeb46b2d96f5b75c9d01a08ae4e28414ab27f76d6653459ca8176c3b5`
- Afzender gekoppeld: `info@andrewbaeten.nl` (accountstatus 1, warmupstatus 1 bij read-only controle)
- Venster: maandag t/m vrijdag 09:00–17:00; Instantly toont tijdzone `Arctic/Longyearbyen` (CET/CEST, controleer tijdzone in UI)
- Veiligheidsinstellingen: 15 e-mails/dag, 15 nieuwe leads/dag, 10 minuten tussen e-mails, stop bij antwoord en auto-reply, open-/linktracking uit, risicocontacten uit, uitschrijvingsheader aan
- Er zijn bij deze inrichting geen leads toegevoegd en geen e-mails verzonden.

De actieve oude campagne `827b1b45-6a7e-45ba-88de-d89db2a47d6a` is niet gewijzigd. De read-only audit bevestigde status Active en één e-mailstap met `leadscanner_subject` en `leadscanner_body`.

## Nog expliciet te beoordelen vóór staging of activering

1. Lees alle zes varianten in Instantly na op toon, feitelijkheid, CTA, opt-out en consistentie met de websiteobservaties. Dit concept is gebaseerd op de teruggevonden oorspronkelijke 3×2-opzet, maar is aangepast aan controleerbare velden; het is **niet** byte-identiek aan de oude teksten.
2. Beoordeel zelfstandig de juridische/contactgrondslag voor ongevraagde commerciële e-mail aan de beoogde ontvangers. Een groen technisch rapport bewijst geen juridische toestemming.
3. Controleer een voorbeeldweergave met een werkelijk goedgekeurde eerste-partijwaarneming; voorkom lege, onjuiste of onhandig geformuleerde mergevelden.
4. Draai daarna opnieuw de read-only `audit_campaign_sequence` op het concept. Als de fingerprint is veranderd, gebruik de **nieuwe** fingerprint na inhoudelijke herbeoordeling.
5. Alleen na expliciete goedkeuring van de campagne én de exacte reviewtokens mag `instantly_stage` leads aan de Draft toevoegen. De bestaande live dedupecontrole en readback blijven verplicht. Staging verstuurt niet.
6. Activatie/verzending is een **afzonderlijke expliciete handeling** en maakt geen deel uit van deze wijziging. De activeringscode blokkeert Leadscanner-campagnes zonder een per-lead gecontroleerde contactgrondslag (`leadscanner_contact_basis` = `consent_verified` of `existing_customer_related_verified`) en een bewijsreferentie (`leadscanner_contact_basis_ref`). Ook is een aparte, exacte `activation_approval` vereist die is gebonden aan de **live** sequentiehash én de hash van de exacte leadset. Deze velden worden niet automatisch afgeleid uit een publiek zakelijk e-mailadres. Gebruik eerst het read-only commando `audit_activation_readiness`; bij ontbrekende bewijsreferenties blijft activering geblokkeerd. De activatiecontrole vergelijkt bovendien alle leads met de actuele canonieke registry: alleen een unieke rij met status `instantly_staged` en hetzelfde lead-ID is toegestaan. Een afmelding, bounce, reply of andere statuswijziging blokkeert activering. Deze audit geeft geen juridisch oordeel.

Voor de huidige, inhoudelijk nog niet goedgekeurde versie zou de campagnegoedkeuring na review exact luiden:

```text
APPROVE_INSTANTLY_SEQUENCE 59c01c6e-86a6-4417-acab-76f114dca9c5 4321b2abeb46b2d96f5b75c9d01a08ae4e28414ab27f76d6653459ca8176c3b5
```

Gebruik deze tekst pas **na** de controles. Voer hem dan in bij `instantly_sequence_approval` van de GitHub Actions-workflow, samen met `confirm_instantly_stage=true`, `preview_run_id`, exacte `approved_review_tokens` en `instantly_campaign_id`. Dezelfde campagnegoedkeuring kan als `sequence_approval` worden doorgegeven aan het beveiligde `stage_approved_lead`-commando.

Bron voor de aangepaste zes varianten: `instantly-commands/inbox/create-20261008-leadscanner-evidence-three-step-draft.json`; de daadwerkelijk toegepaste sequentie staat in `instantly-commands/inbox/update-20261008-leadscanner-draft-three-step-sequence.json`.
