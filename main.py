# -----------------------------
# Standard library
# -----------------------------
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

# -----------------------------
# Third-party
# -----------------------------
import pytz
import pycountry
import phonenumbers
from phonenumbers import timezone as pn_tz

from fastapi import FastAPI
from pydantic import BaseModel, Field


# -----------------------------
# Config
# -----------------------------
CALL_START = "07:00:00"
CALL_END = "18:59:00"
TR_TZ = "Europe/Istanbul"

# Türkiye saatine göre arama penceresi (yeni endpoint için)
TR_CALL_START_HOUR = 10  # 10:00
TR_CALL_END_HOUR = 22    # 22:00

PREFERRED_TZ_BY_ISO2 = {
    "US": "America/New_York",
    "CA": "America/Toronto",
    "AU": "Australia/Sydney",
    "BR": "America/Sao_Paulo",
    "RU": "Europe/Moscow",
    "CN": "Asia/Shanghai",
}

COUNTRY_NAME_ALIASES_TO_ISO2 = {
    "ivory coast": "CI",
    "cote d'ivoire": "CI",
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "russia": "RU",
}

# -----------------------------
# FastAPI app (IMPORTANT: must be before endpoints)
# -----------------------------
app = FastAPI(title="Lead Timezone & Call Prioritization API")


# -----------------------------
# Models
# -----------------------------
class LeadIn(BaseModel):
    lead_id: Optional[str] = Field(default=None, description="Your internal lead id (optional)")
    phone_e164_or_digits: str = Field(..., description="E164 or digits, e.g. +14155552671 or 14155552671")
    country_name: Optional[str] = Field(default="", description="Optional; improves fallback when number is ambiguous")
    meta: Optional[dict] = Field(default=None, description="Any additional info you want to carry")


class LeadRawOut(BaseModel):
    lead_id: Optional[str]
    phone_input: str
    phone_digits: str
    phone_e164: str

    country_name: str
    country_iso2: str

    timezone_iana: str
    tz_ambiguous: bool
    tz_source: str  # "number" | "country_fallback" | "empty"


class LeadOut(BaseModel):
    lead_id: Optional[str]
    phone_digits: str
    country_name: str

    timezone_iana: str
    tz_ambiguous: bool

    lead_local_time_now: str
    can_call_now: bool

    next_call_lead_local: str
    next_call_tr: str

    priority_score: int


class NextToCallOut(BaseModel):
    selected: Optional[LeadOut]
    reason: str
    total_leads: int
    callable_now_count: int


class PhoneCallWindowIn(BaseModel):
    phone_e164_or_digits: str = Field(..., description="E164 or digits, e.g. +14155552671 or 14155552671")
    country_name: Optional[str] = Field(default="", description="Optional; improves fallback when number is ambiguous")


class PhoneCallWindowOut(BaseModel):
    start_time: str  # HH:MM formatında
    end_time: str    # HH:MM formatında


# -----------------------------
# Helpers
# -----------------------------
def normalize_digits(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\D+", "", str(value).strip())


def digits_to_e164(digits: str) -> str:
    digits = normalize_digits(digits)
    return f"+{digits}" if digits else ""


def clean_country_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def iso2_from_country_name(country_name: str) -> str:
    if not country_name:
        return ""
    raw = clean_country_name(country_name)
    key = raw.lower().strip()

    if key in COUNTRY_NAME_ALIASES_TO_ISO2:
        return COUNTRY_NAME_ALIASES_TO_ISO2[key]

    try:
        c = pycountry.countries.lookup(raw)
        return getattr(c, "alpha_2", "") or ""
    except Exception:
        return ""


def parse_time(t: str):
    return datetime.strptime(t, "%H:%M:%S").time()


def lead_local_now(iana: str) -> Optional[datetime]:
    if not iana:
        return None
    try:
        tz = pytz.timezone(iana)
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        return now_utc.astimezone(tz)
    except Exception:
        return None


def can_call_now(iana: str) -> bool:
    dt = lead_local_now(iana)
    if not dt:
        return False
    start_t = parse_time(CALL_START)
    end_t = parse_time(CALL_END)
    return start_t <= dt.time() <= end_t


def next_call_local(iana: str) -> Optional[datetime]:
    dt = lead_local_now(iana)
    if not dt:
        return None

    start_t = parse_time(CALL_START)
    end_t = parse_time(CALL_END)

    today_start = dt.replace(hour=start_t.hour, minute=start_t.minute, second=start_t.second, microsecond=0)

    if dt.time() < start_t:
        return today_start

    if dt.time() > end_t:
        return today_start + timedelta(days=1)

    return dt  # already callable


def to_tz(dt: Optional[datetime], iana: str) -> Optional[datetime]:
    if not dt:
        return None
    try:
        return dt.astimezone(pytz.timezone(iana))
    except Exception:
        return None


def detect_timezone_iana_with_source(digits: str, country_name: str = "") -> Tuple[str, bool, str, str]:
    """
    Returns (iana_timezone, tz_ambiguous, tz_source, country_iso2)
    tz_source: "number" | "country_fallback" | "empty"
    """
    digits = normalize_digits(digits)
    if not digits:
        return ("", False, "empty", "")

    try:
        num = phonenumbers.parse("+" + digits, None)
    except Exception:
        return ("", False, "empty", "")

    # 1) Primary: number -> timezones
    try:
        zones = pn_tz.time_zones_for_number(num)
    except Exception:
        zones = []

    if zones:
        iso2 = phonenumbers.region_code_for_number(num) or ""
        return (zones[0], len(zones) > 1, "number", iso2)

    # 2) Fallback: country -> timezones
    iso2 = iso2_from_country_name(country_name)
    if not iso2:
        try:
            iso2 = phonenumbers.region_code_for_number(num) or ""
        except Exception:
            iso2 = ""

    if not iso2:
        return ("", False, "empty", "")

    tz_list = pytz.country_timezones.get(iso2, [])
    if not tz_list:
        return ("", False, "empty", iso2)

    if len(tz_list) == 1:
        return (tz_list[0], False, "country_fallback", iso2)

    preferred = PREFERRED_TZ_BY_ISO2.get(iso2)
    if preferred and preferred in tz_list:
        return (preferred, True, "country_fallback", iso2)

    return (tz_list[0], True, "country_fallback", iso2)


def score_callable_lead(dt_local: datetime) -> int:
    """
    Callable leads among 07:00-18:59: score closer to 13:00 higher.
    """
    peak = dt_local.replace(hour=13, minute=0, second=0, microsecond=0)
    diff_minutes = abs(int((dt_local - peak).total_seconds() // 60))
    return max(0, 600 - diff_minutes)  # within ~10 hours window


def parse_tr_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        tz = pytz.timezone(TR_TZ)
        return tz.localize(datetime.strptime(s, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


# -----------------------------
# Endpoint 1: RAW (ham + normalize)
# -----------------------------
@app.post("/leads/raw", response_model=List[LeadRawOut])
def leads_raw(leads: List[LeadIn]):
    out: List[LeadRawOut] = []

    for x in leads:
        phone_input = x.phone_e164_or_digits
        digits = normalize_digits(phone_input)
        e164 = digits_to_e164(digits)

        iana, amb, src, iso2 = detect_timezone_iana_with_source(digits, x.country_name or "")
        if not iso2:
            iso2 = iso2_from_country_name(x.country_name or "")

        out.append(
            LeadRawOut(
                lead_id=x.lead_id,
                phone_input=phone_input,
                phone_digits=digits,
                phone_e164=e164,
                country_name=x.country_name or "",
                country_iso2=iso2 or "",
                timezone_iana=iana,
                tz_ambiguous=amb,
                tz_source=src,
            )
        )

    return out


# -----------------------------
# Endpoint 2: LIST (operational)
# -----------------------------
@app.post("/leads/list", response_model=List[LeadOut])
def leads_list(leads: List[LeadIn]):
    out: List[LeadOut] = []

    for x in leads:
        digits = normalize_digits(x.phone_e164_or_digits)
        iana, amb, _, _ = detect_timezone_iana_with_source(digits, x.country_name or "")

        dt_local = lead_local_now(iana) if iana else None
        callable_now = can_call_now(iana) if iana else False

        next_local = next_call_local(iana) if iana else None
        next_tr = to_tz(next_local, TR_TZ) if next_local else None

        if callable_now and dt_local:
            score = score_callable_lead(dt_local)
        else:
            if next_tr:
                now_tr = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(pytz.timezone(TR_TZ))
                minutes = int((next_tr - now_tr).total_seconds() // 60)
                score = max(0, 10000 - max(0, minutes))
            else:
                score = 0

        out.append(
            LeadOut(
                lead_id=x.lead_id,
                phone_digits=digits,
                country_name=x.country_name or "",
                timezone_iana=iana,
                tz_ambiguous=amb,
                lead_local_time_now=dt_local.strftime("%H:%M:%S") if dt_local else "",
                can_call_now=callable_now,
                next_call_lead_local=next_local.strftime("%Y-%m-%d %H:%M:%S") if next_local else "",
                next_call_tr=next_tr.strftime("%Y-%m-%d %H:%M:%S") if next_tr else "",
                priority_score=score,
            )
        )

    out.sort(key=lambda r: r.priority_score, reverse=True)
    return out


# -----------------------------
# Endpoint 3: NEXT-TO-CALL (single lead)
# -----------------------------
@app.post("/leads/next-to-call", response_model=NextToCallOut)
def next_to_call(leads: List[LeadIn]):
    enriched = leads_list(leads)

    callable_now = [x for x in enriched if x.can_call_now and x.timezone_iana]
    if callable_now:
        return NextToCallOut(
            selected=callable_now[0],
            reason="At least one lead is callable now (07:00–18:59 local). Selected the highest priority.",
            total_leads=len(enriched),
            callable_now_count=len(callable_now),
        )

    candidates = [(x, parse_tr_dt(x.next_call_tr)) for x in enriched]
    candidates = [(x, dt) for x, dt in candidates if dt is not None and x.timezone_iana]

    if not candidates:
        return NextToCallOut(
            selected=None,
            reason="No lead had a resolvable timezone or next-call time. Check phone formatting and country_name.",
            total_leads=len(enriched),
            callable_now_count=0,
        )

    candidates.sort(key=lambda t: t[1])  # earliest first
    return NextToCallOut(
        selected=candidates[0][0],
        reason="No lead is callable now. Selected the lead with the earliest next callable time (converted to TR).",
        total_leads=len(enriched),
        callable_now_count=0,
    )


# -----------------------------
# Endpoint 4: CALL-WINDOW (Türkiye 10:00-22:00 bazlı)
# -----------------------------
def get_call_window_for_timezone(iana: str) -> Tuple[str, str]:
    """
    Türkiye saati 10:00-22:00'nin müşteri yerel saatindeki karşılığını hesaplar.
    Returns (local_start_time, local_end_time) in HH:MM format
    """
    if not iana:
        return ("", "")
    
    try:
        tr_tz = pytz.timezone(TR_TZ)
        lead_tz = pytz.timezone(iana)
        
        # Bugünün tarihini al (Türkiye saatine göre)
        now_tr = datetime.now(tr_tz)
        
        # Türkiye saati 10:00
        tr_start = now_tr.replace(hour=TR_CALL_START_HOUR, minute=0, second=0, microsecond=0)
        # Türkiye saati 22:00
        tr_end = now_tr.replace(hour=TR_CALL_END_HOUR, minute=0, second=0, microsecond=0)
        
        # Müşteri saat dilimine çevir
        local_start = tr_start.astimezone(lead_tz)
        local_end = tr_end.astimezone(lead_tz)
        
        return (local_start.strftime("%H:%M"), local_end.strftime("%H:%M"))
    except Exception:
        return ("", "")


@app.post("/timezone", response_model=PhoneCallWindowOut)
def get_call_window(data: PhoneCallWindowIn):
    """
    Telefon numarasına göre arama penceresi döner.
    
    Türkiye saati 10:00-22:00 baz alınır ve müşterinin yerel saatindeki karşılığı hesaplanır.
    
    Örnek: Türkiye 10:00-22:00 → New York 03:00-15:00
    """
    digits = normalize_digits(data.phone_e164_or_digits)
    iana, _, _, _ = detect_timezone_iana_with_source(digits, data.country_name or "")
    
    # Arama penceresini hesapla
    start_time, end_time = get_call_window_for_timezone(iana)
    
    return PhoneCallWindowOut(
        start_time=start_time,
        end_time=end_time,
    )


@app.post("/leads/call-window/batch", response_model=List[PhoneCallWindowOut])
def get_call_window_batch(data: List[PhoneCallWindowIn]):
    """
    Birden fazla telefon numarası için toplu arama penceresi döner.
    """
    return [get_call_window(item) for item in data]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
