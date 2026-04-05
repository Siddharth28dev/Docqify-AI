# from google import genai
import google.generativeai as genai
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, has_request_context
from functools import wraps
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import base64
import hashlib
import hmac
import io
import json
import pdfkit
import sqlite3
import traceback
import os
import uuid
from datetime import datetime, timedelta
import os

# --- App Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "admin_analytics.db")
SETTINGS_PATH = os.path.join(BASE_DIR, "admin_settings.json")

DEFAULT_GEMINI_API_KEY = ""
DEFAULT_MODEL_NAME = "gemini-flash-lite-latest"
RAZORPAY_MIN_ORDER_AMOUNT = Decimal("1.00")
DEFAULT_DOCUMENT_TOKEN_LIMIT = 1200
DEFAULT_ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "curiousrudraksh@gmail.com").strip().lower()
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Docqify#12345")

AVAILABLE_MODELS = {
    "gemini": [
        "gemini-flash-lite-latest",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ],
    "openai": [
        "gpt-4.1-nano",
        "gpt-4.1-mini",
        "gpt-4o-mini"
    ]
}

DEFAULT_SETTINGS = {
    "provider": "gemini",
    "model": DEFAULT_MODEL_NAME,
    "gemini_api_key": DEFAULT_GEMINI_API_KEY,
    "openai_api_key": "",
    "ai_usage_enabled": True,
    "razorpay_key_id": "",
    "razorpay_key_secret": "",
    "document_price": "0.00",
    "currency": "INR",
    "document_rules": {}
}

DOC_PATH_LABELS = {
    "/resume": "Resume",
    "/cv": "CV",
    "/cl": "Cover Letter",
    "/sop": "SOP",
    "/lor": "LOR",
    "/joining_letter": "Joining Letter",
    "/resignation_letter": "Resignation Letter",
    "/appraisal_letter": "Appraisal Letter",
    "/experience_letter": "Experience Letter",
    "/tc_request_letter": "TC Request Letter",
    "/promotion_letter": "Promotion Letter",
    "/relieving_letter": "Relieving Letter",
    "/increment_letter": "Increment Letter",
    "/research_proposal": "Research Proposal",
    "/grant_application_letter": "Grant Application Letter",
    "/scholarship_letter": "Scholarship Letter",
    "/termination_letter": "Termination Letter",
    "/employment_contract": "Employment Contract",
    "/grievance_letter": "Grievance Letter",
    "/rti_application": "RTI Application",
    "/official_memo": "Official Memo",
    "/government_proposal": "Government Proposal",
    "/tender_document": "Tender Document"
}

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret-for-production")


# Configure PDFKit paths based on OS
WKHTMLTOPDF_PATH = None
if os.name == 'posix':
    WKHTMLTOPDF_PATH = '/usr/bin/wkhtmltopdf'
elif os.name == 'nt':
    WKHTMLTOPDF_PATH = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'

# Verify wkhtmltopdf installation
try:
    config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
    pdfkit.from_string('<html><body><h1>Test</h1></body></html>', False, configuration=config)
except Exception as e:
    print(f"wkhtmltopdf verification failed: {str(e)}")
    WKHTMLTOPDF_PATH = None


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS visitors (
                visitor_id TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                total_requests INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS download_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                visitor_id TEXT,
                doc_path TEXT,
                doc_name TEXT,
                downloaded_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                visitor_id TEXT,
                provider TEXT,
                model TEXT,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                visitor_id TEXT,
                doc_path TEXT,
                doc_name TEXT,
                order_id TEXT UNIQUE,
                payment_id TEXT,
                signature TEXT,
                receipt TEXT,
                amount INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'INR',
                status TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                verified_at TEXT,
                download_consumed INTEGER NOT NULL DEFAULT 0,
                downloaded_at TEXT
            )
            """
        )
        conn.commit()


def load_settings():
    settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                persisted = json.load(f)
            settings.update({k: v for k, v in persisted.items() if k in settings})
        except Exception as e:
            app.logger.warning(f"Could not load settings file: {e}")
    settings.setdefault("document_rules", {})
    return settings


def save_settings(new_settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(new_settings, f, indent=2)


def mask_key(value):
    if not value:
        return "Not set"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def utc_now():
    return datetime.utcnow()


def utc_now_iso():
    return utc_now().replace(microsecond=0).isoformat()


def normalize_doc_path(path):
    return path if path in DOC_PATH_LABELS else "unknown"


def get_doc_name(doc_path):
    return DOC_PATH_LABELS.get(normalize_doc_path(doc_path), "Unknown")


def infer_doc_path():
    if not has_request_context():
        return "unknown"

    payload = request.get_json(silent=True) or {}
    doc_path = normalize_doc_path(payload.get("doc_path", ""))
    if doc_path != "unknown":
        return doc_path

    referer = request.headers.get("Referer", "")
    ref_path = urlparse(referer).path if referer else ""
    return normalize_doc_path(ref_path)


def normalize_rule_price(value, fallback_price):
    try:
        return format_price(parse_decimal_price(value))
    except Exception:
        return format_price(parse_decimal_price(fallback_price))


def normalize_rule_token_limit(value, fallback_limit=DEFAULT_DOCUMENT_TOKEN_LIMIT):
    token_limit = to_int_or_zero(value)
    return token_limit if token_limit > 0 else fallback_limit


def build_document_rule(settings, doc_path):
    fallback_price = settings.get("document_price", "0.00")
    raw_rules = settings.get("document_rules", {})
    rule = raw_rules.get(doc_path, {}) if isinstance(raw_rules, dict) else {}
    return {
        "price": normalize_rule_price(rule.get("price", fallback_price), fallback_price),
        "token_limit": normalize_rule_token_limit(
            rule.get("token_limit", DEFAULT_DOCUMENT_TOKEN_LIMIT)
        )
    }


def build_document_rules_map(settings):
    return {
        doc_path: build_document_rule(settings, doc_path)
        for doc_path in DOC_PATH_LABELS
    }


def build_document_rules_view(settings):
    rules_map = build_document_rules_map(settings)
    return [
        {
            "path": doc_path,
            "name": doc_name,
            "price": rules_map[doc_path]["price"],
            "token_limit": rules_map[doc_path]["token_limit"]
        }
        for doc_path, doc_name in DOC_PATH_LABELS.items()
    ]


def parse_decimal_price(value):
    raw_value = str(value or "0").strip()
    try:
        decimal_value = Decimal(raw_value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Document price must be a valid number")

    if decimal_value < 0:
        raise ValueError("Document price cannot be negative")

    return decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_price(decimal_value):
    return format(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def price_to_subunits(decimal_value):
    return int((decimal_value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def get_document_price_decimal(settings, doc_path=None):
    if doc_path and doc_path != "unknown":
        rule = build_document_rule(settings, doc_path)
        return parse_decimal_price(rule["price"])
    return parse_decimal_price(settings.get("document_price", "0.00"))


def payment_required(settings):
    return price_to_subunits(get_document_price_decimal(settings)) > 0


def payment_required_for_doc(settings, doc_path=None):
    return price_to_subunits(get_document_price_decimal(settings, doc_path)) > 0


def payment_ready(settings):
    document_price = get_document_price_decimal(settings)
    return (
        payment_required(settings)
        and document_price >= RAZORPAY_MIN_ORDER_AMOUNT
        and bool(settings.get("razorpay_key_id", "").strip())
        and bool(settings.get("razorpay_key_secret", "").strip())
    )


def get_razorpay_block_reason(settings, host=None, doc_path=None):
    if not payment_required_for_doc(settings, doc_path):
        return None

    amount_decimal = get_document_price_decimal(settings, doc_path)
    if amount_decimal < RAZORPAY_MIN_ORDER_AMOUNT:
        return "Paid downloads need a document price of INR 1.00 or more. Use 0.00 for free downloads."

    key_id = settings.get("razorpay_key_id", "").strip()
    key_secret = settings.get("razorpay_key_secret", "").strip()
    if not key_id or not key_secret:
        return "Razorpay credentials are missing in admin settings."

    return None


def payment_public_config(doc_path=None):
    settings = load_settings()
    amount_decimal = get_document_price_decimal(settings, doc_path)
    amount_subunits = price_to_subunits(amount_decimal)
    normalized_path = normalize_doc_path(doc_path or "")
    host = request.host if has_request_context() else None
    blocked_reason = get_razorpay_block_reason(settings, host, doc_path=normalized_path)
    return {
        "requires_payment": amount_subunits > 0,
        "payment_ready": payment_ready(settings) and not blocked_reason,
        "blocked_reason": blocked_reason,
        "key_id": settings.get("razorpay_key_id", "").strip(),
        "currency": settings.get("currency", "INR"),
        "amount": amount_subunits,
        "price_display": format_price(amount_decimal),
        "doc_path": normalized_path,
        "doc_name": get_doc_name(normalized_path)
    }


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def ensure_visitor_session():
    visitor_id = session.get("visitor_id")
    if not visitor_id:
        visitor_id = str(uuid.uuid4())
        session["visitor_id"] = visitor_id
    now = utc_now_iso()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT visitor_id FROM visitors WHERE visitor_id = ?",
            (visitor_id,)
        )
        exists = cursor.fetchone()
        if exists:
            cursor.execute(
                """
                UPDATE visitors
                SET last_seen = ?, total_requests = total_requests + 1
                WHERE visitor_id = ?
                """,
                (now, visitor_id)
            )
        else:
            cursor.execute(
                """
                INSERT INTO visitors (visitor_id, first_seen, last_seen, total_requests)
                VALUES (?, ?, ?, 1)
                """,
                (visitor_id, now, now)
            )
        conn.commit()
    return visitor_id


def record_download(visitor_id, doc_path):
    now = utc_now_iso()
    doc_name = get_doc_name(doc_path)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO download_events (visitor_id, doc_path, doc_name, downloaded_at)
            VALUES (?, ?, ?, ?)
            """,
            (visitor_id, doc_path, doc_name, now)
        )
        conn.commit()


def estimate_tokens(text):
    # Fallback approximation when provider does not return usage metadata.
    return max(1, len(text) // 4) if text else 0


def to_int_or_zero(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def extract_gemini_usage(response, prompt, text):
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    if usage is not None:
        prompt_tokens = to_int_or_zero(
            getattr(usage, "prompt_token_count", None)
            or getattr(usage, "input_token_count", None)
        )
        completion_tokens = to_int_or_zero(
            getattr(usage, "candidates_token_count", None)
            or getattr(usage, "output_token_count", None)
        )
        total_tokens = to_int_or_zero(getattr(usage, "total_token_count", None))

    if prompt_tokens == 0:
        prompt_tokens = estimate_tokens(prompt)
    if completion_tokens == 0:
        completion_tokens = estimate_tokens(text)
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    }


def extract_openai_usage(body, prompt, text):
    usage = body.get("usage", {}) if isinstance(body, dict) else {}
    prompt_tokens = to_int_or_zero(usage.get("prompt_tokens"))
    completion_tokens = to_int_or_zero(usage.get("completion_tokens"))
    total_tokens = to_int_or_zero(usage.get("total_tokens"))

    if prompt_tokens == 0:
        prompt_tokens = estimate_tokens(prompt)
    if completion_tokens == 0:
        completion_tokens = estimate_tokens(text)
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    }


def record_ai_usage(
    visitor_id,
    provider,
    model,
    prompt_tokens,
    completion_tokens,
    total_tokens,
    status,
    error_message=None
):
    now = utc_now_iso()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_usage_events (
                visitor_id,
                provider,
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                status,
                error_message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                visitor_id,
                provider,
                model,
                max(0, to_int_or_zero(prompt_tokens)),
                max(0, to_int_or_zero(completion_tokens)),
                max(0, to_int_or_zero(total_tokens)),
                status,
                (error_message or "")[:500],
                now
            )
        )
        conn.commit()


def get_basic_auth_header(key_id, key_secret):
    token = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def create_razorpay_order(visitor_id, doc_path):
    settings = load_settings()
    amount_decimal = get_document_price_decimal(settings, doc_path)
    if amount_decimal <= Decimal("0.00"):
        raise ValueError("Payments are disabled for this document because its price is set to 0")
    if amount_decimal < RAZORPAY_MIN_ORDER_AMOUNT:
        raise ValueError("Razorpay requires a minimum document price of INR 1.00. Set the price to 0.00 for free downloads or at least 1.00 for paid downloads.")
    host = request.host if has_request_context() else None
    blocked_reason = get_razorpay_block_reason(settings, host, doc_path=doc_path)
    if blocked_reason:
        raise ValueError(blocked_reason)
    if not payment_ready(settings):
        raise ValueError("Razorpay credentials are missing in admin settings")

    amount_subunits = price_to_subunits(amount_decimal)
    doc_name = get_doc_name(doc_path)
    receipt = f"doc_{uuid.uuid4().hex[:18]}"
    payload = {
        "amount": amount_subunits,
        "currency": settings.get("currency", "INR"),
        "receipt": receipt,
        "notes": {
            "doc_path": doc_path,
            "doc_name": doc_name
        }
    }
    request_obj = Request(
        "https://api.razorpay.com/v1/orders",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **get_basic_auth_header(
                settings.get("razorpay_key_id", "").strip(),
                settings.get("razorpay_key_secret", "").strip()
            )
        },
        method="POST"
    )

    try:
        with urlopen(request_obj, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Razorpay order creation failed ({e.code}): {error_body}")
    except URLError as e:
        raise RuntimeError(f"Razorpay order creation failed: {e.reason}")

    order_id = body.get("id", "").strip()
    if not order_id:
        raise RuntimeError("Razorpay did not return an order id")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO payment_events (
                visitor_id,
                doc_path,
                doc_name,
                order_id,
                receipt,
                amount,
                currency,
                status,
                notes,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                visitor_id,
                doc_path,
                doc_name,
                order_id,
                receipt,
                amount_subunits,
                settings.get("currency", "INR"),
                "created",
                json.dumps(body.get("notes", {})),
                utc_now_iso()
            )
        )
        conn.commit()

    return {
        "order_id": order_id,
        "key": settings.get("razorpay_key_id", "").strip(),
        "amount": amount_subunits,
        "currency": settings.get("currency", "INR"),
        "price_display": format_price(amount_decimal),
        "doc_name": doc_name,
        "doc_path": doc_path
    }


def verify_razorpay_signature(order_id, payment_id, signature, secret):
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


def verify_payment_for_download(visitor_id, doc_path, order_id, payment_id, signature):
    settings = load_settings()
    if not payment_ready(settings):
        raise ValueError("Razorpay credentials are missing in admin settings")
    if not order_id or not payment_id or not signature:
        raise ValueError("Missing Razorpay payment verification fields")

    if not verify_razorpay_signature(
        order_id=order_id,
        payment_id=payment_id,
        signature=signature,
        secret=settings.get("razorpay_key_secret", "").strip()
    ):
        raise ValueError("Invalid Razorpay payment signature")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE payment_events
            SET payment_id = ?, signature = ?, status = 'paid', verified_at = ?
            WHERE order_id = ? AND visitor_id = ? AND doc_path = ?
            """,
            (payment_id, signature, utc_now_iso(), order_id, visitor_id, doc_path)
        )
        if cursor.rowcount == 0:
            raise ValueError("Payment order not found for this session")
        conn.commit()


def has_verified_payment(visitor_id, doc_path, order_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id
            FROM payment_events
            WHERE order_id = ?
              AND visitor_id = ?
              AND doc_path = ?
              AND status = 'paid'
              AND download_consumed = 0
            """,
            (order_id, visitor_id, doc_path)
        )
        row = cursor.fetchone()
    return row is not None


def consume_payment_download(visitor_id, doc_path, order_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE payment_events
            SET download_consumed = 1, downloaded_at = ?
            WHERE order_id = ?
              AND visitor_id = ?
              AND doc_path = ?
              AND status = 'paid'
              AND download_consumed = 0
            """,
            (utc_now_iso(), order_id, visitor_id, doc_path)
        )
        conn.commit()
        return cursor.rowcount > 0


def amount_to_float_from_subunits(value):
    amount = Decimal(to_int_or_zero(value)) / Decimal("100")
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def amount_to_display_from_subunits(value):
    amount = Decimal(to_int_or_zero(value)) / Decimal("100")
    return format_price(amount)


def get_grouped_map(cursor, query):
    cursor.execute(query)
    return {row[0]: row[1] for row in cursor.fetchall() if row[0]}


def build_daily_series(downloads_by_day, tokens_by_day, revenue_by_day, days=14):
    today = utc_now().date()
    labels = []
    downloads = []
    tokens = []
    revenue = []

    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        labels.append(day.strftime("%d %b"))
        downloads.append(to_int_or_zero(downloads_by_day.get(key, 0)))
        tokens.append(to_int_or_zero(tokens_by_day.get(key, 0)))
        revenue.append(amount_to_float_from_subunits(revenue_by_day.get(key, 0)))

    return {
        "labels": labels,
        "downloads": downloads,
        "tokens": tokens,
        "revenue": revenue
    }


def month_start(dt):
    return dt.replace(day=1)


def shift_months(dt, months_back):
    month_cursor = month_start(dt)
    for _ in range(months_back):
        month_cursor = month_start(month_cursor - timedelta(days=1))
    return month_cursor


def build_monthly_series(downloads_by_month, tokens_by_month, revenue_by_month, months=12):
    anchor = utc_now()
    labels = []
    downloads = []
    tokens = []
    revenue = []

    for offset in range(months - 1, -1, -1):
        month_cursor = shift_months(anchor, offset)
        key = month_cursor.strftime("%Y-%m")
        labels.append(month_cursor.strftime("%b %Y"))
        downloads.append(to_int_or_zero(downloads_by_month.get(key, 0)))
        tokens.append(to_int_or_zero(tokens_by_month.get(key, 0)))
        revenue.append(amount_to_float_from_subunits(revenue_by_month.get(key, 0)))

    return {
        "labels": labels,
        "downloads": downloads,
        "tokens": tokens,
        "revenue": revenue
    }


def build_yearly_series(downloads_by_year, tokens_by_year, revenue_by_year, years=5):
    current_year = utc_now().year
    labels = []
    downloads = []
    tokens = []
    revenue = []

    for year in range(current_year - years + 1, current_year + 1):
        key = str(year)
        labels.append(key)
        downloads.append(to_int_or_zero(downloads_by_year.get(key, 0)))
        tokens.append(to_int_or_zero(tokens_by_year.get(key, 0)))
        revenue.append(amount_to_float_from_subunits(revenue_by_year.get(key, 0)))

    return {
        "labels": labels,
        "downloads": downloads,
        "tokens": tokens,
        "revenue": revenue
    }


def sum_recent_daily_values(series_map, days):
    today = utc_now().date()
    total = 0
    for offset in range(days):
        key = (today - timedelta(days=offset)).isoformat()
        total += to_int_or_zero(series_map.get(key, 0))
    return total


def get_ai_usage_stats(cursor):
    cursor.execute("SELECT COUNT(*) FROM ai_usage_events")
    total_clicks = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ai_usage_events WHERE status = 'success'")
    successful_calls = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ai_usage_events WHERE status = 'blocked'")
    blocked_calls = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ai_usage_events WHERE status = 'failed'")
    failed_calls = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(total_tokens), 0) FROM ai_usage_events WHERE status = 'success'")
    total_tokens_used = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT provider, COUNT(*) AS clicks, COALESCE(SUM(total_tokens), 0) AS tokens
        FROM ai_usage_events
        GROUP BY provider
        ORDER BY clicks DESC
        """
    )
    provider_usage = [
        {
            "provider": row[0] or "unknown",
            "clicks": row[1],
            "tokens": row[2]
        }
        for row in cursor.fetchall()
    ]

    cursor.execute(
        """
        SELECT model, provider, COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS tokens
        FROM ai_usage_events
        GROUP BY model, provider
        ORDER BY calls DESC, tokens DESC
        LIMIT 8
        """
    )
    model_usage = [
        {
            "model": row[0] or "unknown",
            "provider": row[1] or "unknown",
            "calls": row[2],
            "tokens": row[3]
        }
        for row in cursor.fetchall()
    ]

    cursor.execute(
        """
        SELECT provider, model, total_tokens, status, COALESCE(error_message, ''), created_at
        FROM ai_usage_events
        ORDER BY created_at DESC
        LIMIT 10
        """
    )
    recent_events = [
        {
            "provider": row[0] or "unknown",
            "model": row[1] or "unknown",
            "tokens": row[2],
            "status": row[3],
            "error_message": row[4],
            "created_at": row[5]
        }
        for row in cursor.fetchall()
    ]

    return {
        "total_clicks": total_clicks,
        "successful_calls": successful_calls,
        "blocked_calls": blocked_calls,
        "failed_calls": failed_calls,
        "total_tokens_used": total_tokens_used,
        "provider_usage": provider_usage,
        "model_usage": model_usage,
        "recent_events": recent_events
    }


def get_admin_stats():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM visitors")
        total_logged_in = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM download_events")
        total_downloads = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT doc_name, COUNT(*) AS downloads
            FROM download_events
            GROUP BY doc_name
            ORDER BY downloads DESC, doc_name ASC
            LIMIT 10
            """
        )
        top_docs = [
            {"doc_name": row[0], "downloads": row[1]}
            for row in cursor.fetchall()
        ]

        downloads_by_day = get_grouped_map(
            cursor,
            """
            SELECT substr(downloaded_at, 1, 10), COUNT(*)
            FROM download_events
            GROUP BY substr(downloaded_at, 1, 10)
            """
        )
        downloads_by_month = get_grouped_map(
            cursor,
            """
            SELECT substr(downloaded_at, 1, 7), COUNT(*)
            FROM download_events
            GROUP BY substr(downloaded_at, 1, 7)
            """
        )
        downloads_by_year = get_grouped_map(
            cursor,
            """
            SELECT substr(downloaded_at, 1, 4), COUNT(*)
            FROM download_events
            GROUP BY substr(downloaded_at, 1, 4)
            """
        )

        tokens_by_day = get_grouped_map(
            cursor,
            """
            SELECT substr(created_at, 1, 10), COALESCE(SUM(total_tokens), 0)
            FROM ai_usage_events
            WHERE status = 'success'
            GROUP BY substr(created_at, 1, 10)
            """
        )
        tokens_by_month = get_grouped_map(
            cursor,
            """
            SELECT substr(created_at, 1, 7), COALESCE(SUM(total_tokens), 0)
            FROM ai_usage_events
            WHERE status = 'success'
            GROUP BY substr(created_at, 1, 7)
            """
        )
        tokens_by_year = get_grouped_map(
            cursor,
            """
            SELECT substr(created_at, 1, 4), COALESCE(SUM(total_tokens), 0)
            FROM ai_usage_events
            WHERE status = 'success'
            GROUP BY substr(created_at, 1, 4)
            """
        )

        revenue_by_day = get_grouped_map(
            cursor,
            """
            SELECT substr(verified_at, 1, 10), COALESCE(SUM(amount), 0)
            FROM payment_events
            WHERE status = 'paid' AND verified_at IS NOT NULL
            GROUP BY substr(verified_at, 1, 10)
            """
        )
        revenue_by_month = get_grouped_map(
            cursor,
            """
            SELECT substr(verified_at, 1, 7), COALESCE(SUM(amount), 0)
            FROM payment_events
            WHERE status = 'paid' AND verified_at IS NOT NULL
            GROUP BY substr(verified_at, 1, 7)
            """
        )
        revenue_by_year = get_grouped_map(
            cursor,
            """
            SELECT substr(verified_at, 1, 4), COALESCE(SUM(amount), 0)
            FROM payment_events
            WHERE status = 'paid' AND verified_at IS NOT NULL
            GROUP BY substr(verified_at, 1, 4)
            """
        )

        cursor.execute("SELECT COUNT(*) FROM payment_events")
        total_orders = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM payment_events WHERE status = 'paid'")
        successful_payments = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM payment_events WHERE status = 'paid'")
        total_revenue_subunits = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT doc_name, amount, currency, status, order_id, payment_id, created_at, verified_at
            FROM payment_events
            ORDER BY COALESCE(verified_at, created_at) DESC
            LIMIT 10
            """
        )
        recent_payments = [
            {
                "doc_name": row[0] or "Unknown",
                "amount": amount_to_float_from_subunits(row[1]),
                "currency": row[2] or "INR",
                "status": row[3],
                "order_id": row[4],
                "payment_id": row[5],
                "created_at": row[6],
                "verified_at": row[7]
            }
            for row in cursor.fetchall()
        ]

        ai_usage = get_ai_usage_stats(cursor)

    today_key = utc_now().date().isoformat()
    month_key = utc_now().strftime("%Y-%m")
    year_key = utc_now().strftime("%Y")
    settings = load_settings()
    document_price = get_document_price_decimal(settings)

    return {
        "total_logged_in": total_logged_in,
        "total_downloads": total_downloads,
        "top_docs": top_docs,
        "downloads_today": to_int_or_zero(downloads_by_day.get(today_key, 0)),
        "downloads_this_month": to_int_or_zero(downloads_by_month.get(month_key, 0)),
        "downloads_this_year": to_int_or_zero(downloads_by_year.get(year_key, 0)),
        "tokens_today": to_int_or_zero(tokens_by_day.get(today_key, 0)),
        "tokens_this_month": to_int_or_zero(tokens_by_month.get(month_key, 0)),
        "tokens_this_year": to_int_or_zero(tokens_by_year.get(year_key, 0)),
        "revenue_today": amount_to_float_from_subunits(revenue_by_day.get(today_key, 0)),
        "revenue_this_week": amount_to_float_from_subunits(sum_recent_daily_values(revenue_by_day, 7)),
        "revenue_this_month": amount_to_float_from_subunits(revenue_by_month.get(month_key, 0)),
        "revenue_this_year": amount_to_float_from_subunits(revenue_by_year.get(year_key, 0)),
        "analytics": {
            "daily": build_daily_series(downloads_by_day, tokens_by_day, revenue_by_day, days=14),
            "monthly": build_monthly_series(downloads_by_month, tokens_by_month, revenue_by_month, months=12),
            "yearly": build_yearly_series(downloads_by_year, tokens_by_year, revenue_by_year, years=5)
        },
        "payments": {
            "total_orders": total_orders,
            "successful_payments": successful_payments,
            "total_revenue": amount_to_float_from_subunits(total_revenue_subunits),
            "recent": recent_payments
        },
        "ai_usage": ai_usage,
        "document_pricing": {
            "price_display": format_price(document_price),
            "requires_payment": payment_required(settings),
            "payment_ready": payment_ready(settings)
        },
        "payment_config": payment_public_config()
    }


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return func(*args, **kwargs)
    return wrapper


def generate_with_gemini(prompt, model, api_key, max_output_tokens=None):
    if not api_key:
        raise ValueError("Gemini API key is not configured")

    import google.generativeai as genai
    genai.configure(api_key=api_key)

    model_obj = genai.GenerativeModel(model)

    response = model_obj.generate_content(prompt)

    if not response.text:
        raise ValueError("Model returned empty response")

    usage = extract_gemini_usage(response=response, prompt=prompt, text=response.text)

    return {
        "text": response.text,
        **usage
    }


def generate_with_openai(prompt, model, api_key, max_output_tokens=None):
    if not api_key:
        raise ValueError("OpenAI API key is not configured")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    if max_output_tokens and max_output_tokens > 0:
        payload["max_tokens"] = max_output_tokens
    request_obj = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        method="POST"
    )

    try:
        with urlopen(request_obj, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI request failed ({e.code}): {error_body}")
    except URLError as e:
        raise RuntimeError(f"OpenAI request failed: {e.reason}")

    choices = body.get("choices", [])
    if not choices:
        raise ValueError("OpenAI model returned empty response")

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        raise ValueError("OpenAI model returned empty response")
    usage = extract_openai_usage(body=body, prompt=prompt, text=content)
    return {
        "text": content,
        **usage
    }


@app.before_request
def track_visitors():
    if request.path.startswith("/static"):
        return
    if request.path.startswith("/admin"):
        return
    if request.method == "GET":
        ensure_visitor_session()


# --- User Routes ---
@app.route("/")
def index():
    return render_template("index.html")


@app.route('/resume')
def resume():
    return render_template('resume.html')


@app.route('/cv')
def cv():
    return render_template('cv.html')


@app.route('/cl')
def cover_letter():
    return render_template('cl.html')


@app.route('/sop')
def statement_of_purpose():
    return render_template('sop.html')


@app.route('/lor')
def letter_of_recommendation():
    return render_template('lor.html')


@app.route('/joining_letter')
def joining_letter():
    return render_template('joining_letter.html')


@app.route('/resignation_letter')
def resignation_letter():
    return render_template('resignation_letter.html')


@app.route('/appraisal_letter')
def appraisal_letter():
    return render_template('appraisal_letter.html')


@app.route('/experience_letter')
def experience_letter():
    return render_template('experience_letter.html')


@app.route('/tc_request_letter')
def tc_request_letter():
    return render_template('tc_request_letter.html')


@app.route('/promotion_letter')
def promotion_letter():
    return render_template('promotion_letter.html')


@app.route('/relieving_letter')
def relieving_letter():
    return render_template('relieving_letter.html')


@app.route('/increment_letter')
def increment_letter():
    return render_template('increment_letter.html')


@app.route('/research_proposal')
def research_proposal():
    return render_template('research_proposal.html')


@app.route('/grant_application_letter')
def grant_application_letter():
    return render_template('grant_application_letter.html')


@app.route('/scholarship_letter')
def scholarship_letter():
    return render_template('scholarship_letter.html')


@app.route('/termination_letter')
def termination_letter():
    return render_template('termination_letter.html')


@app.route('/employment_contract')
def employment_contract():
    return render_template('employment_contract.html')


@app.route('/grievance_letter')
def grievance_letter():
    return render_template('grievance_letter.html')


@app.route('/rti_application')
def rti_application():
    return render_template('rti_application.html')


@app.route('/official_memo')
def official_memo():
    return render_template('official_memo.html')


@app.route('/government_proposal')
def government_proposal():
    return render_template('government_proposal.html')


@app.route('/tender_document')
def tender_document():
    return render_template('tender_document.html')


@app.route("/generate_ai_content", methods=["POST"])
def generate_ai_content():
    visitor_id = None
    provider = "unknown"
    model = "unknown"
    try:
        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({"error": "Prompt is required"}), 400

        visitor_id = ensure_visitor_session()
        prompt = data['prompt']
        settings = load_settings()
        doc_path = normalize_doc_path(data.get("doc_path") or infer_doc_path())
        doc_rule = build_document_rule(settings, doc_path)
        provider = settings.get("provider", "gemini")
        model = settings.get("model", DEFAULT_MODEL_NAME)

        if not settings.get("ai_usage_enabled", True):
            record_ai_usage(
                visitor_id=visitor_id,
                provider=provider,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                status="blocked",
                error_message="AI usage disabled by admin"
            )
            return jsonify({"error": "AI generation is currently disabled by admin."}), 403

        app.logger.info(
            f"Generating content with provider={provider}, model={model}, doc_path={doc_path}, token_limit={doc_rule['token_limit']}, prompt_len={len(prompt)}"
        )

        if provider == "openai":
            generation = generate_with_openai(
                prompt=prompt,
                model=model,
                api_key=settings.get("openai_api_key", ""),
                max_output_tokens=doc_rule["token_limit"]
            )
        else:
            generation = generate_with_gemini(
                prompt=prompt,
                model=model,
                api_key=settings.get("gemini_api_key", ""),
                max_output_tokens=doc_rule["token_limit"]
            )

        generated_text = generation["text"]
        record_ai_usage(
            visitor_id=visitor_id,
            provider=provider,
            model=model,
            prompt_tokens=generation.get("prompt_tokens", 0),
            completion_tokens=generation.get("completion_tokens", 0),
            total_tokens=generation.get("total_tokens", 0),
            status="success"
        )

        cleaned_text = generated_text.replace("*", "").replace("#", "")
        return jsonify({"text": cleaned_text})

    except Exception as e:
        error_msg = str(e)
        app.logger.error(f"AI Generation Error: {error_msg}")
        traceback.print_exc()

        if visitor_id:
            record_ai_usage(
                visitor_id=visitor_id,
                provider=provider,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                status="failed",
                error_message=error_msg
            )

        if "429" in error_msg or "quota" in error_msg.lower():
            return jsonify({
                "error": "API quota exceeded. Please update your key or model in admin settings.",
                "raw_error": error_msg
            }), 429

        return jsonify({"error": error_msg}), 500


@app.route('/download_pdf', methods=['POST'])
def download_pdf():
    try:
        data = request.get_json()
        if not data or 'html_content' not in data:
            return jsonify({'error': 'HTML content is required'}), 400

        if not WKHTMLTOPDF_PATH:
            return jsonify({'error': 'wkhtmltopdf not properly installed or configured'}), 500

        visitor_id = ensure_visitor_session()
        settings = load_settings()
        referer = request.headers.get("Referer", "")
        ref_path = urlparse(referer).path if referer else ""
        doc_path = normalize_doc_path(data.get("doc_path") or ref_path)
        order_id = str(data.get("order_id", "") or "").strip()

        amount_decimal = get_document_price_decimal(settings, doc_path)
        doc_requires_payment = amount_decimal > Decimal("0.00")
        if doc_requires_payment:
            if not payment_ready(settings):
                return jsonify({'error': 'Razorpay is not configured in admin settings yet.'}), 503
            if not order_id:
                return jsonify({'error': 'Payment is required before downloading this document.'}), 402
            if not has_verified_payment(visitor_id=visitor_id, doc_path=doc_path, order_id=order_id):
                return jsonify({'error': 'Payment verification missing or this download has already been used.'}), 402

        options = {
            'page-size': 'A4',
            'margin-top': '0.3in',
            'margin-right': '0.3in',
            'margin-bottom': '0.3in',
            'margin-left': '0.3in',
            'encoding': "UTF-8",
            'no-outline': None
        }

        config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
        pdf_bytes = pdfkit.from_string(
            data['html_content'],
            False,
            options=options,
            configuration=config
        )

        if doc_requires_payment:
            if not consume_payment_download(visitor_id=visitor_id, doc_path=doc_path, order_id=order_id):
                return jsonify({'error': 'Payment could not be locked for download. Please retry payment.'}), 409

        record_download(visitor_id=visitor_id, doc_path=doc_path)

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name='document.pdf'
        )

    except Exception as e:
        app.logger.error(f"PDF Generation Error: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/payment/config')
def payment_config():
    doc_path = normalize_doc_path(request.args.get("doc_path", ""))
    return jsonify(payment_public_config(doc_path=doc_path))


@app.route('/payment/create-order', methods=['POST'])
def payment_create_order():
    try:
        visitor_id = ensure_visitor_session()
        data = request.get_json(silent=True) or {}
        doc_path = normalize_doc_path(data.get("doc_path") or request.headers.get("Referer", ""))
        if doc_path == "unknown":
            referer = request.headers.get("Referer", "")
            doc_path = normalize_doc_path(urlparse(referer).path if referer else "")
        order = create_razorpay_order(visitor_id=visitor_id, doc_path=doc_path)
        return jsonify(order)
    except ValueError as e:
        app.logger.warning(f"Payment order blocked: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Payment order creation error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/payment/verify', methods=['POST'])
def payment_verify():
    try:
        visitor_id = ensure_visitor_session()
        data = request.get_json()
        if not data:
            return jsonify({"error": "Payment payload is required"}), 400

        doc_path = normalize_doc_path(data.get("doc_path", ""))
        verify_payment_for_download(
            visitor_id=visitor_id,
            doc_path=doc_path,
            order_id=str(data.get("order_id", "")).strip(),
            payment_id=str(data.get("payment_id", "")).strip(),
            signature=str(data.get("signature", "")).strip()
        )
        return jsonify({"verified": True})
    except ValueError as e:
        app.logger.warning(f"Payment verification blocked: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Payment verification error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 400


# --- Admin Routes ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    message = ""
    if request.method == 'POST':
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if email == DEFAULT_ADMIN_EMAIL and password == DEFAULT_ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        message = "Invalid email or password"
    return render_template('admin_login.html', message=message)


@app.route('/admin/logout')
@admin_required
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = get_admin_stats()
    settings = load_settings()
    active_provider = settings.get("provider", "gemini")
    active_key = settings.get("gemini_api_key", "") if active_provider == "gemini" else settings.get("openai_api_key", "")
    payment_blocked_reason = get_razorpay_block_reason(settings, request.host)
    return render_template(
        'admin_dashboard.html',
        stats=stats,
        settings=settings,
        document_rules_view=build_document_rules_view(settings),
        available_models=AVAILABLE_MODELS,
        document_catalog=list(DOC_PATH_LABELS.items()),
        active_provider=active_provider,
        ai_usage_enabled=settings.get("ai_usage_enabled", True),
        masked_active_key=mask_key(active_key),
        masked_gemini_key=mask_key(settings.get("gemini_api_key", "")),
        masked_openai_key=mask_key(settings.get("openai_api_key", "")),
        masked_razorpay_key_id=mask_key(settings.get("razorpay_key_id", "")),
        masked_razorpay_key_secret=mask_key(settings.get("razorpay_key_secret", "")),
        payment_ready_flag=payment_ready(settings) and not payment_blocked_reason,
        payment_blocked_reason=payment_blocked_reason
    )


@app.route('/admin/stats')
@admin_required
def admin_stats():
    return jsonify(get_admin_stats())


@app.route('/admin/settings', methods=['POST'])
@admin_required
def admin_settings():
    settings = load_settings()

    provider = request.form.get("provider", settings.get("provider", "gemini")).strip().lower()
    model = request.form.get("model", settings.get("model", DEFAULT_MODEL_NAME)).strip()
    api_key = request.form.get("api_key", "").strip()
    # Backward compatibility if an old UI still posts provider-specific fields.
    gemini_api_key = request.form.get("gemini_api_key", "").strip()
    openai_api_key = request.form.get("openai_api_key", "").strip()
    razorpay_key_id = request.form.get("razorpay_key_id", settings.get("razorpay_key_id", "")).strip()
    razorpay_key_secret = request.form.get("razorpay_key_secret", settings.get("razorpay_key_secret", "")).strip()
    document_price = request.form.get("document_price", settings.get("document_price", "0.00")).strip()

    if provider not in AVAILABLE_MODELS:
        return jsonify({"error": "Invalid provider"}), 400

    if model not in AVAILABLE_MODELS[provider]:
        return jsonify({"error": "Invalid model for selected provider"}), 400

    settings["provider"] = provider
    settings["model"] = model

    if provider == "gemini" and api_key:
        settings["gemini_api_key"] = api_key
    elif provider == "openai" and api_key:
        settings["openai_api_key"] = api_key

    if gemini_api_key:
        settings["gemini_api_key"] = gemini_api_key
    if openai_api_key:
        settings["openai_api_key"] = openai_api_key
    
    # razorpay_key_id = os.getenv("RAZORPAY_KEY_ID") or request.form.get("razorpay_key_id", "").strip()
    # razorpay_key_secret = os.getenv("RAZORPAY_KEY_SECRET") or request.form.get("razorpay_key_secret", "").strip()
    settings["razorpay_key_id"] = razorpay_key_id
    settings["razorpay_key_secret"] = razorpay_key_secret
    parsed_price = parse_decimal_price(document_price)
    if parsed_price != Decimal("0.00") and parsed_price < RAZORPAY_MIN_ORDER_AMOUNT:
        return jsonify({
            "error": "Razorpay requires a minimum paid document price of INR 1.00. Use 0.00 for free downloads or 1.00 and above for paid downloads."
        }), 400

    settings["document_price"] = format_price(parsed_price)
    settings["currency"] = "INR"

    save_settings(settings)
    return jsonify({
        "message": "Settings updated successfully",
        "payment_ready": payment_ready(settings) and not get_razorpay_block_reason(settings, request.host),
        "document_price": settings["document_price"],
        "blocked_reason": get_razorpay_block_reason(settings, request.host)
    })


@app.route('/admin/ai-usage/toggle', methods=['POST'])
@admin_required
def admin_ai_usage_toggle():
    settings = load_settings()
    action = request.form.get("action", "").strip().lower()

    if action == "stop":
        settings["ai_usage_enabled"] = False
    elif action == "resume":
        settings["ai_usage_enabled"] = True
    else:
        return jsonify({"error": "Invalid action. Use 'stop' or 'resume'."}), 400

    save_settings(settings)
    return jsonify({
        "message": "AI usage stopped" if not settings["ai_usage_enabled"] else "AI usage resumed",
        "ai_usage_enabled": settings["ai_usage_enabled"]
    })


@app.route('/admin/document-rules', methods=['POST'])
@admin_required
def admin_document_rules():
    try:
        payload = request.get_json(silent=True) or {}
        rules = payload.get("rules", [])
        if not isinstance(rules, list):
            return jsonify({"error": "Rules must be a list"}), 400

        settings = load_settings()
        current_rules = settings.get("document_rules", {}) if isinstance(settings.get("document_rules", {}), dict) else {}
        normalized_rules = {}

        for item in rules:
            if not isinstance(item, dict):
                continue
            doc_path = normalize_doc_path(item.get("path", ""))
            if doc_path == "unknown":
                continue

            raw_price = str(item.get("price", settings.get("document_price", "0.00"))).strip()
            parsed_price = parse_decimal_price(raw_price)
            if parsed_price != Decimal("0.00") and parsed_price < RAZORPAY_MIN_ORDER_AMOUNT:
                return jsonify({
                    "error": f"{get_doc_name(doc_path)} must be free (0.00) or at least INR 1.00 to work with Razorpay."
                }), 400

            token_limit = to_int_or_zero(item.get("token_limit", DEFAULT_DOCUMENT_TOKEN_LIMIT))
            if token_limit <= 0:
                token_limit = DEFAULT_DOCUMENT_TOKEN_LIMIT

            normalized_rules[doc_path] = {
                "price": format_price(parsed_price),
                "token_limit": token_limit
            }

        current_rules.update(normalized_rules)
        settings["document_rules"] = current_rules
        save_settings(settings)

        return jsonify({
            "message": "Document rules saved successfully",
            "document_rules": build_document_rules_view(settings)
        })
    except Exception as e:
        app.logger.error(f"Document rules save error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


init_db()


# import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=False, use_reloader=False, host="0.0.0.0", port=port)

# import os

# razorpay_key_id = os.getenv("RAZORPAY_KEY_ID")
# razorpay_key_secret = os.getenv("RAZORPAY_KEY_SECRET")