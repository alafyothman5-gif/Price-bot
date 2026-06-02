from __future__ import annotations

import base64
import csv
import html
import io
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from openpyxl import load_workbook
import uvicorn

# =============================================================================
# PriceBot WhatsApp Webhook + Admin Panel
# -----------------------------------------------------------------------------
# Data files are intentionally CSV files so the owner can back them up and edit
# them easily. Secrets are never stored in this file; they must be in .env.
# =============================================================================

APP_DIR = Path(os.getenv("PRICEBOT_DATA_DIR", Path(__file__).resolve().parent))
ENV_FILE = Path(os.getenv("PRICEBOT_ENV_FILE", APP_DIR / ".env"))
PRODUCTS_FILE = Path(os.getenv("PRODUCTS_FILE", APP_DIR / "products.csv"))
ORDERS_FILE = Path(os.getenv("ORDERS_FILE", APP_DIR / "orders.csv"))
MEDIA_DIR = Path(os.getenv("PRICEBOT_MEDIA_DIR", APP_DIR / "media"))

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "pricebot_verify_2026")
ADMIN_KEY = os.getenv("PRICEBOT_ADMIN_KEY", os.getenv("ADMIN_KEY", "PriceBotAdmin2026"))
ADMIN_NOTIFY_PHONE = os.getenv("ADMIN_NOTIFY_PHONE", "")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v20.0")

PRODUCT_FIELDS = ["name", "aliases", "price", "available", "notes"]
ORDER_FIELDS = ["time", "phone", "product", "price", "available", "notes", "message", "status"]

TOKEN_ENV_NAMES = [
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_TOKEN",
    "WA_ACCESS_TOKEN",
    "WA_TOKEN",
    "WHATSAPP_API_TOKEN",
    "WHATSAPP_BEARER_TOKEN",
    "WHATSAPP_PERMANENT_TOKEN",
    "META_WHATSAPP_ACCESS_TOKEN",
    "META_WHATSAPP_TOKEN",
    "META_ACCESS_TOKEN",
    "META_TOKEN",
    "FACEBOOK_ACCESS_TOKEN",
    "FB_ACCESS_TOKEN",
    "GRAPH_API_TOKEN",
    "CLOUD_API_TOKEN",
    "PRICEBOT_TOKEN",
    "ACCESS_TOKEN",
]

PHONE_ID_ENV_NAMES = [
    "WHATSAPP_PHONE_NUMBER_ID",
    "WA_PHONE_NUMBER_ID",
    "PHONE_NUMBER_ID",
    "META_PHONE_NUMBER_ID",
    "META_WHATSAPP_PHONE_NUMBER_ID",
]

app = FastAPI(title="PriceBot", version="3.0.0")
LAST_PRODUCT: Dict[str, dict] = {}
PENDING_SUGGESTION: Dict[str, dict] = {}


def load_dotenv_file() -> None:
    """Load .env values into os.environ without overwriting already set vars."""
    if not ENV_FILE.exists():
        return
    try:
        for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as exc:
        print(f"ENV LOAD WARNING: {exc}", flush=True)


def read_env_file_value(names: Iterable[str]) -> str:
    """Read one of the requested names directly from .env, preferring top names."""
    names = list(names)
    values: Dict[str, str] = {}
    if ENV_FILE.exists():
        try:
            for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        except Exception as exc:
            print(f"ENV READ WARNING: {exc}", flush=True)
    for name in names:
        if values.get(name):
            return values[name]
    for name in names:
        if os.getenv(name):
            return os.getenv(name, "")
    return ""


def clean_token(token: str) -> str:
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token.strip().strip('"').strip("'")


def get_access_token() -> str:
    return clean_token(read_env_file_value(TOKEN_ENV_NAMES))


def get_phone_number_id() -> str:
    return read_env_file_value(PHONE_ID_ENV_NAMES).strip()


def get_config(name: str, default: str = "") -> str:
    """Read optional business settings from environment or .env without exposing secrets."""
    value = os.getenv(name, "").strip()
    if value:
        return value
    if ENV_FILE.exists():
        try:
            for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, raw_value = line.split("=", 1)
                if key.strip() == name:
                    return raw_value.strip().strip('"').strip("'")
        except Exception as exc:
            print(f"CONFIG READ WARNING: {exc}", flush=True)
    return default


def business_name() -> str:
    return get_config("PHARMACY_NAME", "صيدلية بدر البشرية")


def business_city() -> str:
    return get_config("PHARMACY_CITY", "أجدابيا")


def business_hours() -> str:
    return get_config("PHARMACY_HOURS", "24 ساعة")


def delivery_enabled() -> bool:
    value = get_config("DELIVERY_AVAILABLE", "no").strip().lower()
    return value in {"1", "true", "yes", "y", "نعم", "متوفر"}


def delivery_text() -> str:
    if delivery_enabled():
        return get_config("DELIVERY_TEXT", "التوصيل متوفر")
    return get_config("DELIVERY_TEXT", "التوصيل غير متوفر حالياً")


def admin_notify_phone() -> str:
    """Optional WhatsApp number that receives internal admin alerts."""
    return normalize_phone(get_config("ADMIN_NOTIFY_PHONE", ""))


def public_base_url() -> str:
    return get_config("PUBLIC_BASE_URL", "https://46.101.148.246.sslip.io").rstrip("/")


def normalize_phone(phone: str) -> str:
    """Keep digits only, convert 00 prefix, and remove + for WhatsApp Cloud API."""
    phone = str(phone or "").strip()
    phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    phone = re.sub(r"\D+", "", phone)
    if phone.startswith("00"):
        phone = phone[2:]
    return phone


# =============================================================================
# Optional real AI integration with multi-provider fallback
# =============================================================================
def config_bool(name: str, default: bool = False) -> bool:
    raw = get_config(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "y", "on", "نعم", "مفعل"}


def split_secret_list(raw: str) -> List[str]:
    """Parse keys from .env values or admin textareas without exposing them."""
    raw = (raw or "").replace("\r", "\n")
    parts: List[str] = []
    for chunk in re.split(r"[\n,;|]+", raw):
        value = clean_token(chunk)
        if value and value not in parts:
            parts.append(value)
    return parts


def join_secret_list(raw: str) -> str:
    return "||".join(split_secret_list(raw))


def ai_provider_order() -> List[str]:
    raw = get_config("AI_PROVIDER_ORDER", "gemini,openrouter,groq")
    supported = {"openrouter", "gemini", "groq", "openai", "custom"}
    out: List[str] = []
    for item in re.split(r"[,;|\n]+", raw):
        name = item.strip().lower()
        if name in supported and name not in out:
            out.append(name)
    return out or ["gemini", "openrouter", "groq"]


def provider_key_env(provider: str) -> str:
    return {
        "openrouter": "AI_OPENROUTER_KEYS",
        "gemini": "AI_GEMINI_KEYS",
        "groq": "AI_GROQ_KEYS",
        "openai": "AI_OPENAI_KEYS",
        "custom": "AI_CUSTOM_KEYS",
    }.get(provider, "AI_API_KEY")


def ai_keys_for_provider(provider: str) -> List[str]:
    keys = split_secret_list(get_config(provider_key_env(provider), ""))
    # Backward compatibility with the old single-key setting.
    legacy_provider = get_config("AI_PROVIDER", "openrouter").strip().lower() or "openrouter"
    legacy_key = clean_token(get_config("AI_API_KEY", ""))
    if legacy_key and provider == legacy_provider and legacy_key not in keys:
        keys.append(legacy_key)
    return keys


def any_ai_key_saved() -> bool:
    return any(ai_keys_for_provider(provider) for provider in ai_provider_order())


def ai_enabled() -> bool:
    return config_bool("AI_ENABLED", False) and any_ai_key_saved()


def ai_provider() -> str:
    # Compatibility for old UI/health; the actual call uses ai_provider_order().
    order = ai_provider_order()
    return order[0] if order else "openrouter"


def ai_default_model_for(provider: str) -> str:
    if provider == "gemini":
        return "gemini-2.5-flash-lite"
    if provider == "groq":
        return "llama-3.1-8b-instant"
    if provider == "openai":
        return "gpt-4o-mini"
    return "openrouter/free"


def ai_model_for(provider: str) -> str:
    specific = {
        "openrouter": "AI_OPENROUTER_MODEL",
        "gemini": "AI_GEMINI_MODEL",
        "groq": "AI_GROQ_MODEL",
        "openai": "AI_OPENAI_MODEL",
        "custom": "AI_CUSTOM_MODEL",
    }.get(provider, "AI_MODEL")
    return get_config(specific, "").strip() or get_config("AI_MODEL", "").strip() or ai_default_model_for(provider)


def ai_model() -> str:
    return ai_model_for(ai_provider())


def ai_api_key() -> str:
    # Compatibility helper: first key in the first available provider.
    for provider in ai_provider_order():
        keys = ai_keys_for_provider(provider)
        if keys:
            return keys[0]
    return ""


def masked_count_for(provider: str) -> str:
    count = len(ai_keys_for_provider(provider))
    return f"{count} مفتاح" if count else "لا يوجد"


def ai_status_text() -> str:
    counts = [f"{provider}: {masked_count_for(provider)}" for provider in ai_provider_order()]
    if ai_enabled():
        return "مفعل — " + " | ".join(counts)
    return "غير مفعل — " + " | ".join(counts)


def ai_default_model() -> str:
    return ai_default_model_for(ai_provider())


def ai_endpoint_for(provider: str) -> str:
    if provider == "gemini":
        return ""
    if provider == "openai":
        return get_config("AI_OPENAI_BASE_URL", get_config("AI_BASE_URL", "https://api.openai.com/v1/chat/completions"))
    if provider == "groq":
        return get_config("AI_GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
    if provider == "custom":
        return get_config("AI_CUSTOM_BASE_URL", get_config("AI_BASE_URL", "")).strip()
    return get_config("AI_OPENROUTER_BASE_URL", get_config("AI_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"))


def ai_provider_display_name(provider: str) -> str:
    return {
        "openrouter": "OpenRouter",
        "gemini": "Gemini",
        "groq": "Groq",
        "openai": "OpenAI",
        "custom": "Custom",
    }.get(provider, provider)


load_dotenv_file()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize(text: str) -> str:
    text = (text or "").strip().lower()
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "ـ": "",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)  # Arabic tashkeel
    text = re.sub(r"[^\w\s\u0600-\u06FF]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_aliases(aliases: str) -> List[str]:
    if not aliases:
        return []
    parts = re.split(r"[|,،;؛\n]+", aliases)
    return [part.strip() for part in parts if part and part.strip()]


def ensure_csv_file(path: Path, fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()


def ensure_products_file() -> None:
    ensure_csv_file(PRODUCTS_FILE, PRODUCT_FIELDS)


def ensure_orders_file() -> None:
    ensure_csv_file(ORDERS_FILE, ORDER_FIELDS)


def load_products() -> List[dict]:
    ensure_products_file()
    products: List[dict] = []
    with PRODUCTS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or row.get("اسم") or row.get("الاسم") or "").strip()
            if not name:
                continue
            aliases = (row.get("aliases") or row.get("أسماء بديلة") or row.get("اسماء بديلة") or "").strip()
            available = (row.get("available") or row.get("التوفر") or "متوفر").strip() or "متوفر"
            item = {
                "name": name,
                "aliases": aliases,
                "price": (row.get("price") or row.get("السعر") or "").strip(),
                "available": available,
                "notes": (row.get("notes") or row.get("ملاحظات") or row.get("ملاحظة") or "").strip(),
            }
            item["keywords"] = [item["name"], *split_aliases(item["aliases"])]
            products.append(item)
    return products


def save_products(products: List[dict]) -> None:
    PRODUCTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="products_", suffix=".csv", dir=str(PRODUCTS_FILE.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=PRODUCT_FIELDS)
            writer.writeheader()
            for item in products:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                writer.writerow(
                    {
                        "name": name,
                        "aliases": str(item.get("aliases", "")).strip(),
                        "price": str(item.get("price", "")).strip(),
                        "available": str(item.get("available", "")).strip() or "متوفر",
                        "notes": str(item.get("notes", "")).strip(),
                    }
                )
        tmp_path.replace(PRODUCTS_FILE)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def backup_file(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, backup)
    return backup


def product_key(name: str) -> str:
    return normalize(name)


def upsert_product(new_item: dict) -> Tuple[List[dict], str]:
    products = load_products()
    key = product_key(new_item.get("name", ""))
    for item in products:
        if product_key(item.get("name", "")) == key:
            item.update(new_item)
            save_products(products)
            return products, "updated"
    products.append(new_item)
    save_products(products)
    return products, "added"


def extract_product_query(text: str) -> str:
    """Turn natural customer wording into a product-focused query."""
    q = normalize(text)
    if not q:
        return ""

    phrase_replacements = [
        "السلام عليكم", "السلام", "مرحبا", "اهلا", "اهلين", "لو سمحت", "من فضلك", "بالله",
        "كم سعر", "شن سعر", "شنو سعر", "بكم", "قداش", "السعر", "سعر",
        "عندكم", "موجود", "موجوده", "متوفر", "متوفره", "فيه", "في", "هل يوجد",
        "اريد", "نريد", "نبي", "ابي", "ابغى", "ممكن", "عطيني", "احتاج",
        "دواء", "علاج", "حبوب", "كبسولات", "شراب", "علبه", "علبة", "شريط", "قطره", "قطرة",
        "الصيدليه", "الصيدلية", "بدر", "البشرية", "البشريه",
        "do you have", "have", "price", "how much", "need", "want", "please", "medicine", "tablet", "capsule",
    ]
    for phrase in sorted(phrase_replacements, key=len, reverse=True):
        q = q.replace(normalize(phrase), " ")
    q = re.sub(r"\s+", " ", q).strip()
    return q


def match_score(query: str, keyword: str) -> float:
    q = normalize(query)
    k = normalize(keyword)
    if not q or not k:
        return 0.0
    if q == k:
        return 1.0
    if k in q:
        return 0.96
    if q in k and len(q) >= 3:
        return 0.92

    q_tokens = [t for t in q.split() if len(t) > 1]
    k_tokens = [t for t in k.split() if len(t) > 1]
    if q_tokens and k_tokens:
        shared = len(set(q_tokens) & set(k_tokens))
        if shared:
            token_score = shared / max(len(set(k_tokens)), 1)
            if token_score >= 0.6:
                return max(0.86, token_score)

    return SequenceMatcher(None, q, k).ratio()


def ranked_products(text: str) -> List[Tuple[float, dict]]:
    products = load_products()
    candidates = [text, extract_product_query(text)]
    # Keep unique non-empty candidates.
    seen = set()
    candidates = [c for c in candidates if c and not (normalize(c) in seen or seen.add(normalize(c)))]

    ranked: List[Tuple[float, dict]] = []
    for item in products:
        best_score = 0.0
        for candidate in candidates:
            for keyword in item.get("keywords", [item.get("name", "")]):
                best_score = max(best_score, match_score(candidate, keyword))
        if best_score > 0:
            ranked.append((best_score, item))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def category_suggestions(text: str, limit: int = 4) -> List[dict]:
    q = normalize(text)
    products = load_products()
    hints = {
        "صداع": ["بنادول", "فيفادول", "بروفين", "باراسيتامول", "panadol", "paracetamol"],
        "مسكن": ["بنادول", "فيفادول", "بروفين", "كتافلام", "ديكلوفيناك"],
        "الم": ["بنادول", "فيفادول", "بروفين", "كتافلام"],
        "حراره": ["بنادول", "فيفادول", "باراسيتامول", "panadol"],
        "مضاد": ["أموكسيل", "اموكسيل", "أوجمنتين", "اوجمنتين", "أزيثرومايسين"],
        "حموضه": ["جلوسيد", "اوميبرازول", "omeprazole"],
        "معده": ["جلوسيد", "موتيليوم", "سماكتا"],
        "اسهال": ["سماكتا"],
        "ضغط": ["أملور", "كونكور", "كابوتين", "لازيكس"],
    }
    wanted: List[str] = []
    for key, names in hints.items():
        if normalize(key) in q:
            wanted.extend(names)
    if not wanted:
        return []

    result: List[dict] = []
    for item in products:
        haystack = normalize(" ".join([item.get("name", ""), item.get("aliases", ""), item.get("notes", "")]))
        if any(normalize(name) in haystack for name in wanted):
            result.append(item)
        if len(result) >= limit:
            break
    return result


def find_product(text: str) -> Optional[dict]:
    ranked = ranked_products(text)
    if ranked and ranked[0][0] >= 0.76:
        return ranked[0][1]
    return None


def suggested_products(text: str, limit: int = 4) -> List[dict]:
    category = category_suggestions(text, limit=limit)
    if category:
        return category[:limit]
    ranked = [item for score, item in ranked_products(text) if score >= 0.48]
    # De-duplicate by normalized product name.
    out: List[dict] = []
    seen = set()
    for item in ranked:
        key = normalize(item.get("name", ""))
        if key and key not in seen:
            out.append(item)
            seen.add(key)
        if len(out) >= limit:
            break
    return out



def json_from_model_text(content: str) -> dict:
    """Extract a JSON object from an LLM answer safely."""
    content = (content or "").strip()
    if not content:
        return {}
    content = content.replace("```json", "```").strip()
    if "```" in content:
        parts = content.split("```")
        # Prefer the largest fenced block.
        content = max(parts, key=len).strip()
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        content = content[start:end + 1]
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def compact_catalog_for_ai(text: str, limit: int = 80) -> List[dict]:
    """Send a compact product catalog to the AI without leaking orders or secrets."""
    products = load_products()
    ranked = ranked_products(text)
    chosen: List[dict] = []
    seen = set()

    # Start with likely local matches.
    for score, item in ranked:
        key = normalize(item.get("name", ""))
        if key and key not in seen:
            chosen.append(item)
            seen.add(key)
        if len(chosen) >= min(limit, 30):
            break

    # Add category suggestions.
    for item in category_suggestions(text, limit=20):
        key = normalize(item.get("name", ""))
        if key and key not in seen:
            chosen.append(item)
            seen.add(key)

    # If still little context, add beginning of catalog.
    for item in products:
        key = normalize(item.get("name", ""))
        if key and key not in seen:
            chosen.append(item)
            seen.add(key)
        if len(chosen) >= limit:
            break

    compact = []
    for item in chosen[:limit]:
        compact.append({
            "name": item.get("name", ""),
            "aliases": item.get("aliases", ""),
            "notes": item.get("notes", ""),
        })
    return compact


def call_ai_once(provider: str, key: str, model: str, user_text: str, catalog: List[dict]) -> dict:
    """Call one provider/key. Exceptions are handled by the caller."""
    system_prompt = (
        "أنت مساعد واتساب لصيدلية في ليبيا. مهمتك فقط فهم رسالة الزبون وتحويلها إلى JSON. "
        "لا تعطِ تشخيصاً طبياً ولا جرعات ولا علاجاً. لا تخترع منتجات غير موجودة في الكتالوج. "
        "لو الزبون يسأل عن سعر/توفر منتج، استخرج اسم المنتج المقصود. "
        "لو يسأل عن جرعة/استعمال/هل يناسب حامل أو طفل، اجعل intent=medical_advice. "
        "لو قال نعم أو حجز، intent=reservation_yes. لو قال لا أو إلغاء، intent=reservation_no. "
        "لو كانت تحية فقط، intent=greeting. "
        "أرجع JSON فقط بهذا الشكل: "
        "{\"intent\":\"product_lookup|greeting|reservation_yes|reservation_no|medical_advice|unknown\","
        "\"product_query\":\"\",\"matched_product_names\":[],\"suggested_category\":\"\"}"
    )
    user_prompt = json.dumps(
        {
            "business": business_name(),
            "city": business_city(),
            "message": user_text,
            "catalog": catalog,
        },
        ensure_ascii=False,
    )

    if provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent?key={urllib.parse.quote(key)}"
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_prompt}]}
            ],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 350},
        }
        headers = {"Content-Type": "application/json"}
    else:
        url = ai_endpoint_for(provider)
        if not url:
            raise RuntimeError(f"AI endpoint is missing for provider {provider}")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 350,
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": get_config("AI_HTTP_REFERER", "https://pricebot.local"),
            "X-Title": get_config("AI_APP_TITLE", "PriceBot"),
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        if provider == "gemini":
            content = ""
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if part.get("text"):
                        content += part.get("text", "")
        else:
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return json_from_model_text(content)


def call_ai_json(user_text: str) -> dict:
    """Call real external AI APIs with provider/key fallback."""
    if not ai_enabled():
        return {}

    catalog = compact_catalog_for_ai(user_text)
    last_error = ""
    for provider in ai_provider_order():
        keys = ai_keys_for_provider(provider)
        if not keys:
            continue
        model = ai_model_for(provider)
        for index, key in enumerate(keys, 1):
            try:
                parsed = call_ai_once(provider, key, model, user_text, catalog)
                if parsed:
                    print(f"AI OK: provider={provider} key_index={index} model={model} parsed={parsed}", flush=True)
                    return parsed
                last_error = f"{provider} key {index}: empty parse"
                print("AI PARSE EMPTY:", last_error, flush=True)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")[:700]
                last_error = f"{provider} key {index}: HTTP {exc.code} {body}"
                print("AI HTTP ERROR:", last_error, flush=True)
                # Continue to next key/provider on quota/auth/rate-limit/model errors.
                continue
            except Exception as exc:
                last_error = f"{provider} key {index}: {exc}"
                print("AI EXCEPTION:", last_error, flush=True)
                continue
    print("AI FALLBACK EXHAUSTED:", last_error, flush=True)
    return {}


def product_by_ai_names(ai_data: dict) -> Optional[dict]:
    names = []
    if ai_data.get("product_query"):
        names.append(str(ai_data.get("product_query", "")))
    for name in ai_data.get("matched_product_names") or []:
        if isinstance(name, str):
            names.append(name)
    for name in names:
        item = find_product(name)
        if item:
            return item
        # Strong exact/alias scan as backup.
        n = normalize(name)
        for product in load_products():
            keys = [product.get("name", "")] + split_aliases(product.get("aliases", ""))
            if any(normalize(k) == n for k in keys):
                return product
    return None


def suggestions_from_ai(ai_data: dict, user_text: str, limit: int = 4) -> List[dict]:
    items = []
    seen = set()
    names = []
    for name in ai_data.get("matched_product_names") or []:
        if isinstance(name, str):
            names.append(name)
    if ai_data.get("product_query"):
        names.append(str(ai_data.get("product_query")))
    if ai_data.get("suggested_category"):
        names.append(str(ai_data.get("suggested_category")))
    for name in names:
        for score, product in ranked_products(name):
            if score < 0.45:
                continue
            key = normalize(product.get("name", ""))
            if key and key not in seen:
                items.append(product)
                seen.add(key)
            if len(items) >= limit:
                return items
    for product in suggested_products(user_text, limit=limit):
        key = normalize(product.get("name", ""))
        if key and key not in seen:
            items.append(product)
            seen.add(key)
        if len(items) >= limit:
            break
    return items

def is_greeting(text: str) -> bool:
    q = normalize(text)
    greetings = ["السلام عليكم", "سلام", "مرحبا", "اهلا", "اهلين", "هاي", "hi", "hello"]
    return any(normalize(g) in q for g in greetings) and len(q) <= 45






def _safe_text_func(func_name: str, default: str) -> str:
    try:
        fn = globals().get(func_name)
        if callable(fn):
            val = str(fn()).strip()
            return val or default
    except Exception:
        pass
    return default


def pharmacy_name() -> str:
    return _safe_text_func("business_name", "صيدلية بدر البشرية")


def pharmacy_city() -> str:
    return _safe_text_func("business_city", "أجدابيا")


def pharmacy_hours() -> str:
    return _safe_text_func("business_hours", "24 ساعة")


def pharmacy_delivery() -> str:
    return _safe_text_func("delivery_text", "التوصيل غير متوفر حالياً")


def _product_terms(item: dict) -> list:
    terms = []
    name = str(item.get("name", "")).strip()
    if name:
        terms.append(name)
    aliases = str(item.get("aliases", "") or "")
    for part in re.split(r"[,،;؛|\n]+", aliases):
        part = part.strip()
        if part:
            terms.append(part)
    clean = []
    seen = set()
    for t in terms:
        nt = normalize(t)
        if nt and nt not in seen:
            clean.append(nt)
            seen.add(nt)
    return clean


def exact_product_in_text(text: str):
    q = normalize(text or "")
    if not q:
        return None
    try:
        products = load_products()
    except Exception:
        products = []
    for item in products:
        for term in _product_terms(item):
            if len(term) >= 2 and (q == term or term in q):
                return item
    return None


def asks_medical_advice(text: str) -> bool:
    """
    Strict safety gate:
    The bot must not recommend treatment, dosage, or products for symptoms.
    It only answers price/availability for a clearly named product.
    """
    q = normalize(text or "")
    if not q:
        return False
    if exact_product_in_text(text or ""):
        return False

    medical_words = [
        "جرعه", "جرعة", "جرعات", "كم حبه", "كم حبة", "كم مره", "كم مرة",
        "استعمل", "استخدم", "طريقة الاستخدام", "ينفع", "ينفعني", "عادي",
        "شن ناخذ", "شن نأخذ", "ماذا اخذ", "ماذا آخذ", "نبي علاج", "ابي علاج",
        "علاج", "دواء ل", "حاجه ل", "حاجة ل", "شن ندير", "كيف ندير",
        "حامل", "حمل", "مرضع", "رضاعه", "رضاعة", "طفل", "رضيع",
        "سكر", "ضغط", "حساسيه", "حساسية", "اعراض", "أعراض", "تشخيص",
        "صداع", "راس", "رأس", "الم راس", "ألم راس", "وجع راس",
        "حراره", "حرارة", "سخونه", "سخونية",
        "كحه", "كحة", "سعال", "زكام", "رشح", "انفلونزا",
        "اسهال", "إسهال", "مغص", "معده", "معدة", "قيء", "ترجيع",
        "حموضه", "حموضة", "حرقان", "التهاب",
        "الم", "ألم", "وجع", "طفح", "حكة", "حكه", "دوخه", "دوخة",
    ]
    return any(normalize(w) in q for w in medical_words)


def build_welcome_reply() -> str:
    return (
        f"شكراً لتواصلكم مع {pharmacy_name()} 🌿\n\n"
        f"📍 {pharmacy_city()}\n"
        f"🕒 العمل: {pharmacy_hours()}\n"
        f"🚚 {pharmacy_delivery()}\n\n"
        "يمكنك إرسال اسم الدواء أو المنتج، وسأعرض لك السعر والتوفر مباشرة.\n\n"
        "أمثلة:\n"
        "• بنادول\n"
        "• بروفين\n"
        "• أوجمنتين\n\n"
        "ملاحظة: البوت مخصص للاستعلام عن السعر والتوفر والحجز فقط، ولا يقدم وصفات أو جرعات طبية."
    )


def build_medical_safety_reply(text: str = "") -> str:
    return (
        f"{pharmacy_name()} 🌿\n\n"
        "حرصاً على السلامة، لا يقدم البوت تشخيصاً أو وصفات أو جرعات طبية.\n\n"
        "يمكنني مساعدتك في:\n"
        "• معرفة توفر دواء محدد\n"
        "• عرض السعر\n"
        "• تسجيل الحجز\n\n"
        "اكتب اسم المنتج فقط للاستعلام عنه."
    )


def build_product_reply(item: dict, original_text: str = "") -> str:
    name = str(item.get("name", "")).strip()
    available = str(item.get("available", "") or "متوفر").strip()
    price = str(item.get("price", "")).strip()
    notes = str(item.get("notes", "")).strip()
    lines = [
        f"{pharmacy_name()} 🌿",
        "",
        f"✅ المنتج: {name}",
        f"📦 الحالة: {available}",
    ]
    if price:
        lines.append(f"💰 السعر: {price}")
    if notes:
        lines.append(f"📝 ملاحظة: {notes}")
    lines += ["", "للحجز اكتب: نعم"]
    return "\n".join(lines)


def build_suggestion_question(item: dict, alternatives=None) -> str:
    alternatives = alternatives or []
    name = str(item.get("name", "")).strip()
    lines = [
        f"{pharmacy_name()} 🌿",
        "",
        f"هل تقصد: {name}؟",
        "",
        "إذا نعم اكتب: نعم",
        "وإذا لا، أرسل اسم المنتج بشكل أوضح.",
    ]
    alt_names = []
    for alt in alternatives:
        alt_name = str(alt.get("name", "")).strip()
        if alt_name and alt_name != name and alt_name not in alt_names:
            alt_names.append(alt_name)
        if len(alt_names) >= 3:
            break
    if alt_names:
        lines += ["", "خيارات قريبة:"]
        lines += [f"• {n}" for n in alt_names]
    return "\n".join(lines)


def build_suggestions_reply(items, from_number: str = "") -> str:
    if not items:
        return build_not_found_reply("")
    first = items[0]
    if from_number:
        PENDING_SUGGESTION[from_number] = first
    return build_suggestion_question(first, items[1:])


def build_not_found_reply(text: str) -> str:
    if asks_medical_advice(text):
        return build_medical_safety_reply(text)
    return (
        f"{pharmacy_name()} 🌿\n\n"
        "عذراً، لم أتمكن من معرفة اسم المنتج بدقة.\n"
        "اكتب اسم الدواء أو المنتج كما هو مكتوب على العلبة.\n\n"
        "مثال:\n"
        "• بنادول\n"
        "• بروفين\n"
        "• أوجمنتين"
    )


def build_order_success_reply(item: dict) -> str:
    name = str(item.get("name", "")).strip()
    price = str(item.get("price", "")).strip()
    lines = ["✅ تم استلام طلبك بنجاح", "", f"المنتج: {name}"]
    if price:
        lines.append(f"السعر: {price}")
    lines += ["", "سيتواصل معك موظف الصيدلية لتأكيد الطلب.", f"شكراً لتواصلكم مع {pharmacy_name()}."]
    return "\n".join(lines)


def build_image_under_review_reply() -> str:
    return (
        f"{pharmacy_name()} 🌿\n\n"
        "تم استلام الصورة وتحويلها للصيدلي للتأكيد.\n"
        "سيتواصل معك الموظف عند مراجعتها."
    )


def build_reply(text: str, from_number: str = "") -> str:
    raw_text = text or ""
    query = normalize(raw_text)
    yes_words = [normalize(x) for x in ["نعم", "اي", "تمام", "yes", "ok", "اوكي"]]
    reserve_words = [normalize(x) for x in ["حجز", "احجز", "نبي حجز", "اريد حجز", "أريد حجز"]]
    no_words = [normalize(x) for x in ["لا", "الغاء", "إلغاء", "cancel", "no"]]

    if from_number and from_number in PENDING_SUGGESTION and query in yes_words:
        item = PENDING_SUGGESTION.pop(from_number)
        LAST_PRODUCT[from_number] = item
        return build_product_reply(item, raw_text)

    if from_number and from_number in PENDING_SUGGESTION and any(w in query for w in no_words):
        PENDING_SUGGESTION.pop(from_number, None)
        return f"{pharmacy_name()} 🌿\n\nتمام. أرسل اسم المنتج بشكل أوضح."

    if from_number and from_number in LAST_PRODUCT and any(w in query for w in no_words):
        LAST_PRODUCT.pop(from_number, None)
        return f"{pharmacy_name()} 🌿\n\nتم إلغاء الحجز المؤقت. يمكنك كتابة اسم منتج آخر للاستعلام."

    if from_number and from_number in LAST_PRODUCT and (
        query in yes_words or any(w in query for w in reserve_words)
    ):
        item = LAST_PRODUCT[from_number]
        save_order(from_number, item, raw_text)
        LAST_PRODUCT.pop(from_number, None)
        PENDING_SUGGESTION.pop(from_number, None)
        return build_order_success_reply(item)

    exact_item = exact_product_in_text(raw_text)
    if exact_item:
        if from_number:
            LAST_PRODUCT[from_number] = exact_item
            PENDING_SUGGESTION.pop(from_number, None)
        return build_product_reply(exact_item, raw_text)

    if is_greeting(raw_text):
        return build_welcome_reply()

    if asks_medical_advice(raw_text):
        return build_medical_safety_reply(raw_text)

    fuzzy_item = find_product(raw_text)
    if fuzzy_item:
        suggestions = [fuzzy_item]
        try:
            for s in suggested_products(raw_text):
                if s.get("name") != fuzzy_item.get("name"):
                    suggestions.append(s)
        except Exception:
            pass
        return build_suggestions_reply(suggestions, from_number)

    ai_data = call_ai_json(raw_text) if ai_enabled() else {}
    intent = str(ai_data.get("intent", "")).strip().lower() if ai_data else ""
    if intent == "greeting":
        return build_welcome_reply()
    if intent == "medical_advice":
        return build_medical_safety_reply(raw_text)

    ai_item = product_by_ai_names(ai_data) if ai_data else None
    if ai_item:
        if from_number:
            PENDING_SUGGESTION[from_number] = ai_item
        return build_suggestion_question(ai_item)

    if ai_data:
        ai_suggestions = suggestions_from_ai(ai_data, raw_text)
        if ai_suggestions:
            return build_suggestions_reply(ai_suggestions, from_number)

    suggestions = suggested_products(raw_text)
    if suggestions:
        return build_suggestions_reply(suggestions, from_number)
    return build_not_found_reply(raw_text)

def send_whatsapp_message(to_number: str, message: str) -> bool:
    token = get_access_token()
    phone_number_id = get_phone_number_id()
    if not token or not phone_number_id:
        print("SEND ERROR: Missing WhatsApp token or PHONE_NUMBER_ID", flush=True)
        return False

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            print("SEND OK:", response.read().decode("utf-8"), flush=True)
            return True
    except urllib.error.HTTPError as exc:
        print("SEND ERROR:", exc.code, exc.read().decode("utf-8", errors="ignore"), flush=True)
    except Exception as exc:
        print("SEND EXCEPTION:", str(exc), flush=True)
    return False




def notify_admin(message: str, customer_phone: str = "") -> bool:
    admin_phone = admin_notify_phone()
    customer_phone = normalize_phone(customer_phone)
    if not admin_phone:
        print("ADMIN NOTIFY SKIP: ADMIN_NOTIFY_PHONE not set", flush=True)
        return False
    if customer_phone and admin_phone == customer_phone:
        print("ADMIN NOTIFY SKIP: admin phone equals customer phone", flush=True)
        return False
    return send_whatsapp_message(admin_phone, message)


def build_admin_order_message(phone: str, item: dict, message: str) -> str:
    return (
        f"🔔 طلب حجز جديد - {pharmacy_name()}\n\n"
        f"رقم الزبون: {phone}\n"
        f"المنتج: {item.get('name', '')}\n"
        f"السعر: {item.get('price', '')}\n"
        f"التوفر: {item.get('available', '')}\n"
        f"ملاحظة: {item.get('notes', '')}\n"
        f"رسالة الزبون: {message or '-'}\n"
        f"الوقت: {now_str()}\n\n"
        "افتح لوحة الطلبات لمتابعته."
    )


def save_review_order(phone: str, title: str, message: str, media_url: str = "") -> None:
    item = {
        "name": title,
        "price": "",
        "available": "بانتظار مراجعة الصيدلي",
        "notes": "صورة/روشتة تحتاج تأكيد" if media_url else "تحتاج مراجعة",
    }
    save_order(phone, item, (message or "") + (f"\nرابط الصورة: {media_url}" if media_url else ""))


def get_whatsapp_media_info(media_id: str) -> dict:
    token = get_access_token()
    if not token or not media_id:
        return {}
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{urllib.parse.quote(media_id)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception as exc:
        print("MEDIA INFO ERROR:", str(exc), flush=True)
        return {}


def download_whatsapp_media(media_id: str) -> Tuple[bytes, str, str]:
    info = get_whatsapp_media_info(media_id)
    media_url = info.get("url", "")
    mime_type = info.get("mime_type", "image/jpeg") or "image/jpeg"
    if not media_url:
        return b"", mime_type, ""
    token = get_access_token()
    req = urllib.request.Request(media_url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read(), mime_type, info.get("sha256", "")
    except Exception as exc:
        print("MEDIA DOWNLOAD ERROR:", str(exc), flush=True)
        return b"", mime_type, info.get("sha256", "")


def save_incoming_media(media_bytes: bytes, mime_type: str, media_id: str) -> str:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    ext = ".jpg"
    if "png" in mime_type:
        ext = ".png"
    elif "webp" in mime_type:
        ext = ".webp"
    elif "pdf" in mime_type:
        ext = ".pdf"
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "", media_id or datetime.now().strftime("%Y%m%d%H%M%S"))[:80]
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_id}{ext}"
    path = MEDIA_DIR / filename
    path.write_bytes(media_bytes)
    return filename


def admin_media_url(filename: str) -> str:
    return f"{public_base_url()}/admin/media/{urllib.parse.quote(filename)}?key={urllib.parse.quote(ADMIN_KEY)}"


def image_ai_enabled() -> bool:
    return bool(ai_keys_for_provider("gemini"))


def call_gemini_vision_json(media_bytes: bytes, mime_type: str) -> dict:
    keys = ai_keys_for_provider("gemini")
    if not keys or not media_bytes:
        return {}
    model = ai_model_for("gemini") or "gemini-2.5-flash-lite"
    catalog = compact_catalog_for_ai("صورة منتج", limit=120)
    prompt = (
        "أنت مساعد صيدلية. حلل الصورة وأرجع JSON فقط. "
        "لا تقدم نصائح طبية. إذا كانت الصورة روشتة/وصفة طبية/ورقة بخط يد/أدوية كثيرة غير واضحة، اجعل image_type=prescription_or_unclear وrequires_admin_review=true. "
        "إذا كانت صورة علبة منتج دوائي أو منتج صيدلية واضح، اجعل image_type=product_packaging واستخرج أسماء المنتجات الظاهرة. "
        "استخدم الكتالوج فقط للمطابقة ولا تخترع منتجات. "
        "الشكل المطلوب: {\"image_type\":\"product_packaging|prescription_or_unclear|unknown\",\"product_names\":[],\"matched_product_names\":[],\"requires_admin_review\":true|false,\"confidence\":0.0} "
        f"\nCatalog: {json.dumps(catalog, ensure_ascii=False)}"
    )
    b64 = base64.b64encode(media_bytes).decode("ascii")
    for index, key in enumerate(keys, 1):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent?key={urllib.parse.quote(key)}"
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type or "image/jpeg", "data": b64}},
                ],
            }],
            "generationConfig": {"temperature": 0.05, "maxOutputTokens": 500},
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = json.loads(response.read().decode("utf-8", errors="ignore"))
                content = ""
                for cand in raw.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        content += part.get("text", "") or ""
                data = json_from_model_text(content)
                if data:
                    print(f"VISION AI OK: gemini key_index={index} parsed={data}", flush=True)
                    return data
        except urllib.error.HTTPError as exc:
            print("VISION AI HTTP ERROR:", exc.code, exc.read().decode("utf-8", errors="ignore")[:600], flush=True)
        except Exception as exc:
            print("VISION AI EXCEPTION:", str(exc), flush=True)
    return {}


def product_from_vision(data: dict) -> Optional[dict]:
    names: List[str] = []
    for key in ["matched_product_names", "product_names"]:
        for name in data.get(key) or []:
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    for name in names:
        item = find_product(name)
        if item:
            return item
        n = normalize(name)
        for product in load_products():
            keys = [product.get("name", "")] + split_aliases(product.get("aliases", ""))
            if any(normalize(k) == n for k in keys):
                return product
    return None


def process_image_message(msg: dict, from_number: str) -> str:
    image = msg.get("image", {}) or {}
    media_id = image.get("id", "")
    caption = image.get("caption", "") or ""
    media_bytes, mime_type, _sha = download_whatsapp_media(media_id)
    filename = save_incoming_media(media_bytes, mime_type, media_id) if media_bytes else ""
    link = admin_media_url(filename) if filename else ""

    if not media_bytes:
        save_review_order(from_number, "صورة تحتاج مراجعة", "تعذر تحميل الصورة من واتساب", link)
        notify_admin(
            f"📷 صورة تحتاج مراجعة - {pharmacy_name()}\n\nرقم الزبون: {from_number}\nسبب التحويل: تعذر تحميل الصورة من واتساب\nالوقت: {now_str()}",
            from_number,
        )
        return build_image_under_review_reply()

    vision = call_gemini_vision_json(media_bytes, mime_type) if image_ai_enabled() else {}
    image_type = str(vision.get("image_type", "")).lower()
    requires_review = bool(vision.get("requires_admin_review"))

    if image_type == "product_packaging" and not requires_review:
        item = product_from_vision(vision)
        if item:
            LAST_PRODUCT[from_number] = item
            return build_product_reply(item, caption)
        # If vision saw names but no catalog match, ask admin to confirm instead of guessing.
        product_names = ", ".join([str(x) for x in (vision.get("product_names") or vision.get("matched_product_names") or []) if x])
        save_review_order(from_number, "صورة منتج غير موجودة بالكتالوج", f"الأسماء المقروءة: {product_names or '-'}", link)
        notify_admin(
            f"📷 صورة منتج تحتاج إضافة/تأكيد - {pharmacy_name()}\n\nرقم الزبون: {from_number}\nالأسماء المقروءة: {product_names or '-'}\nرابط الصورة: {link or '-'}\nالوقت: {now_str()}",
            from_number,
        )
        return (
            f"{pharmacy_name()} 🌿\n\n"
            "وصلت صورة المنتج، لكن لم أجد مطابقة مؤكدة في قائمة المنتجات.\n"
            "تم تحويلها للصيدلي للتأكيد."
        )

    reason = "روشتة أو صورة غير واضحة" if image_type in {"prescription_or_unclear", "unknown", ""} else image_type
    save_review_order(from_number, "روشتة/صورة تحتاج مراجعة", f"نوع الصورة: {reason}", link)
    notify_admin(
        f"📷 روشتة/صورة تحتاج مراجعة - {pharmacy_name()}\n\nرقم الزبون: {from_number}\nنوع الصورة: {reason}\nرابط الصورة: {link or '-'}\nالوقت: {now_str()}\n\nيرجى مراجعتها من لوحة الطلبات أو التواصل مع الزبون.",
        from_number,
    )
    return build_image_under_review_reply()


def save_order(phone: str, item: dict, message: str) -> None:
    ensure_orders_file()
    with ORDERS_FILE.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ORDER_FIELDS)
        writer.writerow(
            {
                "time": now_str(),
                "phone": phone,
                "product": item.get("name", ""),
                "price": item.get("price", ""),
                "available": item.get("available", ""),
                "notes": item.get("notes", ""),
                "message": message,
                "status": "new",
            }
        )

    notify_admin(build_admin_order_message(phone, item, message), phone)

def read_orders() -> List[dict]:
    ensure_orders_file()
    with ORDERS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_orders(rows: List[dict]) -> None:
    ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="orders_", suffix=".csv", dir=str(ORDERS_FILE.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ORDER_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in ORDER_FIELDS})
        tmp_path.replace(ORDERS_FILE)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def check_admin(key: str) -> bool:
    return bool(key) and key == ADMIN_KEY


def safe_redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


BASE_CSS = """
:root{
  --bg:#f6f8fb; --card:#ffffff; --text:#172026; --muted:#667085; --line:#e6e9ef;
  --brand:#0f766e; --brand2:#115e59; --soft:#ecfdf5; --danger:#b42318; --ok:#15803d;
  --warn:#b45309; --shadow:0 10px 26px rgba(16,24,40,.08); --radius:18px;
}
*{box-sizing:border-box} body{margin:0;padding:18px;background:linear-gradient(180deg,#eef7f5 0,#f7f8fb 220px);color:var(--text);font-family:Arial,Tahoma,sans-serif;direction:rtl}
a{color:var(--brand);text-decoration:none} h1{font-size:28px;margin:8px 0 12px} h2{font-size:22px;margin:4px 0 14px}.container{max-width:1180px;margin:0 auto}.hero{background:linear-gradient(135deg,#0f766e,#134e4a);color:#fff;border-radius:24px;padding:22px;box-shadow:var(--shadow);margin:6px 0 14px}.hero h1{margin:0 0 8px}.hero p{margin:0;color:#d8fffb}.box,.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px;margin:14px 0;box-shadow:var(--shadow)}.nav{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:14px 0}.btn,a.btn,button,input[type=submit]{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:0;border-radius:12px;padding:12px 15px;font-size:16px;font-weight:700;background:var(--brand);color:#fff;cursor:pointer;text-align:center}.btn.secondary,a.btn.secondary{background:#fff;color:#0f5f59;border:1px solid #b9ddd8}.btn.danger,a.btn.danger{background:#fff1f0;color:var(--danger);border:1px solid #ffcbc5}.btn.ok,a.btn.ok{background:#ecfdf3;color:var(--ok);border:1px solid #bbf7d0}.btn.warn{background:#fffbeb;color:#92400e;border:1px solid #fde68a}.msg{color:var(--ok);font-weight:800;text-align:center}.notice{color:var(--muted);font-size:14px;line-height:1.9}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.field{display:flex;flex-direction:column;gap:7px}label{font-weight:800}input,textarea,select{width:100%;border:1px solid #cfd6dd;border-radius:12px;padding:12px;font-size:16px;background:#fff}textarea{min-height:180px;line-height:1.7}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.stat{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px;box-shadow:var(--shadow)}.stat b{font-size:28px;color:var(--brand)}.stat span{display:block;color:var(--muted);margin-top:4px}.product-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(285px,1fr));gap:14px}.product-title{font-size:20px;font-weight:900;margin-bottom:8px}.product-meta{color:var(--muted);font-size:14px;margin:4px 0 12px}.actions{display:flex;flex-wrap:wrap;gap:9px;align-items:center;margin-top:10px}.card-form{display:grid;gap:10px}.order-card{position:relative;display:grid;gap:8px}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:5px 10px;font-weight:800;font-size:13px}.badge.new{background:#fff7ed;color:#c2410c}.badge.done{background:#ecfdf3;color:#15803d}.order-head{display:flex;justify-content:space-between;gap:10px;align-items:center;border-bottom:1px solid var(--line);padding-bottom:10px}.order-title{font-weight:900;font-size:19px}.order-row{display:flex;justify-content:space-between;gap:12px;border-bottom:1px dashed var(--line);padding:6px 0}.order-row strong{white-space:nowrap;color:#344054}.status-new{color:var(--warn);font-weight:900}.status-done{color:var(--ok);font-weight:900}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;background:#fff}th,td{border:1px solid var(--line);padding:10px;text-align:center}th{background:#f0f2f4}.admin-hint{background:#f8fafc;border:1px dashed #cbd5e1;border-radius:14px;padding:12px;color:#475569;line-height:1.8}pre{background:#0b1220;color:#e5e7eb;border-radius:14px;padding:14px;overflow:auto}
@media(max-width:900px){.nav{grid-template-columns:repeat(2,minmax(0,1fr))}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.form-grid{grid-template-columns:1fr}}
@media(max-width:600px){body{padding:10px}h1{font-size:24px}.hero{padding:17px;border-radius:18px}.box,.card{padding:14px;border-radius:15px}.nav{grid-template-columns:1fr 1fr}.product-grid{grid-template-columns:1fr}.actions .btn,.actions button{flex:1 1 auto}.stats{grid-template-columns:1fr 1fr}.stat b{font-size:22px}}
"""


def page_layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{e(title)}</title>
  <style>{BASE_CSS}</style>
</head>
<body>
  <div class="container">
    {body}
  </div>
</body>
</html>"""



def page_layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{e(title)}</title>
  <style>{BASE_CSS}</style>
</head>
<body>
  <div class="container">
    {body}
  </div>
</body>
</html>"""


def admin_nav(key: str) -> str:
    key_q = urllib.parse.quote(key)
    return f"""
    <div class="nav">
      <a class="btn secondary" href="/admin?key={key_q}">📦 المنتجات</a>
      <a class="btn secondary" href="/admin/orders?key={key_q}">🧾 الطلبات</a>
      <a class="btn secondary" href="/admin/upload?key={key_q}">⬆️ رفع ملف</a>
      <a class="btn secondary" href="/admin/bulk?key={key_q}">➕ إدخال بالجملة</a>
      <a class="btn secondary" href="/admin/settings?key={key_q}">⚙️ الإعدادات</a>
      <a class="btn secondary" href="/health">🟢 Health</a>
    </div>
    """

@app.get("/")
def home() -> dict:
    return {"status": "PriceBot WhatsApp bot is running", "version": "3.0.0", "business": business_name()}


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "version": "3.0.0",
        "business": business_name(),
        "city": business_city(),
        "hours": business_hours(),
        "delivery": delivery_text(),
        "products_count": len(load_products()),
        "orders_count": len(read_orders()),
        "phone_number_id_set": bool(get_phone_number_id()),
        "access_token_set": bool(get_access_token()),
        "ai_enabled": ai_enabled(),
        "ai_provider_order": ai_provider_order(),
        "ai_status": ai_status_text(),
        "ai_model": ai_model() or ai_default_model(),
        "admin_notify_phone_set": bool(admin_notify_phone()),
    }


@app.get("/products")
def products_api() -> dict:
    return {"products": load_products()}



def update_env_values(values: Dict[str, str]) -> None:
    """Update .env atomically while preserving unrelated secrets/settings."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    seen = set()
    out = []
    for line in lines:
        if line.strip() and not line.strip().startswith("#") and "=" in line:
            key, _ = line.split("=", 1)
            key = key.strip()
            if key in values:
                out.append(f"{key}={values[key]}")
                seen.add(key)
            else:
                out.append(line)
        else:
            out.append(line)
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
    tmp = ENV_FILE.with_suffix(".env.tmp")
    tmp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    tmp.replace(ENV_FILE)



@app.get("/admin/settings")
def admin_settings(key: str = "", msg: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    enabled_checked = "checked" if ai_enabled() else ""
    order_value = ",".join(ai_provider_order())
    admin_phone_value = admin_notify_phone()
    body = f"""
    <div class="hero"><h1>إعدادات {e(business_name())}</h1><p>بيانات الصيدلية، رقم تنبيهات الأدمن، والذكاء الاصطناعي.</p></div>
    {admin_nav(key)}
    <div class="box">
      <p class="msg">{e(msg)}</p>
      <form method="post" action="/admin/settings/save?key={urllib.parse.quote(key)}">
        <h2>بيانات الصيدلية</h2>
        <div class="form-grid">
          <div class="field"><label>اسم الصيدلية</label><input name="PHARMACY_NAME" value="{e(business_name())}"></div>
          <div class="field"><label>المدينة</label><input name="PHARMACY_CITY" value="{e(business_city())}"></div>
          <div class="field"><label>ساعات العمل</label><input name="PHARMACY_HOURS" value="{e(business_hours())}"></div>
          <div class="field"><label>نص التوصيل</label><input name="DELIVERY_TEXT" value="{e(delivery_text())}"></div>
          <div class="field"><label>رقم أدمن واتساب للتنبيهات</label><input name="ADMIN_NOTIFY_PHONE" value="{e(admin_phone_value)}" placeholder="2189XXXXXXXX"></div>
          <div class="field"><label>رابط الموقع العام</label><input name="PUBLIC_BASE_URL" value="{e(public_base_url())}" placeholder="https://46.101.148.246.sslip.io"></div>
        </div>
        <p><label><input type="checkbox" name="DELIVERY_AVAILABLE" value="yes" {'checked' if delivery_enabled() else ''}> التوصيل متوفر</label></p>
        <div class="admin-hint">رقم الأدمن يستقبل تنبيه واتساب عند تأكيد طلب أو وصول صورة/روشتة تحتاج مراجعة. لا تضع رقم الزبون هنا إلا إذا كنت تختبر فقط.</div>

        <h2>الذكاء الاصطناعي المجاني/الاحتياطي</h2>
        <p class="notice">الحالة الحالية: <b>{e(ai_status_text())}</b></p>
        <p><label><input type="checkbox" name="AI_ENABLED" value="yes" {enabled_checked}> تفعيل AI API</label></p>
        <div class="form-grid">
          <div class="field"><label>ترتيب المحاولة</label><input name="AI_PROVIDER_ORDER" value="{e(order_value)}" placeholder="gemini,openrouter,groq"></div>
          <div class="field"><label>OpenRouter model</label><input name="AI_OPENROUTER_MODEL" value="{e(ai_model_for('openrouter'))}" placeholder="openrouter/free"></div>
          <div class="field"><label>Gemini model</label><input name="AI_GEMINI_MODEL" value="{e(ai_model_for('gemini'))}" placeholder="gemini-2.5-flash-lite"></div>
          <div class="field"><label>Groq model</label><input name="AI_GROQ_MODEL" value="{e(ai_model_for('groq'))}" placeholder="llama-3.1-8b-instant"></div>
        </div>
        <p class="notice">الصق المفاتيح الجديدة فقط إذا تريد تغييرها. اترك الخانة فارغة للحفاظ على المفاتيح المحفوظة. يمكن وضع أكثر من مفتاح، كل مفتاح في سطر.</p>
        <div class="form-grid">
          <div class="field"><label>Gemini keys جديدة — المحفوظ: {e(masked_count_for('gemini'))}</label><textarea name="AI_GEMINI_KEYS_NEW" placeholder="AIza..."></textarea></div>
          <div class="field"><label>OpenRouter keys جديدة — المحفوظ: {e(masked_count_for('openrouter'))}</label><textarea name="AI_OPENROUTER_KEYS_NEW" placeholder="sk-or-v1-..."></textarea></div>
          <div class="field"><label>Groq keys جديدة — المحفوظ: {e(masked_count_for('groq'))}</label><textarea name="AI_GROQ_KEYS_NEW" placeholder="gsk_..."></textarea></div>
          <div class="field"><label>OpenAI keys جديدة — المحفوظ: {e(masked_count_for('openai'))}</label><textarea name="AI_OPENAI_KEYS_NEW" placeholder="اختياري - اتركه فارغاً"></textarea></div>
        </div>
        <div class="actions"><button type="submit">حفظ الإعدادات</button><a class="btn secondary" href="/admin/settings/test?key={urllib.parse.quote(key)}&q=كم سعر البروفين؟">اختبار AI</a></div>
      </form>
    </div>
    """
    return HTMLResponse(page_layout("إعدادات PriceBot", body))

@app.post("/admin/settings/save")
async def admin_settings_save(request: Request, key: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    form = await request.form()
    values = {
        "PHARMACY_NAME": str(form.get("PHARMACY_NAME", business_name())).strip() or business_name(),
        "PHARMACY_CITY": str(form.get("PHARMACY_CITY", business_city())).strip() or business_city(),
        "PHARMACY_HOURS": str(form.get("PHARMACY_HOURS", business_hours())).strip() or business_hours(),
        "DELIVERY_AVAILABLE": "yes" if form.get("DELIVERY_AVAILABLE") == "yes" else "no",
        "DELIVERY_TEXT": str(form.get("DELIVERY_TEXT", delivery_text())).strip() or delivery_text(),
        "ADMIN_NOTIFY_PHONE": normalize_phone(str(form.get("ADMIN_NOTIFY_PHONE", admin_notify_phone())).strip()),
        "PUBLIC_BASE_URL": str(form.get("PUBLIC_BASE_URL", public_base_url())).strip().rstrip("/") or public_base_url(),
        "AI_ENABLED": "yes" if form.get("AI_ENABLED") == "yes" else "no",
        "AI_PROVIDER_ORDER": str(form.get("AI_PROVIDER_ORDER", ",".join(ai_provider_order()))).strip() or "gemini,openrouter,groq",
        "AI_OPENROUTER_MODEL": str(form.get("AI_OPENROUTER_MODEL", ai_model_for("openrouter"))).strip() or ai_default_model_for("openrouter"),
        "AI_GEMINI_MODEL": str(form.get("AI_GEMINI_MODEL", ai_model_for("gemini"))).strip() or ai_default_model_for("gemini"),
        "AI_GROQ_MODEL": str(form.get("AI_GROQ_MODEL", ai_model_for("groq"))).strip() or ai_default_model_for("groq"),
        "AI_OPENAI_MODEL": str(form.get("AI_OPENAI_MODEL", ai_model_for("openai"))).strip() or ai_default_model_for("openai"),
        "AI_CUSTOM_BASE_URL": str(form.get("AI_CUSTOM_BASE_URL", get_config("AI_CUSTOM_BASE_URL", ""))).strip(),
    }
    key_fields = {
        "AI_OPENROUTER_KEYS_NEW": "AI_OPENROUTER_KEYS",
        "AI_GEMINI_KEYS_NEW": "AI_GEMINI_KEYS",
        "AI_GROQ_KEYS_NEW": "AI_GROQ_KEYS",
        "AI_OPENAI_KEYS_NEW": "AI_OPENAI_KEYS",
    }
    for form_name, env_name in key_fields.items():
        raw_keys = str(form.get(form_name, "")).strip()
        if raw_keys:
            values[env_name] = join_secret_list(raw_keys)
    update_env_values(values)
    # Refresh current process environment for immediate use without restart.
    for k, v in values.items():
        os.environ[k] = v
    return safe_redirect(f"/admin/settings?key={urllib.parse.quote(key)}&msg={urllib.parse.quote('تم حفظ الإعدادات')}")


@app.get("/admin/settings/test")
def admin_settings_test(key: str = "", q: str = "كم سعر البروفين؟"):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    local_reply = build_reply(q, "")
    ai_data = call_ai_json(q) if ai_enabled() else {"note": "AI غير مفعل أو لا يوجد مفتاح"}
    body = f"""
    <h1>اختبار الذكاء الاصطناعي</h1>
    {admin_nav(key)}
    <div class="box">
      <form method="get" action="/admin/settings/test">
        <input type="hidden" name="key" value="{e(key)}">
        <div class="field"><label>رسالة اختبار</label><input name="q" value="{e(q)}"></div>
        <div class="actions"><button type="submit">اختبار</button></div>
      </form>
    </div>
    <div class="box"><h2>رد البوت</h2><pre style="white-space:pre-wrap; direction:rtl; font-size:16px">{e(local_reply)}</pre></div>
    <div class="box"><h2>نتيجة AI JSON</h2><pre style="white-space:pre-wrap; direction:ltr; text-align:left">{e(json.dumps(ai_data, ensure_ascii=False, indent=2))}</pre></div>
    """
    return HTMLResponse(page_layout("اختبار AI", body))


@app.get("/admin")
def admin(key: str = "", msg: str = "", q: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)

    query = normalize(q)
    all_products = load_products()
    orders = read_orders()
    new_orders = [o for o in orders if (o.get("status") or "new") != "done"]
    products = all_products
    if query:
        products = [
            item for item in all_products
            if query in normalize(" ".join([item.get("name", ""), item.get("aliases", ""), item.get("notes", "")]))
        ]

    cards = ""
    for idx, item in enumerate(products):
        real_index = all_products.index(item) if item in all_products else idx
        cards += f"""
        <div class="card">
          <div class="product-title">{e(item.get('name'))}</div>
          <div class="product-meta">💰 <b>{e(item.get('price'))}</b> &nbsp; | &nbsp; 📦 <b>{e(item.get('available'))}</b> &nbsp; | &nbsp; 📝 {e(item.get('notes'))}</div>
          <form class="card-form" method="get" action="/admin/update">
            <input type="hidden" name="key" value="{e(key)}">
            <input type="hidden" name="idx" value="{real_index}">
            <div class="form-grid">
              <div class="field"><label>اسم المنتج</label><input name="name" value="{e(item.get('name'))}" required></div>
              <div class="field"><label>أسماء بديلة</label><input name="aliases" value="{e(item.get('aliases'))}" placeholder="بندول, panadol"></div>
              <div class="field"><label>السعر</label><input name="price" value="{e(item.get('price'))}"></div>
              <div class="field"><label>التوفر</label><input name="available" value="{e(item.get('available'))}"></div>
              <div class="field"><label>ملاحظات</label><input name="notes" value="{e(item.get('notes'))}"></div>
            </div>
            <div class="actions"><button type="submit">حفظ</button><a class="btn danger" href="/admin/delete?key={urllib.parse.quote(key)}&idx={real_index}" onclick="return confirm('حذف المنتج؟')">حذف</a></div>
          </form>
        </div>
        """
    if not cards:
        cards = '<div class="box notice">لا توجد منتجات مطابقة. أضف منتجًا أو ارفع ملف Excel/CSV.</div>'

    body = f"""
    <div class="hero"><h1>لوحة إدارة {e(business_name())}</h1><p>إدارة المنتجات، الطلبات، الصور، والردود الآلية.</p></div>
    {admin_nav(key)}
    <div class="stats">
      <div class="stat"><b>{len(all_products)}</b><span>منتج</span></div>
      <div class="stat"><b>{len(new_orders)}</b><span>طلبات جديدة</span></div>
      <div class="stat"><b>{'نعم' if ai_enabled() else 'لا'}</b><span>AI مفعل</span></div>
      <div class="stat"><b>{'نعم' if admin_notify_phone() else 'لا'}</b><span>تنبيه الأدمن</span></div>
    </div>
    <div class="box">
      <p class="msg">{e(msg)}</p>
      <form method="get" action="/admin">
        <input type="hidden" name="key" value="{e(key)}">
        <div class="field"><label>بحث سريع</label><input name="q" value="{e(q)}" placeholder="ابحث باسم المنتج أو الاسم البديل"></div>
        <div class="actions"><button type="submit">بحث</button><a class="btn secondary" href="/admin?key={urllib.parse.quote(key)}">إظهار الكل</a><a class="btn ok" href="/admin/orders?key={urllib.parse.quote(key)}&status=new">الطلبات الجديدة</a></div>
      </form>
    </div>
    <div class="box">
      <h2>إضافة منتج جديد</h2>
      <form method="get" action="/admin/add">
        <input type="hidden" name="key" value="{e(key)}">
        <div class="form-grid">
          <div class="field"><label>اسم المنتج</label><input name="name" placeholder="بنادول" required></div>
          <div class="field"><label>أسماء بديلة</label><input name="aliases" placeholder="بندول, panadol"></div>
          <div class="field"><label>السعر</label><input name="price" placeholder="5 د.ل"></div>
          <div class="field"><label>التوفر</label><input name="available" value="متوفر"></div>
          <div class="field"><label>ملاحظات</label><input name="notes" placeholder="شريط / 500mg"></div>
        </div>
        <div class="actions"><button type="submit">إضافة المنتج</button></div>
      </form>
    </div>
    <h2>المنتجات الحالية ({len(products)})</h2>
    <div class="product-grid">{cards}</div>
    """
    return HTMLResponse(page_layout("لوحة PriceBot", body))

@app.get("/admin/add")
def admin_add(key: str = "", name: str = "", aliases: str = "", price: str = "", available: str = "متوفر", notes: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    if name.strip():
        upsert_product({"name": name.strip(), "aliases": aliases.strip(), "price": price.strip(), "available": available.strip() or "متوفر", "notes": notes.strip()})
        return safe_redirect(f"/admin?key={urllib.parse.quote(key)}&msg={urllib.parse.quote('تمت الإضافة أو التحديث')}")
    return safe_redirect(f"/admin?key={urllib.parse.quote(key)}&msg={urllib.parse.quote('لم يتم إدخال اسم المنتج')}")


@app.get("/admin/update")
def admin_update(key: str = "", idx: int = -1, name: str = "", aliases: str = "", price: str = "", available: str = "", notes: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    products = load_products()
    if 0 <= idx < len(products) and name.strip():
        products[idx] = {"name": name.strip(), "aliases": aliases.strip(), "price": price.strip(), "available": available.strip() or "متوفر", "notes": notes.strip()}
        save_products(products)
        msg = "تم الحفظ"
    else:
        msg = "لم يتم العثور على المنتج"
    return safe_redirect(f"/admin?key={urllib.parse.quote(key)}&msg={urllib.parse.quote(msg)}")


@app.get("/admin/delete")
def admin_delete(key: str = "", idx: int = -1, name: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    products = load_products()
    if 0 <= idx < len(products):
        products.pop(idx)
        save_products(products)
        msg = "تم الحذف"
    elif name:
        before = len(products)
        products = [p for p in products if p.get("name") != name]
        save_products(products)
        msg = "تم الحذف" if len(products) < before else "لم يتم العثور على المنتج"
    else:
        msg = "لم يتم تحديد المنتج"
    return safe_redirect(f"/admin?key={urllib.parse.quote(key)}&msg={urllib.parse.quote(msg)}")


@app.get("/admin/bulk")
def admin_bulk(key: str = "", msg: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    sample = "بنادول,بندول|panadol,5 د.ل,متوفر,شريط\nبروفين,brufen|ibuprofen,8,متوفر,400mg"
    body = f"""
    <h1>إدخال منتجات بالجملة</h1>
    {admin_nav(key)}
    <div class="box">
      <p class="msg">{e(msg)}</p>
      <p class="notice">كل سطر بهذا الترتيب: الاسم, الأسماء البديلة, السعر, التوفر, ملاحظات. يمكن فصل الأسماء البديلة بفاصلة أو علامة |.</p>
      <form method="post" action="/admin/bulk/save?key={urllib.parse.quote(key)}">
        <textarea name="data" placeholder="{e(sample)}"></textarea>
        <p><label><input type="checkbox" name="replace" value="1"> استبدال كل المنتجات الحالية</label></p>
        <button type="submit">استيراد المنتجات</button>
      </form>
    </div>
    """
    return HTMLResponse(page_layout("إدخال منتجات بالجملة", body))


@app.post("/admin/bulk/save")
async def admin_bulk_save(request: Request, key: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    form = await request.form()
    raw_data = str(form.get("data", ""))
    replace = form.get("replace") == "1"
    imported = parse_rows_from_text(raw_data)
    products = [] if replace else load_products()
    products.extend(imported)
    save_products(products)
    return safe_redirect(f"/admin/bulk?key={urllib.parse.quote(key)}&msg={urllib.parse.quote('تم استيراد ' + str(len(imported)) + ' منتج')}")


def parse_rows_from_text(raw_data: str) -> List[dict]:
    if not raw_data:
        return []
    rows: List[List[str]] = []
    if "\t" in raw_data:
        for line in raw_data.splitlines():
            rows.append([x.strip() for x in line.split("\t")])
    else:
        rows = [[x.strip() for x in row] for row in csv.reader(io.StringIO(raw_data)) if row]
    return rows_to_products(rows)


def header_map(headers: List[str]) -> Dict[str, int]:
    normalized = [normalize(h) for h in headers]
    variants = {
        "name": ["name", "product", "product name", "اسم", "الاسم", "اسم المنتج"],
        "aliases": ["aliases", "alias", "اسماء بديله", "اسامي بديله", "بدائل"],
        "price": ["price", "سعر", "السعر"],
        "available": ["available", "availability", "stock", "توفر", "التوفر", "الحاله", "متوفر"],
        "notes": ["notes", "note", "ملاحظات", "ملاحظه", "تركيز"],
    }
    mapping: Dict[str, int] = {}
    for field, names in variants.items():
        normalized_names = [normalize(name) for name in names]
        for idx, h in enumerate(normalized):
            if h in normalized_names:
                mapping[field] = idx
                break
    return mapping


def rows_to_products(rows: List[List[str]]) -> List[dict]:
    if not rows:
        return []
    mapping = header_map(rows[0])
    start = 1 if "name" in mapping else 0
    imported = []
    for row in rows[start:]:
        if not row or not any(str(x).strip() for x in row):
            continue
        while len(row) < 5:
            row.append("")
        if mapping:
            name = row[mapping.get("name", 0)].strip() if mapping.get("name", 0) < len(row) else ""
            aliases = row[mapping.get("aliases", 1)].strip() if mapping.get("aliases", 1) < len(row) else ""
            price = row[mapping.get("price", 2)].strip() if mapping.get("price", 2) < len(row) else ""
            available = row[mapping.get("available", 3)].strip() if mapping.get("available", 3) < len(row) else ""
            notes = row[mapping.get("notes", 4)].strip() if mapping.get("notes", 4) < len(row) else ""
        else:
            name, aliases, price, available, notes = [x.strip() for x in row[:5]]
        if not name or normalize(name) in ["name", "اسم", "الاسم", "اسم المنتج"]:
            continue
        imported.append({"name": name, "aliases": aliases, "price": price, "available": available or "متوفر", "notes": notes})
    return imported


@app.get("/admin/upload")
def admin_upload_page(key: str = "", msg: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    body = f"""
    <h1>رفع ملف منتجات {e(business_name())}</h1>
    {admin_nav(key)}
    <div class="box">
      <p class="msg">{e(msg)}</p>
      <p class="notice">يقبل CSV أو Excel xlsx. الأعمدة المفضلة: name, aliases, price, available, notes. يدعم أيضًا عناوين عربية مثل: الاسم، السعر، التوفر، ملاحظات.</p>
      <p><a class="btn secondary" href="/admin/template.csv?key={urllib.parse.quote(key)}">تحميل قالب CSV</a></p>
      <form method="post" action="/admin/upload/save?key={urllib.parse.quote(key)}" enctype="multipart/form-data">
        <div class="field"><label>اختر الملف</label><input type="file" name="file" accept=".csv,.xlsx,.txt" required></div>
        <p><label><input type="checkbox" name="replace" value="1"> استبدال كل المنتجات الحالية</label></p>
        <button type="submit">رفع واستيراد</button>
      </form>
    </div>
    """
    return HTMLResponse(page_layout("رفع ملف المنتجات", body))


@app.get("/admin/template.csv")
def admin_template_csv(key: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    content = "\ufeffname,aliases,price,available,notes\nبنادول,بندول|panadol,5 د.ل,متوفر,شريط\nبروفين,brufen|ibuprofen,8,متوفر,400mg\n"
    return PlainTextResponse(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=pricebot_products_template.csv"},
    )


@app.post("/admin/upload/save")
async def admin_upload_save(request: Request, file: UploadFile = File(...), key: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    form = await request.form()
    replace = form.get("replace") == "1"
    content = await file.read()
    filename = (file.filename or "").lower()
    rows: List[List[str]] = []

    if filename.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            values = ["" if v is None else str(v).strip() for v in row]
            if any(values):
                rows.append(values)
    else:
        text = content.decode("utf-8-sig", errors="ignore")
        rows = [[x.strip() for x in row] for row in csv.reader(io.StringIO(text)) if row]

    imported = rows_to_products(rows)
    products = [] if replace else load_products()
    products.extend(imported)
    save_products(products)
    return safe_redirect(f"/admin/upload?key={urllib.parse.quote(key)}&msg={urllib.parse.quote('تم استيراد ' + str(len(imported)) + ' منتج من الملف')}")



@app.get("/admin/orders")
def admin_orders(key: str = "", msg: str = "", status: str = "all", q: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    orders = read_orders()
    total = len(orders)
    new_count = len([o for o in orders if (o.get("status") or "new") != "done"])
    done_count = total - new_count
    query = normalize(q)
    filtered: List[Tuple[int, dict]] = []
    for idx, row in enumerate(orders):
        row_status = row.get("status", "new") or "new"
        if status == "new" and row_status == "done":
            continue
        if status == "done" and row_status != "done":
            continue
        if query and query not in normalize(" ".join([row.get('phone',''), row.get('product',''), row.get('notes',''), row.get('message','')])):
            continue
        filtered.append((idx, row))
    filtered = list(reversed(filtered))

    cards = ""
    for idx, row in filtered:
        row_status = row.get("status", "new") or "new"
        status_ar = "تم التنفيذ" if row_status == "done" else "جديد"
        badge_class = "done" if row_status == "done" else "new"
        phone = row.get("phone", "")
        phone_link = f"https://wa.me/{urllib.parse.quote(phone)}" if phone else "#"
        done_button = f'<a class="btn ok" href="/admin/orders/done?key={urllib.parse.quote(key)}&idx={idx}">تم التنفيذ</a>' if row_status != "done" else '<span class="btn secondary">منتهي</span>'
        msg_text = row.get('message','')
        image_link = ''
        m = re.search(r"https?://\S+", msg_text or "")
        if m:
            image_link = f'<a class="btn secondary" target="_blank" href="{e(m.group(0))}">فتح الصورة</a>'
        cards += f"""
        <div class="card order-card">
          <div class="order-head"><div class="order-title">{e(row.get('product'))}</div><span class="badge {badge_class}">{status_ar}</span></div>
          <div class="order-row"><strong>الوقت</strong><span>{e(row.get('time'))}</span></div>
          <div class="order-row"><strong>رقم الزبون</strong><a href="{phone_link}" target="_blank">{e(phone)}</a></div>
          <div class="order-row"><strong>السعر</strong><span>{e(row.get('price') or '-')}</span></div>
          <div class="order-row"><strong>التوفر</strong><span>{e(row.get('available') or '-')}</span></div>
          <div class="order-row"><strong>ملاحظة</strong><span>{e(row.get('notes') or '-')}</span></div>
          <div class="order-row"><strong>رسالة</strong><span>{e((msg_text or '-')[:180])}</span></div>
          <div class="actions">{done_button}<a class="btn secondary" target="_blank" href="{phone_link}">مراسلة الزبون</a>{image_link}<a class="btn danger" href="/admin/orders/delete?key={urllib.parse.quote(key)}&idx={idx}" onclick="return confirm('حذف الطلب؟')">حذف</a></div>
        </div>
        """
    if not cards:
        cards = '<div class="box notice">لا توجد طلبات في هذا القسم.</div>'

    body = f"""
    <div class="hero"><h1>طلبات الحجز</h1><p>{e(business_name())} — متابعة الطلبات والصور والروشتات.</p></div>
    {admin_nav(key)}
    <div class="stats">
      <div class="stat"><b>{total}</b><span>كل الطلبات</span></div>
      <div class="stat"><b>{new_count}</b><span>جديدة</span></div>
      <div class="stat"><b>{done_count}</b><span>منفذة</span></div>
      <div class="stat"><b>{len(filtered)}</b><span>المعروضة</span></div>
    </div>
    <div class="box">
      <p class="msg">{e(msg)}</p>
      <form method="get" action="/admin/orders">
        <input type="hidden" name="key" value="{e(key)}">
        <div class="form-grid"><div class="field"><label>بحث في الطلبات</label><input name="q" value="{e(q)}" placeholder="رقم زبون / منتج / ملاحظة"></div><div class="field"><label>الحالة</label><select name="status"><option value="all" {'selected' if status=='all' else ''}>كل الطلبات</option><option value="new" {'selected' if status=='new' else ''}>الجديدة</option><option value="done" {'selected' if status=='done' else ''}>المنفذة</option></select></div></div>
        <div class="actions"><button type="submit">تطبيق</button><a class="btn secondary" href="/admin/orders?key={urllib.parse.quote(key)}&status=new">الجديدة</a><a class="btn secondary" href="/admin/orders?key={urllib.parse.quote(key)}&status=done">المنفذة</a><a class="btn secondary" href="/admin/orders/export?key={urllib.parse.quote(key)}">تصدير CSV</a></div>
      </form>
    </div>
    <div class="product-grid">{cards}</div>
    """
    return HTMLResponse(page_layout("طلبات PriceBot", body))

@app.get("/admin/orders/done")
def admin_orders_done(key: str = "", idx: int = -1):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    orders = read_orders()
    if 0 <= idx < len(orders):
        orders[idx]["status"] = "done"
        write_orders(orders)
        msg = "تم تحديث الطلب"
    else:
        msg = "لم يتم العثور على الطلب"
    return safe_redirect(f"/admin/orders?key={urllib.parse.quote(key)}&msg={urllib.parse.quote(msg)}")


@app.get("/admin/orders/delete")
def admin_orders_delete(key: str = "", idx: int = -1):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    orders = read_orders()
    if 0 <= idx < len(orders):
        orders.pop(idx)
        write_orders(orders)
        msg = "تم حذف الطلب"
    else:
        msg = "لم يتم العثور على الطلب"
    return safe_redirect(f"/admin/orders?key={urllib.parse.quote(key)}&msg={urllib.parse.quote(msg)}")


@app.get("/admin/orders/export")
def admin_orders_export(key: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=ORDER_FIELDS)
    writer.writeheader()
    for row in read_orders():
        writer.writerow({field: row.get(field, "") for field in ORDER_FIELDS})
    return PlainTextResponse(
        "\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=pricebot_orders.csv"},
    )



@app.get("/admin/media/{filename}")
def admin_media(filename: str, key: str = ""):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    safe_name = Path(filename).name
    path = MEDIA_DIR / safe_name
    if not path.exists() or not path.is_file():
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(path)

@app.get("/privacy")
def privacy_policy():
    return PlainTextResponse(
        """
PriceBot Privacy Policy

PriceBot receives WhatsApp messages only to respond to customer product and price inquiries.
We do not sell user data.
We do not share customer messages with advertisers.
Messages may be processed to provide automated replies about product availability and prices.
Users can request deletion of their data by contacting the business owner.

Data deletion URL:
/delete-data
""".strip()
    )


@app.get("/delete-data")
def delete_data():
    return PlainTextResponse(
        """
Data Deletion Instructions

To request deletion of your WhatsApp messages or customer data, contact the business owner and provide your WhatsApp number.
The business owner will delete your related records from the system when applicable.
""".strip()
    )


@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)



@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if "statuses" in value and "messages" not in value:
                    return JSONResponse({"status": "status_event_ignored"})
                for msg in value.get("messages", []):
                    from_number = msg.get("from")
                    if not from_number:
                        continue
                    msg_type = msg.get("type")
                    if msg_type == "text":
                        text_msg = msg.get("text", {}).get("body", "")
                        reply = build_reply(text_msg, from_number)
                    elif msg_type == "image":
                        reply = process_image_message(msg, from_number)
                    elif msg_type in {"document", "audio", "video"}:
                        save_review_order(from_number, f"ملف {msg_type} يحتاج مراجعة", f"وصل ملف من نوع {msg_type}", "")
                        notify_admin(
                            f"📎 ملف يحتاج مراجعة - {pharmacy_name()}\n\nرقم الزبون: {from_number}\nنوع الملف: {msg_type}\nالوقت: {now_str()}",
                            from_number,
                        )
                        reply = build_image_under_review_reply()
                    else:
                        reply = (
                            f"{pharmacy_name()} 🌿\n\n"
                            "أستطيع الرد على أسماء المنتجات المكتوبة أو صور المنتجات.\n"
                            "للروشتات أو الصور غير الواضحة سيتم تحويلها للصيدلي."
                        )
                    send_whatsapp_message(from_number, reply)
    except Exception as exc:
        print("WEBHOOK PROCESS ERROR:", str(exc), flush=True)
    return JSONResponse({"status": "received"})

@app.get("/test")
def test_reply(q: str = ""):
    return {"reply": build_reply(q)}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8095"))
    uvicorn.run(app, host="0.0.0.0", port=port)
