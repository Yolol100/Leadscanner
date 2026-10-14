# Leadscanner — vier stappen, twee technische taken

De **menselijke workflow** is precies:

1. **Bedrijf zoeken** — alleen passende Nederlandse lokale vakbedrijven.
2. **E-mailadres zoeken** — maximaal één exact gepubliceerd algemeen zakelijk adres van de officiële bedrijfswebsite.
3. **E-mail opstellen in Mijn.Host Drafts** — één privé concept via IMAP, nooit via SMTP.
4. **Menselijke controle** — daarna beslist alleen een mens of het bericht geschikt en rechtmatig is.

## Wat deze publieke repo doet

- **Discovery + dedupe:** Overture/PDOK levert bedrijfshints. Het volledige historische Lead Dedupe Registry blokkeert eerdere contacten, bounces, afmeldingen en dubbelen. Openbare logs tonen alleen tellingen.
- **Doelgroepfilter:** standaardprofiel `vakbedrijven` omvat lokale bouw/installatie, tuin, schoonmaak, auto/fiets, reparatie, persoonlijke verzorging, horeca, lokale retail en vergelijkbare afspraak-/offertebedrijven. Digitale/marketing/SEO/web/IT/software/consultancy en andere poor-fit sectoren zijn geblokkeerd.
- **Mijn.Host Draft-only:** de mailinhoud staat in een **privé** Draft Queue. GitHub ontvangt alleen een willekeurig `draft-<32hex>` ID. De workflow schrijft via IMAP `APPEND` met `\Draft` naar de echte Drafts-map en leest hetzelfde concept exact terug. Er bestaat in deze route **geen SMTP-send**.

Issue #1659 is uitsluitend de opaque trigger voor Drafts. Zet daar nooit bedrijf, e-mailadres, onderwerp of mailtekst in.

## Wat niet terugkomt

Geen website-audits, problemenlijsten, leadscores, A/B-campagnes, CRM/outreach queues, sender-readiness, inbox-placement, tracking, automatische follow-ups of automatische verzending. Ook geen verplichte BV/NV-filter: een passende lokale eenmanszaak of vof mag binnen de doelgroep vallen.

De historische uitsluitingen en HMAC-beveiliging blijven behouden. Een openbaar e-mailadres is geen automatische toestemming om commerciële mail te sturen; de menselijke controle blijft de laatste stap.

Wetgeving: [Telecommunicatiewet art. 11.7](https://wetten.overheid.nl/BWBR0009950/2026-07-01) en [ACM spamregels](https://www.acm.nl/nl/verkoop-aan-consumenten/reclame-en-verleiden/spam-voorkomen-uw-reclame).
