from __future__ import annotations

import calendar as pycalendar
import hashlib
import os
import secrets
import smtplib
import sqlite3
from email.message import EmailMessage
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Optional

from flask import (
    Flask,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def load_env_file() -> None:
    """Load simple KEY=VALUE pairs from a local .env file, if it exists."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-local-dev-key")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "bookings.db"
CASE_DIR = DATA_DIR / "cases"

TOTAL_CHILD_BALLS = int(os.getenv("TOTAL_CHILD_BALLS", "12"))
TOTAL_ADULT_BALLS = int(os.getenv("TOTAL_ADULT_BALLS", "12"))
ADULT_AVAILABLE_FROM = date.fromisoformat(os.getenv("ADULT_AVAILABLE_FROM", "2026-09-01"))

# Used as headline/default inventory. Actual adult availability is date-gated.
BALL_INVENTORY = {"barn": TOTAL_CHILD_BALLS, "vuxen": TOTAL_ADULT_BALLS}
TOTAL_BALLS = TOTAL_CHILD_BALLS + TOTAL_ADULT_BALLS
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change_me")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "kontakt@offroadbumpis.se")

SELLER_COMPANY = os.getenv("SELLER_COMPANY", "Nordlöf Nordic")
SELLER_BRAND = os.getenv("SELLER_BRAND", "Offroad Bumpis")
SELLER_ORG_NUMBER = os.getenv("SELLER_ORG_NUMBER", "8612253966")
SELLER_VAT_NUMBER = os.getenv("SELLER_VAT_NUMBER", "SE861225396601")
SELLER_ADDRESS = os.getenv("SELLER_ADDRESS", "Lövviksgatan 10, 213 74 Malmö")
SELLER_PHONE = os.getenv("SELLER_PHONE", "0793442520")
SELLER_EMAIL = os.getenv("SELLER_EMAIL", "kontakt@offroadbumpis.se")
SELLER_WEBSITE = os.getenv("SELLER_WEBSITE", "offroadbumpis.se")
SELLER_TAX_NOTE = os.getenv("SELLER_TAX_NOTE", "Godkänd för F-skatt")

PAYMENT_STRIPE_URL = os.getenv("PAYMENT_STRIPE_URL", "https://book.stripe.com/28E28tfsO6v888tbVw6oo0a")
PAYMENT_SWISH = os.getenv("PAYMENT_SWISH", "123-054 60 51")
PAYMENT_BANK_NAME = os.getenv("PAYMENT_BANK_NAME", "Svea Bank AB")
PAYMENT_CLEARING = os.getenv("PAYMENT_CLEARING", "9660")
PAYMENT_ACCOUNT = os.getenv("PAYMENT_ACCOUNT", "0643805")
PAYMENT_IBAN = os.getenv("PAYMENT_IBAN", "SE02 9660 0000 0966 0064 3805")
PAYMENT_BIC = os.getenv("PAYMENT_BIC", "SVEASESS")
PAYMENT_BIC_NOTE = os.getenv("PAYMENT_BIC_NOTE", "Använd SVEASESS tills vidare enligt bankens information.")

def file_basename(file_path: str) -> str:
    """Return file name only, regardless of Windows or Linux path separators."""
    return str(file_path or "").replace("\\", "/").rstrip("/").split("/")[-1]


app.jinja_env.filters["basename"] = file_basename



def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_: Optional[BaseException]) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            child_count INTEGER NOT NULL DEFAULT 0,
            adult_count INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            customer_type TEXT NOT NULL DEFAULT 'private',
            company_name TEXT,
            org_number TEXT,
            invoice_reference TEXT,
            location TEXT,
            deliver INTEGER NOT NULL DEFAULT 0,
            return_delivery INTEGER NOT NULL DEFAULT 0,
            delivery_zone TEXT NOT NULL DEFAULT 'pickup',
            tournament_kit INTEGER NOT NULL DEFAULT 0,
            car_rental INTEGER NOT NULL DEFAULT 0,
            cargo_bike INTEGER NOT NULL DEFAULT 0,
            coupon_code TEXT,
            discount_percent INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """
    )
    # Add newer columns if an older local database already exists.
    columns = {row["name"] for row in db.execute("PRAGMA table_info(bookings)").fetchall()}
    if "return_delivery" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN return_delivery INTEGER NOT NULL DEFAULT 0")
    if "delivery_zone" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN delivery_zone TEXT NOT NULL DEFAULT 'pickup'")
    if "tournament_kit" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN tournament_kit INTEGER NOT NULL DEFAULT 0")
    if "car_rental" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN car_rental INTEGER NOT NULL DEFAULT 0")
    if "cargo_bike" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN cargo_bike INTEGER NOT NULL DEFAULT 0")
    if "coupon_code" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN coupon_code TEXT")
    if "discount_percent" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN discount_percent INTEGER NOT NULL DEFAULT 0")
    if "customer_type" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN customer_type TEXT NOT NULL DEFAULT 'private'")
    if "company_name" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN company_name TEXT")
    if "org_number" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN org_number TEXT")
    if "invoice_reference" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN invoice_reference TEXT")
    db.commit()

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS safe_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            agreement_file TEXT,
            terms_file TEXT,
            handover_file TEXT,
            return_file TEXT,
            damage_invoice_file TEXT,
            payment_invoice_file TEXT,
            handover_control_file TEXT,
            return_control_file TEXT,
            hash_register_file TEXT,
            verification_token TEXT,
            agreement_hash TEXT,
            terms_hash TEXT,
            handover_hash TEXT,
            return_hash TEXT,
            damage_invoice_hash TEXT,
            payment_invoice_hash TEXT,
            handover_control_hash TEXT,
            return_control_hash TEXT,
            hash_register_hash TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        )
        """
    )

    # Add newer safe_cases columns if an older local database already exists.
    safe_columns = {row["name"] for row in db.execute("PRAGMA table_info(safe_cases)").fetchall()}
    if "hash_register_file" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN hash_register_file TEXT")
    if "hash_register_hash" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN hash_register_hash TEXT")
    if "verification_token" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN verification_token TEXT")
    if "payment_invoice_file" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN payment_invoice_file TEXT")
    if "payment_invoice_hash" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN payment_invoice_hash TEXT")
    if "return_control_file" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN return_control_file TEXT")
    if "return_control_hash" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN return_control_hash TEXT")
    if "handover_control_file" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN handover_control_file TEXT")
    if "handover_control_hash" not in safe_columns:
        db.execute("ALTER TABLE safe_cases ADD COLUMN handover_control_hash TEXT")
    db.commit()


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return func(*args, **kwargs)
    return wrapper


def parse_date(date_str: str) -> date:
    return date.fromisoformat(date_str)


def format_period(start_date_str: str, end_date_str: str) -> str:
    if start_date_str == end_date_str:
        return f"{start_date_str} kl. 08–20"
    return f"{start_date_str} kl. 08 till {end_date_str} kl. 20"


def booking_period(start_date_str: str, end_date_str: str | None = None) -> tuple[str, str]:
    """Return booking period.

    If end_date_str is provided, the customer has chosen a custom multi-day period.
    If it is left empty, Friday still automatically covers Friday 08:00 to Sunday 20:00.
    """
    start = parse_date(start_date_str)

    if end_date_str:
        end = parse_date(end_date_str)
        if end < start:
            raise ValueError("end_date_before_start_date")
        return start.isoformat(), end.isoformat()

    if start.weekday() == 4:  # Friday
        end = start + timedelta(days=2)
    else:
        end = start

    return start.isoformat(), end.isoformat()


def dates_between(start_date_str: str, end_date_str: str) -> list[str]:
    start = parse_date(start_date_str)
    end = parse_date(end_date_str)
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def rental_day_count(start_date_str: str, end_date_str: str) -> int:
    """Count price days for a booking period.

    Normal weekdays count as one rental day each. A full Friday-Sunday period
    counts as one rental day, matching the weekend rule on the booking page.
    """
    start = parse_date(start_date_str)
    end = parse_date(end_date_str)
    if end < start:
        raise ValueError("end_date_before_start_date")

    units = 0
    current = start
    while current <= end:
        if current.weekday() == 4 and current + timedelta(days=2) <= end:
            units += 1
            current += timedelta(days=3)
        else:
            units += 1
            current += timedelta(days=1)
    return max(units, 1)


def inventory_for_date(date_str: str) -> dict[str, int]:
    d = parse_date(date_str)
    return {
        "barn": TOTAL_CHILD_BALLS,
        "vuxen": TOTAL_ADULT_BALLS if d >= ADULT_AVAILABLE_FROM else 0,
    }


def reserved_per_type_on_date(date_str: str) -> dict[str, int]:
    db = get_db()
    row = db.execute(
        """
        SELECT
          COALESCE(SUM(child_count), 0) AS child_total,
          COALESCE(SUM(adult_count), 0) AS adult_total
        FROM bookings
        WHERE start_date <= ?
          AND end_date >= ?
          AND status IN ('booked_unpaid', 'paid', 'confirmed')
        """,
        (date_str, date_str),
    ).fetchone()
    return {"barn": int(row["child_total"]), "vuxen": int(row["adult_total"])}


def remaining_on_date(date_str: str) -> dict[str, int]:
    reserved = reserved_per_type_on_date(date_str)
    inventory = inventory_for_date(date_str)
    return {
        "barn": max(inventory["barn"] - reserved["barn"], 0),
        "vuxen": max(inventory["vuxen"] - reserved["vuxen"], 0),
    }


def remaining_for_period(start_date_str: str, end_date_str: str) -> dict[str, int]:
    remaining_days = [remaining_on_date(d) for d in dates_between(start_date_str, end_date_str)]
    return {
        "barn": min(day["barn"] for day in remaining_days),
        "vuxen": min(day["vuxen"] for day in remaining_days),
    }


CHILD_PRICE_LADDER = {0: 0, 2: 600, 4: 1100, 6: 1500, 8: 1800, 10: 2000, 12: 2200}
ADULT_PRICE_LADDER = {0: 0, 2: 700, 4: 1300, 6: 1900, 8: 2500, 10: 3000, 12: 3500}

ADDON_PRICES = {
    "tournament_kit": 1000,
    "car_rental": 500,
    "cargo_bike": 350,
}

ADDON_LABELS = {
    "tournament_kit": "Turneringskit",
    "car_rental": "Kombibil",
    "cargo_bike": "Ellådcykel",
}

DELIVERY_ZONES = {
    "pickup": {"label": "Hämta själv", "price": 0, "places": "Hämtning och lämning i Malmö."},
    "Z1": {"label": "Z1", "price": 500, "places": "Malmö."},
    "Z2": {"label": "Z2", "price": 600, "places": "Burlöv, Lomma, Staffanstorp."},
    "Z3": {"label": "Z3", "price": 700, "places": "Lund, Svedala, Vellinge."},
    "Z4": {"label": "Z4", "price": 800, "places": "Eslöv, Kävlinge, Trelleborg."},
    "Z5": {"label": "Z5", "price": 900, "places": "Höör, Hörby, Skurup."},
    "Z6": {"label": "Z6", "price": 1000, "places": "Landskrona, Ystad, Sjöbo."},
    "Z7": {"label": "Z7", "price": 1100, "places": "Helsingborg, Ängelholm, Bjuv, Åstorp, Höganäs, Svalöv, Klippan, Perstorp, Båstad."},
    "Z8": {"label": "Z8", "price": 1200, "places": "Kristianstad, Hässleholm, Osby, Bromölla, Östra Göinge, Simrishamn, Tomelilla, Örkelljunga."},
}


# Aktiva rabattkoder. Koderna kontrolleras server-side.
COUPON_CODES = {
    "BLLACA": 10,
    "BLLACA09": 10,

    "YNGVE10": 10,
    "IGEN-1026": 10,
    "BEHAR-1026": 10,
    "ERICA-10": 10,
    "ERICA10": 10,
    "ANNIKA-1026": 10,
    "YNGVE-1026": 10,
    "EMIL-1026": 10,
    "ERICA-1026": 10,
    "BUMPIS-4827": 10,
    "HJP-1026": 10,
    "KOMPASS-1026": 10,
    "VINTERSPEL": 10,

    "BUMPIS-2026": 20,
    "20BUMPERBALL2026": 20,
}

# Vem som ska få affiliate-mejl för respektive rabattkod.
AFFILIATE_COUPONS = {
    "BLLACA": {"name": "Behar Bllaca", "email": "b.bllaca86@hotmail.com"},
    "BLLACA09": {"name": "Behar Bllaca", "email": "b.bllaca86@hotmail.com"},
    "BEHAR-1026": {"name": "Behar Bllaca", "email": "b.bllaca86@hotmail.com"},

    "YNGVE10": {"name": "Yngve Aniedeh", "email": "yngveaniedeh@gmail.com"},
    "ANNIKA-1026": {"name": "Annika Nordlöf", "email": "annikanordlof@outlook.com"},
    "EMIL-1026": {"name": "Emil Aniedeh", "email": "emil.aniedeh2009@gmail.com"},
    "HJP-1026": {"name": "Hitta Jippo", "email": "Hittajippo@outlook.com"},
    "KOMPASS-1026": {"name": "Oliver", "email": "oliverlon20020@gmail.com"},
    "BUMPIS-4827": {"name": "Katusergo7", "email": "katusergo7@gmail.com"},
}


def normalize_coupon_code(code: str | None) -> str:
    return (code or "").strip().upper().replace(" ", "")


def coupon_discount_percent(code: str | None) -> int:
    return int(COUPON_CODES.get(normalize_coupon_code(code), 0))


def discount_amount_for_subtotal(subtotal: int, discount_percent: int) -> int:
    if subtotal <= 0 or discount_percent <= 0:
        return 0
    return int(round(subtotal * (discount_percent / 100)))


def total_after_discount(subtotal: int, discount_percent: int) -> int:
    return max(subtotal - discount_amount_for_subtotal(subtotal, discount_percent), 0)


def booking_value(booking, key: str, default=None):
    if isinstance(booking, dict):
        return booking.get(key, default)
    try:
        if hasattr(booking, "keys") and key in booking.keys():
            return booking[key]
    except Exception:
        pass
    return default


def customer_type_label(booking) -> str:
    return "Företag" if booking_value(booking, "customer_type", "private") == "company" else "Privatperson"


def customer_extra_lines(booking) -> list[str]:
    """Return simple customer/faktura lines for emails and PDFs."""
    lines: list[str] = [f"Bokar som: {customer_type_label(booking)}"]
    company_name = booking_value(booking, "company_name") or ""
    org_number = booking_value(booking, "org_number") or ""
    invoice_reference = booking_value(booking, "invoice_reference") or ""

    if company_name:
        lines.append(f"Företag: {company_name}")
    if org_number:
        lines.append(f"Organisationsnummer: {org_number}")
    if invoice_reference:
        lines.append(f"Fakturareferens/PO: {invoice_reference}")

    return lines


def seller_invoice_lines() -> list[str]:
    """Return seller/uthyrare lines for invoices and agreements."""
    lines = [
        "Säljare / uthyrare",
        SELLER_COMPANY,
        f"Varumärke: {SELLER_BRAND}",
        f"Organisationsnummer: {SELLER_ORG_NUMBER}",
        f"Momsregistreringsnummer: {SELLER_VAT_NUMBER}",
        f"Adress / utlämningsadress: {SELLER_ADDRESS}",
        f"E-post: {SELLER_EMAIL}",
        f"Telefon: {SELLER_PHONE}",
        f"Webb: {SELLER_WEBSITE}",
    ]
    if SELLER_TAX_NOTE:
        lines.append(SELLER_TAX_NOTE)
    return lines


def vat_breakdown_from_total(total_including_vat: int, vat_rate: int = 25) -> tuple[int, int, int]:
    """Return ex VAT, VAT amount and total, assuming prices include VAT."""
    total = int(total_including_vat or 0)
    if total <= 0 or vat_rate <= 0:
        return total, 0, total
    ex_vat = round(total / (1 + vat_rate / 100))
    vat = total - ex_vat
    return ex_vat, vat, total


def affiliate_for_coupon(code: str | None) -> dict[str, str] | None:
    return AFFILIATE_COUPONS.get(normalize_coupon_code(code))


def send_affiliate_booking_email(booking, coupon_code: str) -> None:
    affiliate = affiliate_for_coupon(coupon_code)
    if not affiliate:
        return

    send_email(
        affiliate["email"],
        "Ny bokning med din rabattkod - Offroad Bumpis",
        (
            f"Hej {affiliate['name']}!\n\n"
            f"Någon har bokat Offroad Bumpis med din rabattkod {normalize_coupon_code(coupon_code)}.\n\n"
            f"Kund: {booking_value(booking, 'name', '-')}\n"
            f"Kundens e-post: {booking_value(booking, 'email', '-')}\n"
            f"Period: {format_period(booking_value(booking, 'start_date'), booking_value(booking, 'end_date'))}\n"
            f"Pris att betala: {total_price_for_booking(booking)} kr\n\n"
            "Provision kan bli aktuell när bokningen är betald och genomförd enligt överenskommelse.\n\n"
            "Offroad Bumpis"
        ),
    )


def send_affiliate_paid_email(booking) -> None:
    coupon_code = booking_value(booking, "coupon_code")
    affiliate = affiliate_for_coupon(coupon_code)
    if not affiliate:
        return

    send_email(
        affiliate["email"],
        "Betalning registrerad med din rabattkod - Offroad Bumpis",
        (
            f"Hej {affiliate['name']}!\n\n"
            f"En bokning med din rabattkod {normalize_coupon_code(coupon_code)} är nu markerad som betald.\n\n"
            f"Kund: {booking_value(booking, 'name', '-')}\n"
            f"Kundens e-post: {booking_value(booking, 'email', '-')}\n"
            f"Period: {format_period(booking_value(booking, 'start_date'), booking_value(booking, 'end_date'))}\n"
            f"Betalt belopp enligt bokning: {total_price_for_booking(booking)} kr\n\n"
            "Offroad Bumpis"
        ),
    )


def ladder_price(count: int, ladder: dict[int, int]) -> int:
    return ladder.get(count, 0)


def price_from(child_count: int, adult_count: int) -> int:
    """Base price estimate using package ladders for child and adult bumperballs."""
    return ladder_price(child_count, CHILD_PRICE_LADDER) + ladder_price(adult_count, ADULT_PRICE_LADDER)


def addons_price(
    tournament_kit: int = 0,
    car_rental: int = 0,
    cargo_bike: int = 0,
    rental_days: int = 1,
) -> int:
    """Return addon price for the booking period.

    Tournament kit is charged once per booking. Kombibil and ellådcykel are
    charged per price day/rental day.
    """
    days = max(int(rental_days or 1), 1)
    total = 0
    if int(tournament_kit or 0):
        total += ADDON_PRICES["tournament_kit"]
    if int(car_rental or 0):
        total += ADDON_PRICES["car_rental"] * days
    if int(cargo_bike or 0):
        total += ADDON_PRICES["cargo_bike"] * days
    return total


def delivery_price(deliver: int = 0, return_delivery: int = 0, delivery_zone: str = "pickup") -> int:
    zone = DELIVERY_ZONES.get(delivery_zone or "pickup", DELIVERY_ZONES["pickup"])
    ways = (1 if int(deliver or 0) else 0) + (1 if int(return_delivery or 0) else 0)
    return zone["price"] * ways


def subtotal_price(
    child_count: int,
    adult_count: int,
    deliver: int = 0,
    return_delivery: int = 0,
    delivery_zone: str = "pickup",
    tournament_kit: int = 0,
    car_rental: int = 0,
    cargo_bike: int = 0,
    rental_days: int = 1,
) -> int:
    days = max(int(rental_days or 1), 1)
    return (
        price_from(child_count, adult_count) * days
        + delivery_price(deliver, return_delivery, delivery_zone)
        + addons_price(tournament_kit, car_rental, cargo_bike, days)
    )


def total_price(
    child_count: int,
    adult_count: int,
    deliver: int = 0,
    return_delivery: int = 0,
    delivery_zone: str = "pickup",
    tournament_kit: int = 0,
    car_rental: int = 0,
    cargo_bike: int = 0,
    coupon_code: str | None = None,
    rental_days: int = 1,
) -> int:
    subtotal = subtotal_price(
        child_count,
        adult_count,
        deliver,
        return_delivery,
        delivery_zone,
        tournament_kit,
        car_rental,
        cargo_bike,
        rental_days,
    )
    return total_after_discount(subtotal, coupon_discount_percent(coupon_code))


def subtotal_price_for_booking(booking) -> int:
    rental_days = rental_day_count(
        booking_value(booking, "start_date"),
        booking_value(booking, "end_date"),
    )
    return subtotal_price(
        int(booking_value(booking, "child_count", 0) or 0),
        int(booking_value(booking, "adult_count", 0) or 0),
        int(booking_value(booking, "deliver", 0) or 0),
        int(booking_value(booking, "return_delivery", 0) or 0),
        booking_value(booking, "delivery_zone", "pickup") or "pickup",
        int(booking_value(booking, "tournament_kit", 0) or 0),
        int(booking_value(booking, "car_rental", 0) or 0),
        int(booking_value(booking, "cargo_bike", 0) or 0),
        rental_days,
    )


def total_price_for_booking(booking) -> int:
    subtotal = subtotal_price_for_booking(booking)
    percent = int(booking_value(booking, "discount_percent", 0) or 0)
    return total_after_discount(subtotal, percent)


def booking_discount_amount(booking) -> int:
    subtotal = subtotal_price_for_booking(booking)
    percent = int(booking_value(booking, "discount_percent", 0) or 0)
    return discount_amount_for_subtotal(subtotal, percent)


def selected_addons_text(booking) -> str:
    selected = []
    rental_days = rental_day_count(booking["start_date"], booking["end_date"])
    if int(booking["tournament_kit"] or 0):
        selected.append(f"{ADDON_LABELS['tournament_kit']} ({sek(ADDON_PRICES['tournament_kit'])})")
    if int(booking["car_rental"] or 0):
        selected.append(f"{ADDON_LABELS['car_rental']} ({sek(ADDON_PRICES['car_rental'])} × {rental_days} hyresdagar)")
    if int(booking["cargo_bike"] or 0):
        selected.append(f"{ADDON_LABELS['cargo_bike']} ({sek(ADDON_PRICES['cargo_bike'])} × {rental_days} hyresdagar)")
    return ", ".join(selected) if selected else "-"


def selected_addon_terms(booking) -> list[str]:
    terms: list[str] = []

    if int(booking_value(booking, "tournament_kit", 0) or 0):
        terms.append(
            "Turneringskit: lagvästar, knäskydd, koner, markörer och skumfotboll ska återlämnas vid retur."
        )
        terms.append(
            "Turneringskit: diplom, poängmallar, pokal, visselpipa och reflexer får kunden behålla."
        )

    if int(booking_value(booking, "car_rental", 0) or 0):
        terms.append(
            "Kombibil: fria mil ingår. Bilen är en enklare äldre kombibil med värde cirka 15 000 kr."
        )
        terms.append(
            "Kombibil: bilen har trafikförsäkring. Normalt slitage ingår. Vårdslöshet, skador, böter, avgifter och saknad utrustning debiteras."
        )

    if int(booking_value(booking, "cargo_bike", 0) or 0):
        terms.append(
            "Ellådcykel: får användas för upp till 4 bollar inom Malmö. Batteriladdare ingår."
        )
        terms.append(
            "Ellådcykel: värde cirka 15 000 kr. Normalt slitage ingår. Vårdslöshet, skador, stöld/förlust, saknat batteri eller saknad laddare debiteras."
        )

    return terms


def send_email(to_email: str, subject: str, body: str, attachments: Optional[list[str]] = None) -> None:
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM") or smtp_user or "no-reply@offroadbumpis.se"
    attachments = attachments or []

    if not smtp_server or not smtp_port:
        print("\n--- EMAIL TESTLÄGE: SMTP är inte konfigurerat, inget mejl skickades ---")
        print("To:", to_email)
        print("Subject:", subject)
        print(body)
        if attachments:
            print("Attachments:", ", ".join([str(a) for a in attachments if a]))
        print("--- SLUT EMAIL ---\n")
        return

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    for file_path in attachments:
        if not file_path:
            continue
        path = Path(file_path)
        if path.exists():
            msg.add_attachment(
                path.read_bytes(),
                maintype="application",
                subtype="pdf",
                filename=path.name,
            )

    with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
        try:
            server.starttls()
        except Exception:
            pass
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)


def ensure_case_directory(booking_id: int) -> Path:
    case_path = CASE_DIR / str(booking_id)
    case_path.mkdir(parents=True, exist_ok=True)
    return case_path


def hash_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()



ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def clean_upload_filename(filename: str) -> str:
    """Return a safe file name for uploaded photos."""
    base = file_basename(filename).strip() or "foto"
    stem = Path(base).stem
    ext = Path(base).suffix.lower()
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem).strip("._-")
    safe_stem = safe_stem or "foto"
    return f"{safe_stem[:60]}{ext}"


def save_uploaded_photos(booking_id: int, field_name: str, phase: str) -> list[dict[str, str]]:
    """Save uploaded photos for handover/return control and return filename + hash."""
    saved: list[dict[str, str]] = []
    files = request.files.getlist(field_name)
    if not files:
        return saved

    case_path = ensure_case_directory(booking_id)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for index, uploaded in enumerate(files, start=1):
        original_name = getattr(uploaded, "filename", "") or ""
        if not original_name:
            continue

        safe_name = clean_upload_filename(original_name)
        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED_PHOTO_EXTENSIONS:
            continue

        target = case_path / f"{phase}_foto_{stamp}_{index}_{safe_name}"
        uploaded.save(target)
        saved.append({"filename": target.name, "hash": hash_file(target), "phase": phase})

    return saved


def photo_records_for_case(booking_id: int, phase: str | None = None) -> list[dict[str, str]]:
    """List saved photo evidence for a case."""
    case_path = ensure_case_directory(booking_id)
    phases = [phase] if phase else ["utlamning", "aterlamning"]
    records: list[dict[str, str]] = []

    for path in sorted(case_path.iterdir()):
        if not path.is_file():
            continue

        matched_phase = None
        for candidate in phases:
            if path.name.startswith(f"{candidate}_foto_"):
                matched_phase = candidate
                break

        if not matched_phase:
            continue

        records.append({
            "filename": path.name,
            "hash": hash_file(path),
            "phase": matched_phase,
        })

    return records


def photo_hashes_for_case(booking_id: int) -> dict[str, str]:
    """Return photo hashes in the same format as document hashes."""
    hashes: dict[str, str] = {}
    for record in photo_records_for_case(booking_id):
        hashes[f"foto_{record['phase']}_{record['filename']}"] = record["hash"]
    return hashes


def generate_verification_token() -> str:
    return secrets.token_urlsafe(18)


def generate_hash_register_pdf(booking, case_path: Path, hashes: dict[str, str], verification_token: str) -> str:
    """Create a separate verification PDF listing SHA-256 hashes for all generated documents."""
    path = case_path / "hashregister.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "Hashregister – Offroad Bumpis")
    y -= 34
    c.setFont("Helvetica", 10)
    lines = [
        f"Bokning: #{booking['id']}",
        f"Period: {format_period(booking['start_date'], booking['end_date'])}",
        f"Skapat: {datetime.now().isoformat(timespec='seconds')}",
        "Algoritm: SHA-256",
        f"Publik verifiering: /verify/{verification_token}",
        "",
        "Detta register används för att kontrollera att PDF-filerna inte har ändrats efter skapande.",
        "Om en PDF ändras får den en annan SHA-256-hash.",
        "",
    ]
    for line in lines:
        c.drawString(40, y, line)
        y -= 15

    labels = [
        ("Hyresavtal", "agreement"),
        ("Villkor", "terms"),
        ("Checklista utlämning", "handover"),
        ("Checklista återlämning", "return"),
        ("Faktura / betalningsuppgifter", "payment_invoice"),
        ("Ifylld utlämningskontroll", "handover_control"),
        ("Ifylld återlämningskontroll", "return_control"),
        ("Skadefaktura", "damage_invoice"),
    ]

    photo_labels = []
    for key in sorted(hashes.keys()):
        if key.startswith("foto_utlamning_"):
            photo_labels.append((f"Foto utlämning: {key.replace('foto_utlamning_', '')}", key))
        elif key.startswith("foto_aterlamning_"):
            photo_labels.append((f"Foto återlämning: {key.replace('foto_aterlamning_', '')}", key))

    for label, key in labels + photo_labels:
        value = hashes.get(key)
        if not value:
            continue
        if y < 90:
            c.showPage()
            y = 800
            c.setFont("Helvetica", 10)
        c.setFont("Helvetica-Bold", 10)
        y = draw_wrapped(c, label, 40, y, max_chars=82, step=12)
        c.setFont("Courier", 8)
        c.drawString(40, y, value[:64])
        y -= 18

    c.save()
    return str(path)



def business_days_before(start_date_str: str, business_days: int = 3) -> str:
    """Return date string N business days before start date, excluding Saturday/Sunday."""
    current = parse_date(start_date_str)
    remaining = business_days
    while remaining > 0:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current.isoformat()


def sek(amount: int | float) -> str:
    if isinstance(amount, float) and not amount.is_integer():
        return f"{amount:,.2f} kr".replace(",", " ").replace(".", ",")
    return f"{int(amount):,} kr".replace(",", " ")


def generate_payment_invoice_pdf(booking: sqlite3.Row, case_path: Path) -> str:
    """Create payment invoice with bank transfer, Swish and Stripe payment options."""
    path = case_path / "faktura_betalning.pdf"
    rental_days = rental_day_count(booking["start_date"], booking["end_date"])
    child_unit_price = CHILD_PRICE_LADDER.get(int(booking["child_count"]), 0)
    adult_unit_price = ADULT_PRICE_LADDER.get(int(booking["adult_count"]), 0)
    child_price = child_unit_price * rental_days
    adult_price = adult_unit_price * rental_days
    addon_total = addons_price(booking["tournament_kit"], booking["car_rental"], booking["cargo_bike"], rental_days)
    delivery_total = delivery_price(booking["deliver"], booking["return_delivery"], booking["delivery_zone"])
    subtotal = subtotal_price_for_booking(booking)
    discount_percent = int(booking_value(booking, "discount_percent", 0) or 0)
    discount_amount = booking_discount_amount(booking)
    coupon_code = booking_value(booking, "coupon_code") or "-"
    total = total_price_for_booking(booking)
    ex_vat, vat_amount, total_including_vat = vat_breakdown_from_total(total, 25)
    due_date = business_days_before(booking["start_date"], 3)
    zone = DELIVERY_ZONES.get(booking["delivery_zone"] or "pickup", DELIVERY_ZONES["pickup"])
    ways = (1 if int(booking["deliver"] or 0) else 0) + (1 if int(booking["return_delivery"] or 0) else 0)

    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "Faktura / betalningsuppgifter – Offroad Bumpis")
    y -= 32
    c.setFont("Helvetica", 10)

    lines = [
        *seller_invoice_lines(),
        "",
        f"Fakturanummer: OB-{int(booking['id']):04d}",
        f"Fakturadatum: {date.today().isoformat()}",
        f"Bokning: #{booking['id']}",
        "",
        "Köpare / kund",
        f"Kund: {booking['name']}",
        *customer_extra_lines(booking),
        f"E-post: {booking['email']}",
        f"Telefon: {booking['phone'] or '-'}",
        f"Period: {format_period(booking['start_date'], booking['end_date'])}",
        f"Hyresdagar/prisdagar: {rental_days}",
        f"Betalas senast: {due_date} (3 arbetsdagar före utlämning)",
        "",
        "Specifikation",
        f"Barnbollar: {booking['child_count']} st – {sek(child_unit_price)} × {rental_days} = {sek(child_price)}",
        f"Vuxenbollar: {booking['adult_count']} st – {sek(adult_unit_price)} × {rental_days} = {sek(adult_price)}",
    ]
    if int(booking["tournament_kit"] or 0):
        lines.append(f"Turneringskit – {sek(ADDON_PRICES['tournament_kit'])}")
    if int(booking["car_rental"] or 0):
        lines.append(f"Kombibil – {sek(ADDON_PRICES['car_rental'])} × {rental_days} = {sek(ADDON_PRICES['car_rental'] * rental_days)}")
    if int(booking["cargo_bike"] or 0):
        lines.append(f"Ellådcykel – {sek(ADDON_PRICES['cargo_bike'])} × {rental_days} = {sek(ADDON_PRICES['cargo_bike'] * rental_days)}")
    if ways:
        lines.append(f"Leveranszon: {zone['label']} – {sek(zone['price'])} per enkel väg")
        if int(booking["deliver"] or 0):
            lines.append(f"Leverans – {sek(zone['price'])}")
        if int(booking["return_delivery"] or 0):
            lines.append(f"Återleverans/hämtning efteråt – {sek(zone['price'])}")
    else:
        lines.append("Hämtning/lämning själv i Malmö – 0 kr")
    lines += [
        "",
        f"Tillval totalt: {sek(addon_total)}",
        f"Leverans totalt: {sek(delivery_total)}",
        f"Delsumma före rabatt: {sek(subtotal)}",
    ]
    if discount_percent > 0:
        lines.append(f"Rabattkod: {coupon_code} ({discount_percent}% rabatt)")
        lines.append(f"Rabatt: -{sek(discount_amount)}")
    lines += [
        f"Belopp exkl. moms: {sek(ex_vat)}",
        f"Moms 25 %: {sek(vat_amount)}",
        f"Belopp att betala inkl. moms: {sek(total_including_vat)}",
        "",
        "Betalningsalternativ",
        f"Swish: {PAYMENT_SWISH}",
        f"Stripe/kort/Klarna: {PAYMENT_STRIPE_URL}",
        "",
        "Banköverföring",
        f"Bank: {PAYMENT_BANK_NAME}",
        f"Clearingnummer: {PAYMENT_CLEARING}",
        f"Kontonummer: {PAYMENT_ACCOUNT}",
        f"IBAN: {PAYMENT_IBAN}",
        f"BIC: {PAYMENT_BIC}",
        f"Notering BIC: {PAYMENT_BIC_NOTE}",
        "",
        f"Meddelande/OCR: {booking['phone'] or '-'}",
    ]

    for line in lines:
        if y < 70:
            c.showPage()
            y = 800
            c.setFont("Helvetica", 10)
        if line in {"Säljare / uthyrare", "Köpare / kund", "Specifikation", "Betalningsalternativ", "Banköverföring"}:
            y -= 6
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, line)
            c.setFont("Helvetica", 10)
        else:
            c.drawString(40, y, line)
        y -= 15
    c.save()
    return str(path)


def generate_handover_control_pdf(
    booking: sqlite3.Row,
    case_path: Path,
    handed_child: int,
    handed_adult: int,
    count_ok: bool,
    condition_ok: bool,
    pump_included: bool,
    rules_reviewed: bool,
    notes: str,
    photo_records: list[dict[str, str]] | None = None,
) -> str:
    """Create filled handover control PDF from admin checkboxes."""
    path = case_path / "utlamningskontroll_ifylld.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "Ifylld utlämningskontroll – Offroad Bumpis")
    y -= 34
    c.setFont("Helvetica", 10)
    lines = [
        f"Bokning: #{booking['id']}",
        f"Kund: {booking['name']}",
        f"Period: {format_period(booking['start_date'], booking['end_date'])}",
        f"Kontroll utförd: {datetime.now().isoformat(timespec='seconds')}",
        f"Bokade bollar: Barn {booking['child_count']}, vuxen {booking['adult_count']}",
        f"Utlämnade bollar: Barn {handed_child}, vuxen {handed_adult}",
        f"Tillval: {selected_addons_text(booking)}",
        f"Leveranszon: {DELIVERY_ZONES.get(booking['delivery_zone'] or 'pickup', DELIVERY_ZONES['pickup'])['label']}",
        "",
    ]
    for line in lines:
        c.drawString(40, y, line)
        y -= 15

    def box(label: str, checked: bool):
        nonlocal y
        c.setFont("Helvetica", 11)
        c.rect(40, y - 2, 10, 10)
        if checked:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(42, y - 1, "X")
        c.setFont("Helvetica", 11)
        c.drawString(60, y, label)
        y -= 24

    box("Antal utlämnade bollar stämmer", count_ok)
    box("Ventiler, remmar och synliga skador är kontrollerade och OK vid utlämning", condition_ok)
    box("Pump, batteri/laddare och instruktioner är lämnade enligt bokning", pump_included)
    box("Tillåtna underlag och säkerhetsregler är genomgångna", rules_reviewed)
    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Anteckningar")
    y -= 18
    c.setFont("Helvetica", 10)
    y = draw_wrapped(c, notes or "Inga anteckningar.", 40, y)

    photos = photo_records or []
    if photos:
        y -= 10
        if y < 120:
            c.showPage()
            y = 800
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Bifogade foton")
        y -= 18
        c.setFont("Helvetica", 9)
        for photo in photos:
            if y < 90:
                c.showPage()
                y = 800
                c.setFont("Helvetica", 9)
            y = draw_wrapped(c, f"Foto: {photo['filename']}", 40, y, max_chars=86, step=12)
            c.setFont("Courier", 7)
            c.drawString(40, y, f"SHA-256: {photo['hash'][:64]}")
            y -= 15
            c.setFont("Helvetica", 9)

    c.save()
    return str(path)



def generate_return_control_pdf(
    booking: sqlite3.Row,
    case_path: Path,
    returned_child: int,
    returned_adult: int,
    returned_count_ok: bool,
    condition_ok: bool,
    cleaning_needed: bool,
    damage_invoice_needed: bool,
    notes: str,
    photo_records: list[dict[str, str]] | None = None,
) -> str:
    """Create filled return control PDF from admin checkboxes."""
    path = case_path / "aterlamningskontroll_ifylld.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "Ifylld återlämningskontroll – Offroad Bumpis")
    y -= 34
    c.setFont("Helvetica", 10)

    lines = [
        f"Bokning: #{booking['id']}",
        f"Kund: {booking['name']}",
        f"Period: {format_period(booking['start_date'], booking['end_date'])}",
        f"Kontroll utförd: {datetime.now().isoformat(timespec='seconds')}",
        f"Bokade bollar: Barn {booking['child_count']}, vuxen {booking['adult_count']}",
        f"Återlämnade bollar: Barn {returned_child}, vuxen {returned_adult}",
        "",
    ]
    for line in lines:
        c.drawString(40, y, line)
        y -= 15

    def box(label: str, checked: bool):
        nonlocal y
        c.setFont("Helvetica", 11)
        c.rect(40, y - 2, 10, 10)
        if checked:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(42, y - 1, "X")
        c.setFont("Helvetica", 11)
        c.drawString(60, y, label)
        y -= 24

    box("Antal återlämnade bollar stämmer", returned_count_ok)
    box("Ventiler, remmar och synliga skador är kontrollerade och OK", condition_ok)
    box("Rengöring behövs", cleaning_needed)
    box("Skadefaktura behöver skapas", damage_invoice_needed)

    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Anteckningar")
    y -= 18
    c.setFont("Helvetica", 10)
    y = draw_wrapped(c, notes or "Inga anteckningar.", 40, y)

    photos = photo_records or []
    if photos:
        y -= 10
        if y < 120:
            c.showPage()
            y = 800
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Bifogade foton")
        y -= 18
        c.setFont("Helvetica", 9)
        for photo in photos:
            if y < 90:
                c.showPage()
                y = 800
                c.setFont("Helvetica", 9)
            y = draw_wrapped(c, f"Foto: {photo['filename']}", 40, y, max_chars=86, step=12)
            c.setFont("Courier", 7)
            c.drawString(40, y, f"SHA-256: {photo['hash'][:64]}")
            y -= 15
            c.setFont("Helvetica", 9)

    c.save()
    return str(path)



def build_case_hashes(current_case, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Collect available hashes from a safe_case row."""
    hashes = {}
    if current_case:
        mapping = {
            "agreement": "agreement_hash",
            "terms": "terms_hash",
            "handover": "handover_hash",
            "return": "return_hash",
            "payment_invoice": "payment_invoice_hash",
            "handover_control": "handover_control_hash",
            "return_control": "return_control_hash",
            "damage_invoice": "damage_invoice_hash",
        }
        for key, column in mapping.items():
            try:
                value = current_case[column]
            except (KeyError, IndexError):
                value = None
            if value:
                hashes[key] = value
    if extra:
        hashes.update({k: v for k, v in extra.items() if v})
    return hashes



def release_unpaid_overdue_bookings() -> int:
    """Release direct bookings that are still unpaid after payment due date."""
    db = get_db()
    rows = db.execute(
        "SELECT id, start_date FROM bookings WHERE status = 'booked_unpaid'"
    ).fetchall()
    released = 0
    today = date.today().isoformat()
    for row in rows:
        due = business_days_before(row["start_date"], 3)
        if today > due:
            db.execute("UPDATE bookings SET status = 'released' WHERE id = ?", (row["id"],))
            released += 1
    if released:
        db.commit()
    return released




def draw_wrapped(c: canvas.Canvas, text: str, x: int, y: int, max_chars: int = 88, step: int = 13) -> int:
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) > max_chars:
            c.drawString(x, y, line)
            y -= step
            line = word
        else:
            line = candidate
    if line:
        c.drawString(x, y, line)
        y -= step
    return y


def generate_agreement_pdf(booking: sqlite3.Row, case_path: Path) -> str:
    path = case_path / "hyresavtal.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "Hyresavtal – Offroad Bumpis")
    y -= 35
    c.setFont("Helvetica", 10)
    lines = [
        "Uthyrare",
        f"{SELLER_COMPANY} / {SELLER_BRAND}",
        f"Organisationsnummer: {SELLER_ORG_NUMBER}",
        f"Momsregistreringsnummer: {SELLER_VAT_NUMBER}",
        f"Adress / utlämningsadress: {SELLER_ADDRESS}",
        f"E-post: {SELLER_EMAIL}",
        f"Telefon: {SELLER_PHONE}",
        "",
        f"Bokning: #{booking['id']}",
        f"Hyrestagare: {booking['name']}",
        *customer_extra_lines(booking),
        f"E-post: {booking['email']}",
        f"Telefon: {booking['phone'] or '-'}",
        f"Period: {format_period(booking['start_date'], booking['end_date'])}",
        f"Hyresdagar/prisdagar: {rental_day_count(booking['start_date'], booking['end_date'])}",
        f"Barnbollar: {booking['child_count']}",
        f"Vuxenbollar: {booking['adult_count']}",
        f"Leverans: {'Ja' if booking['deliver'] else 'Nej'}",
        f"Återleverans/hämtning efteråt: {'Ja' if booking['return_delivery'] else 'Nej'}",
        f"Leveranszon: {DELIVERY_ZONES.get(booking['delivery_zone'] or 'pickup', DELIVERY_ZONES['pickup'])['label']}",
        f"Tillval: {selected_addons_text(booking)}",
        f"Totalpris: {sek(total_price_for_booking(booking))}",
        f"Plats/adress: {booking['location'] or '-'}",
    ]
    for line in lines:
        c.drawString(40, y, line)
        y -= 15
    y -= 15
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Kort sammanfattning")
    y -= 18
    c.setFont("Helvetica", 10)
    for item in [
        "Utrustningen ska användas på mjukt underlag, till exempel gräs, konstgräs eller idrottshall.",
        "Hyrestagaren ansvarar för utrustningen under hyresperioden.",
        "Skador, förlust eller onormalt slitage kan debiteras efter återlämning.",
        "En ansvarig vuxen ska finnas på plats under användning.",
    ]:
        y = draw_wrapped(c, f"• {item}", 50, y)

    addon_terms = selected_addon_terms(booking)
    if addon_terms:
        y -= 10
        if y < 90:
            c.showPage()
            y = 800
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Villkor för valda tillval")
        y -= 18
        c.setFont("Helvetica", 10)

        for term in addon_terms:
            if y < 90:
                c.showPage()
                y = 800
                c.setFont("Helvetica", 10)
            y = draw_wrapped(c, f"• {term}", 50, y)
            y -= 5

    c.setFont("Helvetica", 8)
    c.drawString(40, 40, "Genererat av bokningssystemet. Kontrollera SHA-256-hash i adminvyn.")
    c.save()
    return str(path)


def generate_terms_pdf(case_path: Path) -> str:
    path = case_path / "villkor.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "Hyresvillkor – Offroad Bumpis")
    y -= 35
    c.setFont("Helvetica", 10)
    terms = [
        "Bumperballs får användas på mjuka och jämna underlag. Asfalt, grus, betong, is och hårda ojämna ytor är inte tillåtna.",
        "En person per bumperball gäller. Ansvarig vuxen ska övervaka aktiviteten.",
        "Utrustningen ska återlämnas i samma skick som vid utlämning, med normalt slitage undantaget.",
        "Skador eller saknad utrustning ska meddelas direkt och kan leda till skadefaktura.",
        "Betalning och avbokning sker enligt överenskommelse/faktura.",
    ]
    for i, term in enumerate(terms, 1):
        y = draw_wrapped(c, f"{i}. {term}", 40, y)
        y -= 8
    c.save()
    return str(path)


def generate_checklist_pdf(case_path: Path, filename: str, title: str, items: list[str]) -> str:
    path = case_path / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, title)
    y -= 35
    c.setFont("Helvetica", 11)
    for item in items:
        c.rect(40, y - 2, 10, 10)
        y = draw_wrapped(c, item, 60, y, max_chars=80, step=16)
        y -= 5
    c.save()
    return str(path)


def generate_damage_invoice_pdf(booking: sqlite3.Row, case_path: Path, description: str, cost: float) -> str:
    """Create damage invoice PDF with payment details."""
    path = case_path / "skadefaktura.pdf"
    issue_date = date.today()
    due_date = issue_date + timedelta(days=14)

    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800

    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "Skadefaktura - Offroad Bumpis")
    y -= 32

    c.setFont("Helvetica", 10)
    header_lines = [
        *seller_invoice_lines(),
        "",
        f"Skadefakturanummer: SK-{int(booking['id']):04d}",
        f"Utfärdad: {issue_date.isoformat()}",
        f"Betalas senast: {due_date.isoformat()} (14 dagar från utfärdande)",
        f"Bokning: #{booking['id']}",
        "",
        "Köpare / hyrestagare",
        f"Hyrestagare: {booking['name']}",
        *customer_extra_lines(booking),
        f"E-post: {booking['email']}",
        f"Telefon: {booking['phone'] or '-'}",
        f"Period: {format_period(booking['start_date'], booking['end_date'])}",
        f"Belopp att betala: {cost:.2f} kr",
    ]

    for line in header_lines:
        c.drawString(40, y, line)
        y -= 15

    y -= 8
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Beskrivning")
    y -= 18
    c.setFont("Helvetica", 10)
    draw_wrapped(c, description or "Ingen beskrivning angiven.", 40, y)

    y -= 18
    if y < 280:
        c.showPage()
        y = 800
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Betalningsalternativ")
    y -= 18
    c.setFont("Helvetica", 10)

    payment_lines = [
        f"Swish: {PAYMENT_SWISH}",
        f"Stripe/kort/Klarna: {PAYMENT_STRIPE_URL}",
        "",
        "Banköverföring",
        f"Bank: {PAYMENT_BANK_NAME}",
        f"Clearingnummer: {PAYMENT_CLEARING}",
        f"Kontonummer: {PAYMENT_ACCOUNT}",
        f"IBAN: {PAYMENT_IBAN}",
        f"BIC: {PAYMENT_BIC}",
        f"Notering BIC: {PAYMENT_BIC_NOTE}",
        "",
        f"Meddelande/OCR: {booking['phone'] or '-'}",
    ]

    for line in payment_lines:
        if line == "Banköverföring":
            y -= 8
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, line)
            c.setFont("Helvetica", 10)
        elif line == "":
            y -= 8
        else:
            c.drawString(40, y, line)
        y -= 15

    c.save()
    return str(path)


@app.route("/", methods=["GET", "POST"])
def booking_form():
    release_unpaid_overdue_bookings()

    if request.method == "POST":
        requested_date = request.form.get("date", "").strip()
        requested_end_date = request.form.get("end_date", "").strip()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        customer_type = request.form.get("customer_type", "private").strip()
        if customer_type not in {"private", "company"}:
            customer_type = "private"
        company_name = request.form.get("company_name", "").strip()
        org_number = request.form.get("org_number", "").strip()
        invoice_reference = request.form.get("invoice_reference", "").strip()
        location = request.form.get("location", "").strip()
        message = request.form.get("message", "").strip()
        coupon_code = normalize_coupon_code(request.form.get("coupon_code", ""))
        discount_percent = coupon_discount_percent(coupon_code) if coupon_code else 0
        deliver = 1 if request.form.get("deliver") == "on" else 0
        return_delivery = 1 if request.form.get("return_delivery") == "on" else 0
        delivery_zone = request.form.get("delivery_zone", "pickup").strip() or "pickup"
        tournament_kit = 1 if request.form.get("tournament_kit") == "on" else 0
        car_rental = 1 if request.form.get("car_rental") == "on" else 0
        cargo_bike = 1 if request.form.get("cargo_bike") == "on" else 0
        try:
            child_count = int(request.form.get("child", "0"))
            adult_count = int(request.form.get("adult", "0"))
        except ValueError:
            child_count = adult_count = 0

        template_context = {
            "form_data": request.form,
            "inventory": BALL_INVENTORY,
            "adult_available_from": ADULT_AVAILABLE_FROM.isoformat(),
            "adult_available_from_sv": "1 september 2026",
            "child_price_ladder": CHILD_PRICE_LADDER,
            "adult_price_ladder": ADULT_PRICE_LADDER,
            "addon_prices": ADDON_PRICES,
            "delivery_zones": DELIVERY_ZONES,
            "coupon_codes": COUPON_CODES,
        }

        if not requested_date or not name or not email or not phone:
            return render_template("booking_form.html", error="Fyll i datum, namn, e-post och telefon. Telefon används som meddelande/OCR vid betalning.", **template_context)
        if customer_type == "company" and not company_name:
            return render_template("booking_form.html", error="Fyll i företagsnamn om bokningen gäller ett företag.", **template_context)
        if child_count <= 0 and adult_count <= 0:
            return render_template("booking_form.html", error="Välj minst en boll.", **template_context)
        if child_count % 2 != 0 or adult_count % 2 != 0:
            return render_template("booking_form.html", error="Bollar bokas i jämna antal, till exempel 2, 4, 6, 8, 10 eller 12.", **template_context)
        if coupon_code and discount_percent <= 0:
            return render_template("booking_form.html", error="Rabattkoden hittades inte. Kontrollera stavningen eller lämna fältet tomt.", **template_context)
        if delivery_zone not in DELIVERY_ZONES:
            return render_template("booking_form.html", error="Välj en giltig leveranszon.", **template_context)
        if (deliver or return_delivery) and delivery_zone == "pickup":
            return render_template("booking_form.html", error="Välj leveranszon när du vill ha leverans eller återleverans.", **template_context)
        if not (deliver or return_delivery):
            delivery_zone = "pickup"
        if cargo_bike and (child_count + adult_count) > 4:
            return render_template("booking_form.html", error="Ellådcykel kan bara bokas för upp till 4 bollar. Välj färre bollar, ta bort ellådcykel eller välj kombibil/leverans.", **template_context)

        try:
            start_date, end_date = booking_period(requested_date, requested_end_date)
        except ValueError:
            return render_template("booking_form.html", error="Kontrollera startdatum och slutdatum. Slutdatum kan inte vara före startdatum.", **template_context)

        remaining = remaining_for_period(start_date, end_date)
        if adult_count > 0 and parse_date(start_date) < ADULT_AVAILABLE_FROM:
            return render_template("booking_form.html", error="Vuxenbollar kan bokas från och med 1 september 2026.", **template_context)
        if child_count > remaining["barn"] or adult_count > remaining["vuxen"]:
            period_text = format_period(start_date, end_date)
            return render_template(
                "booking_form.html",
                error=f"Det finns bara {remaining['barn']} barnbollar och {remaining['vuxen']} vuxenbollar kvar under perioden {period_text}.",
                **template_context,
            )

        rental_days = rental_day_count(start_date, end_date)
        subtotal = subtotal_price(child_count, adult_count, deliver, return_delivery, delivery_zone, tournament_kit, car_rental, cargo_bike, rental_days)
        discount_amount = discount_amount_for_subtotal(subtotal, discount_percent)
        estimated_price = total_after_discount(subtotal, discount_percent)
        db = get_db()
        cur = db.execute(
            """
            INSERT INTO bookings (created_at, start_date, end_date, child_count, adult_count, name, email, phone, customer_type, company_name, org_number, invoice_reference, location, deliver, return_delivery, delivery_zone, tournament_kit, car_rental, cargo_bike, coupon_code, discount_percent, message, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'booked_unpaid')
            """,
            (datetime.now().isoformat(timespec="seconds"), start_date, end_date, child_count, adult_count, name, email, phone, customer_type, company_name or None, org_number or None, invoice_reference or None, location, deliver, return_delivery, delivery_zone, tournament_kit, car_rental, cargo_bike, coupon_code or None, discount_percent, message),
        )
        booking_id = cur.lastrowid
        db.commit()

        case = create_safe_case_for_booking(booking_id)
        period_text = format_period(start_date, end_date)
        due_date = business_days_before(start_date, 3)
        invoice_file = case["payment_invoice_file"] if case and case["payment_invoice_file"] else None
        verify_url = url_for("public_verify", token=case["verification_token"], _external=True) if case and case["verification_token"] else ""
        customer_email_lines = f"Bokar som: {'Företag' if customer_type == 'company' else 'Privatperson'}\n"
        if customer_type == "company":
            customer_email_lines += f"Företag: {company_name}\n"
            customer_email_lines += f"Organisationsnummer: {org_number or '-'}\n"
            customer_email_lines += f"Fakturareferens/PO: {invoice_reference or '-'}\n"

        send_email(
            email,
            "Din bokning och faktura - Offroad Bumpis",
            (
                f"Hej {name}!\n\n"
                f"Din bokning för {period_text} är reserverad.\n\n"
                f"Hyresdagar/prisdagar: {rental_days}\n"
                f"Barnbollar: {child_count}\n"
                f"Vuxenbollar: {adult_count}\n"
                f"Pris före rabatt: {subtotal} kr\n"
                f"Rabattkod: {coupon_code or '-'}\n"
                f"Rabatt: {discount_percent}% (-{discount_amount} kr)\n"
                f"Pris att betala: {estimated_price} kr\n"
                f"Leverans: {'Ja' if deliver else 'Nej'}\n"
                f"Återleverans/hämtning efteråt: {'Ja' if return_delivery else 'Nej'}\n"
                f"Leveranszon: {DELIVERY_ZONES[delivery_zone]['label']}\n"
                f"Tillval: {', '.join([ADDON_LABELS[k] for k, selected in {'tournament_kit': tournament_kit, 'car_rental': car_rental, 'cargo_bike': cargo_bike}.items() if selected]) or '-'}\n\n"
                f"Fakturan/betalningsuppgifterna finns bifogad som PDF.\n"
                f"Betala senast {due_date}, alltså senast 3 arbetsdagar före utlämning.\n"
                f"Meddelande/OCR vid banköverföring eller Swish: {phone}\n\n"
                f"Betalning kan göras via Swish, banköverföring eller Stripe/kort/Klarna:\n{PAYMENT_STRIPE_URL}\n\n"
                "Om betalning inte kommer in i tid släpps bokningen.\n\n"
                f"Verifiering av dokument: {verify_url}\n\n"
                "Offroad Bumpis"
            ),
            attachments=[invoice_file] if invoice_file else None,
        )
        send_email(
            ADMIN_EMAIL,
            "Ny direktbokning - Offroad Bumpis",
            (
                f"Ny direktbokning har kommit in.\n\n"
                f"Period: {period_text}\n"
                f"Hyresdagar/prisdagar: {rental_days}\n"
                f"Barnbollar: {child_count}\n"
                f"Vuxenbollar: {adult_count}\n"
                f"Pris före rabatt: {subtotal} kr\n"
                f"Rabattkod: {coupon_code or '-'}\n"
                f"Rabatt: {discount_percent}% (-{discount_amount} kr)\n"
                f"Pris att betala: {estimated_price} kr\n"
                f"Betalas senast: {due_date}\n"
                f"Kund: {name}\n"
                f"E-post: {email}\n"
                f"Telefon/OCR: {phone}\n"
                f"Plats: {location or '-'}\n"
                f"Leverans: {'Ja' if deliver else 'Nej'}\n"
                f"Återleverans/hämtning efteråt: {'Ja' if return_delivery else 'Nej'}\n"
                f"Leveranszon: {DELIVERY_ZONES[delivery_zone]['label']}\n"
                f"Tillval: {', '.join([ADDON_LABELS[k] for k, selected in {'tournament_kit': tournament_kit, 'car_rental': car_rental, 'cargo_bike': cargo_bike}.items() if selected]) or '-'}\n"
                f"Meddelande: {message or '-'}\n\n"
                f"Case och faktura är skapade automatiskt. Verifiering: {verify_url}"
            ),
        )
        fresh_booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if coupon_code:
            send_affiliate_booking_email(fresh_booking, coupon_code)
        return render_template("thank_you.html", date=period_text, due_date=due_date)

    return render_template(
        "booking_form.html",
        inventory=BALL_INVENTORY,
        adult_available_from=ADULT_AVAILABLE_FROM.isoformat(),
        adult_available_from_sv="1 september 2026",
        child_price_ladder=CHILD_PRICE_LADDER,
        adult_price_ladder=ADULT_PRICE_LADDER,
        addon_prices=ADDON_PRICES,
        delivery_zones=DELIVERY_ZONES,
        coupon_codes=COUPON_CODES,
    )


@app.route("/calendar")
def calendar_view():
    release_unpaid_overdue_bookings()
    today = date.today()
    first_month = date(today.year, today.month, 1)
    months = []
    for offset in range(6):
        month_num = first_month.month + offset
        year = first_month.year + (month_num - 1) // 12
        month = ((month_num - 1) % 12) + 1
        month_start = date(year, month, 1)
        weeks = []
        for week in pycalendar.monthcalendar(year, month):
            week_data = []
            for day in week:
                if day == 0:
                    week_data.append(None)
                    continue
                current = date(year, month, day)
                d = current.isoformat()
                available = remaining_on_date(d)
                inventory = inventory_for_date(d)
                adult_active = current >= ADULT_AVAILABLE_FROM
                if available["barn"] == 0 and (not adult_active or available["vuxen"] == 0):
                    color = "#f8d7da"
                elif available["barn"] < inventory["barn"] or (adult_active and available["vuxen"] < inventory["vuxen"]):
                    color = "#fff3cd"
                else:
                    color = "#d4edda"
                week_data.append({"date": d, "available": available, "inventory": inventory, "color": color, "adult_active": adult_active})
            weeks.append(week_data)
        months.append({"month_name": month_start.strftime("%B"), "year": year, "weeks": weeks})
    return render_template(
        "calendar.html",
        months=months,
        weekday_names=["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"],
        inventory=BALL_INVENTORY,
        adult_available_from_sv="1 september 2026",
    )


@app.route("/admin")
def admin_index():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_bookings"))
    return redirect(url_for("admin_login"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_bookings"))
        return render_template("admin_login.html", error="Fel lösenord.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin/bookings")
@admin_required
def admin_bookings():
    release_unpaid_overdue_bookings()
    db = get_db()
    bookings = db.execute(
        """
        SELECT b.*, c.id AS case_id, c.status AS case_status
        FROM bookings b
        LEFT JOIN safe_cases c ON c.booking_id = b.id
        ORDER BY b.created_at DESC
        """
    ).fetchall()
    booking_rows = []
    for b in bookings:
        item = dict(b)
        item["price_from"] = total_price_for_booking(item)
        item["period_text"] = format_period(item["start_date"], item["end_date"])
        booking_rows.append(item)
    return render_template("admin_bookings.html", bookings=booking_rows, total_balls=TOTAL_BALLS)



def create_safe_case_for_booking(booking_id: int):
    """Create documents, hashes, hash register and public verification token for a confirmed booking."""
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        return None

    existing = db.execute("SELECT * FROM safe_cases WHERE booking_id = ?", (booking_id,)).fetchone()
    if existing:
        return existing

    case_path = ensure_case_directory(booking_id)
    agreement = generate_agreement_pdf(booking, case_path)
    terms = generate_terms_pdf(case_path)
    handover = generate_checklist_pdf(case_path, "checklista_utlamning.pdf", "Checklista utlämning", [
        "Räkna antal bollar.",
        "Kontrollera ventiler, remmar och synliga skador.",
        "Lämna med pump och instruktioner.",
        "Gå igenom tillåtna underlag och säkerhetsregler.",
    ])
    returned = generate_checklist_pdf(case_path, "checklista_aterlamning.pdf", "Checklista återlämning", [
        "Räkna antal återlämnade bollar.",
        "Kontrollera ventiler, remmar och synliga skador.",
        "Notera om rengöring behövs.",
        "Markera om skadefaktura behöver skapas.",
    ])

    agreement_hash = hash_file(agreement)
    terms_hash = hash_file(terms)
    handover_hash = hash_file(handover)
    return_hash = hash_file(returned)
    payment_invoice = generate_payment_invoice_pdf(booking, case_path)
    payment_invoice_hash = hash_file(payment_invoice)
    verification_token = generate_verification_token()
    hash_register = generate_hash_register_pdf(
        booking,
        case_path,
        {
            "agreement": agreement_hash,
            "terms": terms_hash,
            "handover": handover_hash,
            "return": return_hash,
            "payment_invoice": payment_invoice_hash,
        },
        verification_token,
    )
    hash_register_hash = hash_file(hash_register)

    db.execute(
        """
        INSERT INTO safe_cases (
            booking_id, created_at,
            agreement_file, terms_file, handover_file, return_file, payment_invoice_file, hash_register_file,
            verification_token,
            agreement_hash, terms_hash, handover_hash, return_hash, payment_invoice_hash, hash_register_hash,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """,
        (
            booking_id,
            datetime.now().isoformat(timespec="seconds"),
            agreement,
            terms,
            handover,
            returned,
            payment_invoice,
            hash_register,
            verification_token,
            agreement_hash,
            terms_hash,
            handover_hash,
            return_hash,
            payment_invoice_hash,
            hash_register_hash,
        ),
    )
    db.commit()
    return db.execute("SELECT * FROM safe_cases WHERE booking_id = ?", (booking_id,)).fetchone()


@app.post("/admin/bookings/<int:booking_id>/<action>")
@admin_required
def admin_update_booking(booking_id: int, action: str):
    if action not in {"confirm", "reject", "paid", "release"}:
        return redirect(url_for("admin_bookings"))

    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        return redirect(url_for("admin_bookings"))

    if action == "paid":
        db.execute("UPDATE bookings SET status = 'paid' WHERE id = ?", (booking_id,))
        db.commit()
        send_email(
            booking["email"],
            "Betalning registrerad - Offroad Bumpis",
            f"Hej {booking['name']}!\n\nDin betalning för {format_period(booking['start_date'], booking['end_date'])} är registrerad.\n\nOffroad Bumpis",
        )
        send_affiliate_paid_email(booking)
    elif action == "release":
        db.execute("UPDATE bookings SET status = 'released' WHERE id = ?", (booking_id,))
        db.commit()
        send_email(
            booking["email"],
            "Bokning släppt - Offroad Bumpis",
            f"Hej {booking['name']}!\n\nDin bokning för {format_period(booking['start_date'], booking['end_date'])} har släppts eftersom betalning inte är registrerad i tid.\n\nOffroad Bumpis",
        )
    elif action == "confirm":
        db.execute("UPDATE bookings SET status = 'booked_unpaid' WHERE id = ?", (booking_id,))
        db.commit()
        create_safe_case_for_booking(booking_id)
    elif action == "reject":
        db.execute("UPDATE bookings SET status = 'rejected' WHERE id = ?", (booking_id,))
        db.commit()

    return redirect(url_for("admin_bookings"))


@app.post("/admin/cases/<int:booking_id>/create")
@admin_required
def admin_create_case(booking_id: int):
    case = create_safe_case_for_booking(booking_id)
    if not case:
        return redirect(url_for("admin_bookings"))
    return redirect(url_for("admin_case_view", booking_id=booking_id))


@app.route("/admin/cases/<int:booking_id>")
@admin_required
def admin_case_view(booking_id: int):
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    case = db.execute("SELECT * FROM safe_cases WHERE booking_id = ?", (booking_id,)).fetchone()
    if not booking or not case:
        return redirect(url_for("admin_bookings"))
    return render_template(
        "admin_case.html",
        booking=dict(booking),
        case=dict(case),
        handover_photos=photo_records_for_case(booking_id, "utlamning"),
        return_photos=photo_records_for_case(booking_id, "aterlamning"),
    )


@app.route("/cases/<int:booking_id>/<path:filename>")
@admin_required
def serve_case_file(booking_id: int, filename: str):
    safe_filename = file_basename(filename)
    ext = Path(safe_filename).suffix.lower()
    image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
    return send_from_directory(
        ensure_case_directory(booking_id),
        safe_filename,
        as_attachment=ext not in image_extensions,
    )





@app.route("/verify/<token>")
def public_verify(token: str):
    db = get_db()
    row = db.execute(
        """
        SELECT c.*, b.start_date, b.end_date, b.child_count, b.adult_count
        FROM safe_cases c
        JOIN bookings b ON b.id = c.booking_id
        WHERE c.verification_token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        return render_template("verify.html", found=False), 404

    data = dict(row)
    data["period_text"] = format_period(data["start_date"], data["end_date"])
    return render_template("verify.html", found=True, case=data)


@app.post("/admin/cases/<int:booking_id>/damage")
@admin_required
def admin_damage_invoice(booking_id: int):
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        return redirect(url_for("admin_bookings"))
    description = request.form.get("damage_description", "").strip()
    try:
        cost = float(request.form.get("damage_cost", "0").replace(",", "."))
    except ValueError:
        cost = 0.0
    case_path = ensure_case_directory(booking_id)
    invoice = generate_damage_invoice_pdf(booking, case_path, description, cost)
    invoice_hash = hash_file(invoice)
    current_case = db.execute("SELECT * FROM safe_cases WHERE booking_id = ?", (booking_id,)).fetchone()
    verification_token = current_case["verification_token"] if current_case and current_case["verification_token"] else generate_verification_token()
    hash_register = generate_hash_register_pdf(
        booking,
        case_path,
        build_case_hashes(current_case, {"damage_invoice": invoice_hash, **photo_hashes_for_case(booking_id)}),
        verification_token,
    )
    hash_register_hash = hash_file(hash_register)
    db.execute(
        "UPDATE safe_cases SET damage_invoice_file = ?, damage_invoice_hash = ?, hash_register_file = ?, hash_register_hash = ?, verification_token = ?, status = 'damage' WHERE booking_id = ?",
        (invoice, invoice_hash, hash_register, hash_register_hash, verification_token, booking_id),
    )
    db.commit()
    return redirect(url_for("admin_case_view", booking_id=booking_id))




@app.post("/admin/cases/<int:booking_id>/handover-control")
@admin_required
def admin_handover_control(booking_id: int):
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    current_case = db.execute("SELECT * FROM safe_cases WHERE booking_id = ?", (booking_id,)).fetchone()
    if not booking or not current_case:
        return redirect(url_for("admin_bookings"))

    try:
        handed_child = int(request.form.get("handed_child", booking["child_count"]) or 0)
        handed_adult = int(request.form.get("handed_adult", booking["adult_count"]) or 0)
    except ValueError:
        handed_child = int(booking["child_count"])
        handed_adult = int(booking["adult_count"])

    count_ok = request.form.get("handover_count_ok") == "on"
    condition_ok = request.form.get("handover_condition_ok") == "on"
    pump_included = request.form.get("pump_included") == "on"
    rules_reviewed = request.form.get("rules_reviewed") == "on"
    notes = request.form.get("handover_notes", "").strip()

    case_path = ensure_case_directory(booking_id)
    save_uploaded_photos(booking_id, "handover_photos", "utlamning")
    handover_photos = photo_records_for_case(booking_id, "utlamning")
    handover_control = generate_handover_control_pdf(
        booking,
        case_path,
        handed_child,
        handed_adult,
        count_ok,
        condition_ok,
        pump_included,
        rules_reviewed,
        notes,
        handover_photos,
    )
    handover_control_hash = hash_file(handover_control)

    verification_token = current_case["verification_token"] or generate_verification_token()
    hash_register = generate_hash_register_pdf(
        booking,
        case_path,
        build_case_hashes(current_case, {"handover_control": handover_control_hash, **photo_hashes_for_case(booking_id)}),
        verification_token,
    )
    hash_register_hash = hash_file(hash_register)

    db.execute(
        """
        UPDATE safe_cases
        SET handover_control_file = ?,
            handover_control_hash = ?,
            hash_register_file = ?,
            hash_register_hash = ?,
            verification_token = ?
        WHERE booking_id = ?
        """,
        (handover_control, handover_control_hash, hash_register, hash_register_hash, verification_token, booking_id),
    )
    db.commit()
    return redirect(url_for("admin_case_view", booking_id=booking_id))


@app.post("/admin/cases/<int:booking_id>/return-control")
@admin_required
def admin_return_control(booking_id: int):
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    current_case = db.execute("SELECT * FROM safe_cases WHERE booking_id = ?", (booking_id,)).fetchone()
    if not booking or not current_case:
        return redirect(url_for("admin_bookings"))

    try:
        returned_child = int(request.form.get("returned_child", booking["child_count"]) or 0)
        returned_adult = int(request.form.get("returned_adult", booking["adult_count"]) or 0)
    except ValueError:
        returned_child = int(booking["child_count"])
        returned_adult = int(booking["adult_count"])

    returned_count_ok = request.form.get("returned_count_ok") == "on"
    condition_ok = request.form.get("condition_ok") == "on"
    cleaning_needed = request.form.get("cleaning_needed") == "on"
    damage_invoice_needed = request.form.get("damage_invoice_needed") == "on"
    notes = request.form.get("return_notes", "").strip()

    case_path = ensure_case_directory(booking_id)
    save_uploaded_photos(booking_id, "return_photos", "aterlamning")
    return_photos = photo_records_for_case(booking_id, "aterlamning")
    return_control = generate_return_control_pdf(
        booking,
        case_path,
        returned_child,
        returned_adult,
        returned_count_ok,
        condition_ok,
        cleaning_needed,
        damage_invoice_needed,
        notes,
        return_photos,
    )
    return_control_hash = hash_file(return_control)

    verification_token = current_case["verification_token"] or generate_verification_token()
    hash_register = generate_hash_register_pdf(
        booking,
        case_path,
        build_case_hashes(current_case, {"return_control": return_control_hash, **photo_hashes_for_case(booking_id)}),
        verification_token,
    )
    hash_register_hash = hash_file(hash_register)

    db.execute(
        """
        UPDATE safe_cases
        SET return_control_file = ?,
            return_control_hash = ?,
            hash_register_file = ?,
            hash_register_hash = ?,
            verification_token = ?
        WHERE booking_id = ?
        """,
        (return_control, return_control_hash, hash_register, hash_register_hash, verification_token, booking_id),
    )
    db.commit()
    return redirect(url_for("admin_case_view", booking_id=booking_id))



with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
