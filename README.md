# Leadscanner

Eén simpele flow:

1. Zoek een bedrijf via Google Maps.
2. Open de echte website of webshop.
3. Kies precies één passend aanbod.
4. Zoek het beste publieke zakelijke e-mailadres: beslisser -> afdeling -> algemeen adres.
5. Maak één korte persoonlijke mail.
6. Controleer de mail.
7. Zet de geselecteerde lead als concept in mijn.host.
8. Stop. Andrew controleert en verstuurt zelf.

Google Maps is alleen het startpunt. Sla pas leaddata op nadat de website/webshop of een andere toegestane officiële bedrijfsbron is gecontroleerd.

Deze repository verstuurt nooit e-mail. Er staat geen SMTP-sendroute in de core.

## Repo-rol

ChatGPT/Leads doet stappen 1 t/m 6 en zet de gecontroleerde lead in `OutreachQueue`.
Deze repo doet alleen stap 7: geselecteerde lead-ID's lezen, de rij controleren, een IMAP-concept maken en exact teruglezen.

## Benodigde velden in OutreachQueue

`lead_id`, `company`, `website`, `email`, `subject`, `body`

## Mijn.host command

Maak een GitHub issue met titel `SYNC SELECTED MYHOST DRAFTS` en body:

```text
COMMAND=SYNC_SELECTED_MYHOST_DRAFTS
EXPECTED_COUNT=2
LEAD_ID=lead-1
LEAD_ID=lead-2
```

Alleen GitHub-gebruiker `Yolol100` kan deze workflow starten.
