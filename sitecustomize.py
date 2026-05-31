from __future__ import annotations

import importlib.abc
import os
import sqlite3
import sys
from datetime import datetime
from importlib.machinery import PathFinder
from pathlib import Path

TERMS_URL = os.getenv("TERMS_URL", "https://offroadbumpis.se/villkor.html")
BASE_DIR = Path(__file__).resolve().parent
MANUAL_IMAGE_PATH = Path(os.getenv("MANUAL_IMAGE_PATH", str(BASE_DIR / "static" / "manual.png")))

_PATCHED = False


def _draw_wrapped(c, text: str, x: int, y: int, max_chars: int = 88, step: int = 13) -> int:
    line = ""
    for word in str(text or "").split():
        candidate = f"{line} {word}".strip()
        if len(candidate) > max_chars:
            if line:
                c.drawString(x, y, line)
                y -= step
            line = word
        else:
            line = candidate
    if line:
        c.drawString(x, y, line)
        y -= step
    return y


def _generate_bumperball_manual_pdf(case_path: Path) -> str:
    """Create a PDF manual. Uses static/manual.png if it exists, otherwise creates a text manual."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    case_path.mkdir(parents=True, exist_ok=True)
    path = case_path / "manual_bumperball.pdf"
    page_width, page_height = A4

    c = canvas.Canvas(str(path), pagesize=A4)

    if MANUAL_IMAGE_PATH.exists():
        try:
            image = ImageReader(str(MANUAL_IMAGE_PATH))
            img_width, img_height = image.getSize()
            margin = 24
            max_width = page_width - margin * 2
            max_height = page_height - margin * 2
            scale = min(max_width / img_width, max_height / img_height)
            draw_width = img_width * scale
            draw_height = img_height * scale
            x = (page_width - draw_width) / 2
            y = (page_height - draw_height) / 2
            c.drawImage(
                image,
                x,
                y,
                width=draw_width,
                height=draw_height,
                preserveAspectRatio=True,
                mask="auto",
            )
            c.save()
            return str(path)
        except Exception as exc:
            print(f"Kunde inte skapa manual-PDF från bild: {exc}")

    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "Enkel spelguide / användarmanual - Bumperball")
    y -= 28

    c.setFont("Helvetica", 10)
    y = _draw_wrapped(
        c,
        "Säker användning för barnaktivitet. Läs igenom innan start och avbryt direkt vid obehag, skada eller osäkerhet.",
        40,
        y,
        max_chars=86,
        step=13,
    )
    y -= 10

    sections = [
        ("1. Målgrupp", [
            "7-12 år.",
            "Max 60 kg per deltagare.",
            "1 person per boll.",
            "Ansvarig vuxen ska vara på plats.",
        ]),
        ("2. Underlag", [
            "Tillåtet: gräs, konstgräs, sporthall, fin sand och mjuk snö.",
            "Ej tillåtet: asfalt, grus, betong, is, hårt eller ojämnt underlag.",
            "Ytan ska vara fri från hinder.",
        ]),
        ("3. Innan ni börjar", [
            "Pumpa upp bollarna ordentligt.",
            "Kontrollera remmar och handtag.",
            "Se till att ytan är fri från hinder.",
            "Gå igenom reglerna före start.",
        ]),
        ("4. Spelregler / grundregler", [
            "Inga dobbar, smycken eller vassa föremål.",
            "Ingen tackling bakifrån.",
            "Ingen kontakt med spelare som ligger ner.",
            "Inga farliga tacklingar eller grov lek.",
            "Stoppa direkt om vuxen säger stopp.",
            "Ta pauser och drick vatten.",
            "Avbryt vid obehag, skada eller risk.",
        ]),
        ("5. Tillsyn", [
            "Ansvarig vuxen ska övervaka hela tiden.",
            "Ingen användning utan tillsyn.",
            "Vuxen ska stoppa leken direkt om reglerna inte följs.",
        ]),
        ("6. Så spelar ni", [
            "Dela in barnen i smålag.",
            "Spela korta matcher: 3-5 minuter.",
            "5 mot 5 eller mindre lag.",
            "Vinst 3 poäng, oavgjort 1 poäng.",
        ]),
        ("7. Spelidéer", [
            "Rushmatch.",
            "Bumper Tag.",
            "Kungen av ringen.",
            "Sköldpaddan.",
        ]),
        ("8. Pumpar / pumpning", [
            "Endast vuxen använder pumpen.",
            "Håll pumpen manuellt över ventilöppningen.",
            "Öppna och stäng ventil enligt instruktion.",
            "Bind upp långt hår och håll lösa kläder borta från pumpen.",
        ]),
        ("9. Efter aktiviteten", [
            "Kontrollera bollar och tillbehör.",
            "Packa ihop allt.",
            "Markera eventuella skador.",
        ]),
        ("10. Försäkring & ansvar", [
            "Normal användning enligt reglerna: ingen deposition och ingen självrisk.",
            "Stoppa och rapportera skada, läckage, olycka eller tillbud direkt.",
            "Grov oaktsamhet eller förbjuden användning kan medföra ansvar.",
        ]),
        ("11. Acceptans", [
            "Genom att hyra och använda utrustningen bekräftar hyrestagaren att reglerna har lästs och förståtts.",
        ]),
    ]

    for title, items in sections:
        if y < 90:
            c.showPage()
            y = 800
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, title)
        y -= 17
        c.setFont("Helvetica", 10)
        for item in items:
            if y < 70:
                c.showPage()
                y = 800
                c.setFont("Helvetica", 10)
            y = _draw_wrapped(c, f"- {item}", 55, y, max_chars=82, step=12)
        y -= 8

    if y < 90:
        c.showPage()
        y = 800

    c.setFont("Helvetica-Bold", 12)
    _draw_wrapped(
        c,
        "Viktigt: Avbryt direkt vid obehag, skada eller osäkerhet. Använd inte utrustningen om något känns osäkert eller om underlaget inte följer reglerna.",
        40,
        y,
        max_chars=86,
        step=13,
    )

    c.save()
    return str(path)


def _ensure_terms_columns(app_module) -> None:
    db_path = Path(getattr(app_module, "DB_PATH"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(bookings)").fetchall()}

        if "terms_accepted" not in columns:
            db.execute("ALTER TABLE bookings ADD COLUMN terms_accepted INTEGER NOT NULL DEFAULT 1")
        if "terms_accepted_at" not in columns:
            db.execute("ALTER TABLE bookings ADD COLUMN terms_accepted_at TEXT")

        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS bookings_terms_accept_after_insert
            AFTER INSERT ON bookings
            FOR EACH ROW
            WHEN NEW.terms_accepted_at IS NULL
            BEGIN
                UPDATE bookings
                SET terms_accepted = 1,
                    terms_accepted_at = datetime('now')
                WHERE id = NEW.id;
            END;
            """
        )
        db.commit()


def _template_context(app_module):
    return {
        "form_data": __import__("flask").request.form,
        "inventory": getattr(app_module, "BALL_INVENTORY"),
        "adult_available_from": getattr(app_module, "ADULT_AVAILABLE_FROM").isoformat(),
        "adult_available_from_sv": "1 september 2026",
        "child_price_ladder": getattr(app_module, "CHILD_PRICE_LADDER"),
        "adult_price_ladder": getattr(app_module, "ADULT_PRICE_LADDER"),
        "addon_prices": getattr(app_module, "ADDON_PRICES"),
        "delivery_zones": getattr(app_module, "DELIVERY_ZONES"),
        "coupon_codes": getattr(app_module, "COUPON_CODES"),
        "terms_url": TERMS_URL,
    }


def _patch_app(app_module) -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    flask_app = getattr(app_module, "app")
    original_send_email = getattr(app_module, "send_email")

    @flask_app.context_processor
    def _offroad_bumpis_terms_context():
        return {"terms_url": TERMS_URL}

    @flask_app.before_request
    def _offroad_bumpis_terms_guard():
        from flask import render_template, request

        _ensure_terms_columns(app_module)

        if request.endpoint == "booking_form" and request.method == "POST":
            if request.form.get("terms_accepted") != "on":
                return render_template(
                    "booking_form.html",
                    error="Du måste godkänna hyresvillkoren innan du bokar.",
                    **_template_context(app_module),
                )

        return None

    def _patched_send_email(to_email: str, subject: str, body: str, attachments=None) -> None:
        attachment_list = list(attachments or [])

        if subject == "Din bokning och faktura - Offroad Bumpis":
            case_path = None
            for attachment in attachment_list:
                if attachment:
                    case_path = Path(attachment).parent
                    break
            if case_path is None:
                case_path = Path(getattr(app_module, "CASE_DIR")) / "manual"

            manual_file = _generate_bumperball_manual_pdf(case_path)
            if manual_file not in attachment_list:
                attachment_list.append(manual_file)

            if "Manualen för säker användning" not in body:
                body = body.replace(
                    "Fakturan/betalningsuppgifterna finns bifogad som PDF.\n",
                    "Fakturan/betalningsuppgifterna finns bifogad som PDF.\n"
                    "Manualen för säker användning finns också bifogad som PDF.\n"
                    f"Genom bokningen har du godkänt hyresvillkoren: {TERMS_URL}\n",
                )

        return original_send_email(to_email, subject, body, attachment_list or None)

    app_module.send_email = _patched_send_email

    try:
        _ensure_terms_columns(app_module)
    except Exception as exc:
        print(f"Kunde inte förbereda villkorskolumner: {exc}")


class _AppPatchLoader(importlib.abc.Loader):
    def __init__(self, original_loader):
        self.original_loader = original_loader

    def create_module(self, spec):
        if hasattr(self.original_loader, "create_module"):
            return self.original_loader.create_module(spec)
        return None

    def exec_module(self, module) -> None:
        self.original_loader.exec_module(module)
        if module.__name__ == "app":
            _patch_app(module)


class _AppPatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "app":
            return None

        spec = PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = _AppPatchLoader(spec.loader)
            return spec
        return None


if "app" in sys.modules:
    _patch_app(sys.modules["app"])
else:
    sys.meta_path.insert(0, _AppPatchFinder())
