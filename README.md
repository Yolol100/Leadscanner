# Leadscanner

De standaardflow is één run:

**vinden -> verifiëren/selecteren -> korte Groeiabonnement-mail maken -> mijn.host-concept + exacte readback**

Er wordt nergens automatisch verzonden.

## 1. Vinden

- PDOK + Overture Maps Places + Google Maps;
- deduplicatie;
- vroege uitsluiting van marketing/web/SEO/social/AI/automation/WordPress/Elementor/hosting-aanbieders;
- Overture- en Google Maps-e-mailvelden zijn alleen kandidaat-contactgegevens.

## 2. Verifiëren/selecteren

De officiële website controleert in één pass:
- bedrijf/domein;
- finale concurrentstatus;
- NL/EN;
- publiek zakelijk e-mailadres.

E-mailprioriteit:
1. officiële website;
2. Overture-emailcandidate;
3. Google Maps-e-mailfallback.

Formulierplaceholders, voorbeeldadressen en duidelijk corrupte scraper-adressen worden geweigerd. Zichtbare paginatekst mag een fout of verouderd `html lang` attribuut overrulen.

Een publiek of gescrapet e-mailadres geeft nooit automatisch toestemming. Zonder bewezen contactbasis wordt het concept als `review_draft` opgeslagen zodat Andrew dit pas aan het eind beoordeelt.

## 3. Mail maken

Eén Groeiabonnement van **€250-€500 per maand afhankelijk van scope** met:
- website/webshop verbeteren;
- zoekbaarheid verbeteren;
- social content verzorgen;
- geschikte repetitieve werkzaamheden tot circa 30% automatiseren waar haalbaar;
- hosting overnemen/beheren;
- Andrew als vast contactpersoon.

Het onderwerp is kort en relevant. De body gebruikt twee korte openingsalinea's, een pakketregel met prijs, zes bullets, één lage-frictie CTA, een makkelijke afmelding en een duidelijke afzender/signatuur.

## 4. mijn.host-concept

De geselecteerde mail gaat direct via IMAP naar mijn.host Concepten/Drafts. De workflow leest ontvanger, onderwerp, body en eventuele review-header exact terug. Een run is pas groen wanneer exact het gevraagde aantal concepten aantoonbaar in mijn.host staat en de readback klopt. Dezelfde `growth-...` lead-ID wordt niet dubbel aangemaakt.

**SMTP/sendcode bestaat niet. Andrew verzendt alleen handmatig na beoordeling.**

## Starten

Dezelfde workflow ondersteunt:
- normale `workflow_dispatch`;
- een owner-only GitHub issue met titel `[growth-draft] ...` en JSON-body. Dit maakt ChatGPT-triggering mogelijk zonder een aparte runtime-controller.

Andere issue-auteurs kunnen de secret-using job niet uitvoeren.
