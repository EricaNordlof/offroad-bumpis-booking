# Offroad Bumpis bokningssystem

## Starta lokalt

```powershell
cd C:\dev\booking_app_email_ready_kontakt
pip install -r requirements.txt
python app.py
```

Öppna sedan:

- Kundsida: http://127.0.0.1:5000/
- Kalender: http://127.0.0.1:5000/calendar
- Admin: http://127.0.0.1:5000/admin/login

Standardlösenord admin: `change_me`

## Lager och datum

Standard:

- 12 barnbollar finns nu.
- 12 vuxenbollar kan bokas från och med 1 september 2026.
- Kalendern visar 6 månader framåt.
- Bokning på fredag räknas som helgperiod: fredag kl. 08 till söndag kl. 20.

Ändra i `.env`:

```env
TOTAL_CHILD_BALLS=12
TOTAL_ADULT_BALLS=12
ADULT_AVAILABLE_FROM=2026-09-01
```

## Priser

- Barnbollar: 2-pack från 600 kr.
- Vuxenbollar: 2-pack från 700 kr.

Systemet visar pris från baserat på antal bollar.

## Funktioner

- Bokningsformulär
- Lager per barn-/vuxenboll
- Vuxenbollar spärrade före 1 september 2026
- Kalender 6 månader framåt
- Fredag–söndag som helgperiod till samma pris
- Leverans och återleverans/hämtning efteråt
- Adminpanel
- Bekräfta/avvisa bokningar
- Hyresavtal, villkor och checklistor som PDF
- SHA-256-hashar på dokument
- Skadefaktura
- E-postlogg i terminalen om SMTP saknas
- Favicon och logga

## E-post / notiser

Appen kan skicka mejl till både kunden och administratören, men bara om SMTP är konfigurerat.
Om SMTP inte är konfigurerat visas mejlen i terminalen i stället under rubriken `EMAIL TESTLÄGE`.

För att aktivera riktiga mejl:

1. Kopiera `.env.example` och döp kopian till `.env`.
2. Fyll i SMTP-uppgifter från din e-postleverantör.
3. Sätt `ADMIN_EMAIL=kontakt@offroadbumpis.se` eller den adress som ska få nya bokningsförfrågningar.
4. Starta om appen med `python app.py`.

Viktigt: klistra inte in e-postlösenord eller app-lösenord i chatten. Skriv dem direkt i `.env` på din egen dator.


## Priser på bokningssidan

Bokningsformuläret visar nu prisstege för barnbollar och vuxenbollar, samt tillval och leveranszoner.


## Dokumentlänkar

Denna version använder robust filnamnshantering för PDF-länkar, så dokumenten fungerar både lokalt på Windows och senare på live-server.


## Safe Standard-matchning

Denna version skapar dokument automatiskt när en bokning bekräftas, skapar SHA-256-hashar, ett hashregister och en publik verifieringslänk via `/verify/<token>`.

## Faktura och digital återlämningskontroll

När en bokning bekräftas skapas nu även en faktura/betalningsuppgifter med Swish, banköverföring och Stripe-länk. Betalning anges senast 3 arbetsdagar före utlämning.

Adminpanelen har också digital återlämningskontroll. När kontrollen sparas skapas en ifylld PDF, hashas och läggs in i hashregistret/verifieringssidan.

## Direktbokning och faktura

Kunden bokar direkt. Bokningen får status `booked_unpaid`, dokument och faktura skapas automatiskt och fakturan skickas till kundens e-post. Telefonnumret används som meddelande/OCR i fakturan. Bokningar som inte markerats som betalda efter sista betalningsdag släpps automatiskt när appen används igen.


## Tillval, leveranszon och digital utlämningskontroll

Kunden kan välja tillval och leveranszon direkt i bokningsformuläret. Summan räknas live och läggs på fakturan. Adminpanelen har både digital utlämningskontroll och digital återlämningskontroll. Båda skapar ifyllda PDF:er, hashas och hamnar i hashregister/verifiering.


## Skadefaktura

Skadefakturan innehåller nu betalningsuppgifter, Stripe-länk, Swish, bankkonto och betalningsvillkor: 14 dagar från utfärdande. Kundens telefonnummer används som meddelande/OCR.


## Fix v2: skadefaktura

Skadefakturan har betalningsuppgifter på samma sida:
Swish, Stripe/kort/Klarna, Svea Bank AB, clearingnummer, kontonummer, IBAN, BIC och Meddelande/OCR = kundens telefonnummer.
Betalningsvillkor: 14 dagar från utfärdande.


## Deploy till Render

Den här versionen är förberedd för Render.

Build command:
pip install -r requirements.txt

Start command:
gunicorn app:app

Persistent disk:
Mount path: /opt/render/project/src/data

Environment variables:
DATA_DIR=/opt/render/project/src/data
SECRET_KEY=<lång hemlig text>
ADMIN_PASSWORD=<eget adminlösenord>
ADMIN_EMAIL=kontakt@offroadbumpis.se

För riktiga mejl behövs även SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD och SMTP_FROM.
