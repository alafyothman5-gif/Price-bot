from __future__ import annotations

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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
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

app = FastAPI(title="PriceBot", version="2.3.0")
LAST_PRODUCT: Dict[str, dict] = {}


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
    raw = get_config("AI_PROVIDER_ORDER", "openrouter,gemini,groq,openai")
    supported = {"openrouter", "gemini", "groq", "openai", "custom"}
    out: List[str] = []
    for item in re.split(r"[,;|\n]+", raw):
        name = item.strip().lower()
        if name in supported and name not in out:
            out.append(name)
    return out or ["openrouter", "gemini", "groq", "openai"]


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
        return "gemini-1.5-flash"
    if provider == "groq":
        return "llama-3.1-8b-instant"
    if provider == "openai":
        return "gpt-4o-mini"
    return "openai/gpt-4o-mini"


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


def asks_medical_advice(text: str) -> bool:
    q = normalize(text)
    medical_words = [
        "جرعه", "جرعات", "كم حبه", "كم مره", "استعمل", "استخدم", "ينفع", "عادي", "حامل", "حمل",
        "طفل", "رضيع", "سكر", "ضغط", "حساسيه", "اعراض", "تشخيص", "علاج ل", "وجع", "الم شديد",
    ]
    return any(normalize(w) in q for w in medical_words)


def build_welcome_reply() -> str:
    return (
        f"أهلاً وسهلاً بك في {business_name()}\n"
        f"المدينة: {business_city()}\n"
        f"ساعات العمل: {business_hours()}\n"
        f"{delivery_text()}\n\n"
        "اكتب اسم الدواء أو المنتج، وسأخبرك بالسعر والتوفر.\n"
        "مثال: بنادول، بروفين، أوجمنتين.\n\n"
        "للحجز بعد ظهور المنتج، اكتب: نعم"
    )


def build_product_reply(item: dict, original_text: str = "") -> str:
    lines = [
        f"{business_name()}",
        "",
        f"المنتج: {item.get('name', '')}",
        f"الحالة: {item.get('available') or 'متوفر'}",
    ]
    if item.get("price"):
        lines.append(f"السعر: {item.get('price')}")
    if item.get("notes"):
        lines.append(f"ملاحظة: {item.get('notes')}")
    if asks_medical_advice(original_text):
        lines.append("")
        lines.append("تنبيه: للاستعمال أو الجرعة، يرجى مراجعة الصيدلي.")
    lines.append("")
    lines.append("هل تريد حجزه؟ اكتب: نعم")
    return "\n".join(lines)


def build_suggestions_reply(items: List[dict]) -> str:
    lines = [
        f"{business_name()}",
        "لم أجد المنتج بالضبط، لكن ربما تقصد أحد هذه المنتجات:",
        "",
    ]
    for idx, item in enumerate(items, 1):
        price = f" - السعر: {item.get('price')}" if item.get("price") else ""
        lines.append(f"{idx}. {item.get('name', '')}{price}")
    lines.append("")
    lines.append("اكتب اسم المنتج كما هو ظاهر للحجز أو الاستعلام.")
    return "\n".join(lines)


def build_not_found_reply(text: str) -> str:
    if asks_medical_advice(text):
        return (
            f"{business_name()}\n"
            "سؤالك يحتاج مراجعة الصيدلي، ولا أستطيع تحديد علاج أو جرعة من الرسائل.\n\n"
            "للاستعلام عن السعر والتوفر، اكتب اسم الدواء أو المنتج فقط."
        )
    return (
        f"{business_name()}\n"
        "لم أفهم اسم المنتج بدقة.\n"
        "اكتب اسم المنتج فقط، مثل: بنادول أو بروفين."
    )


def build_reply(text: str, from_number: str = "") -> str:
    raw_text = text or ""
    query = normalize(raw_text)

    yes_words = [normalize(x) for x in ["نعم", "اي", "تمام", "حجز", "احجز", "اريد", "نبي", "yes", "ok", "اوكي"]]
    no_words = [normalize(x) for x in ["لا", "الغاء", "إلغاء", "cancel", "no"]]

    if from_number and from_number in LAST_PRODUCT and any(w in query for w in no_words):
        LAST_PRODUCT.pop(from_number, None)
        return "تم إلغاء الحجز المؤقت. اكتب اسم منتج آخر للبحث."

    if from_number and from_number in LAST_PRODUCT and any(w in query for w in yes_words):
        item = LAST_PRODUCT[from_number]
        save_order(from_number, item, raw_text)
        LAST_PRODUCT.pop(from_number, None)
        return (
            f"تم تسجيل طلب حجز {item.get('name', '')}\n"
            f"السعر: {item.get('price', '')}\n\n"
            "سيتواصل معك الموظف لتأكيد الطلب."
        )

    # Fast local path: no API cost when the product is already clear.
    item = find_product(raw_text)
    if item:
        if from_number:
            LAST_PRODUCT[from_number] = item
        return build_product_reply(item, raw_text)

    if is_greeting(raw_text):
        return build_welcome_reply()

    # Real AI path: used only after local matching fails, so cost stays low.
    ai_data = call_ai_json(raw_text) if ai_enabled() else {}
    intent = str(ai_data.get("intent", "")).strip().lower() if ai_data else ""

    if intent == "greeting":
        return build_welcome_reply()

    ai_item = product_by_ai_names(ai_data) if ai_data else None
    if ai_item:
        if from_number:
            LAST_PRODUCT[from_number] = ai_item
        return build_product_reply(ai_item, raw_text)

    if intent == "medical_advice":
        ai_suggestions = suggestions_from_ai(ai_data, raw_text) if ai_data else []
        if ai_suggestions:
            return build_suggestions_reply(ai_suggestions) + "\n\nتنبيه: للاستعمال أو الجرعة، يرجى مراجعة الصيدلي."
        return (
            f"{business_name()}\n"
            "سؤالك يحتاج مراجعة الصيدلي، ولا أستطيع تحديد علاج أو جرعة من الرسائل.\n\n"
            "للاستعلام عن السعر والتوفر، اكتب اسم الدواء أو المنتج فقط."
        )

    if ai_data:
        ai_suggestions = suggestions_from_ai(ai_data, raw_text)
        if ai_suggestions:
            return build_suggestions_reply(ai_suggestions)

    suggestions = suggested_products(raw_text)
    if suggestions:
        return build_suggestions_reply(suggestions)

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

    if ADMIN_NOTIFY_PHONE:
        admin_msg = (
            "✅ طلب جديد من PriceBot\n\n"
            f"رقم الزبون: {phone}\n"
            f"المنتج: {item.get('name', '')}\n"
            f"السعر: {item.get('price', '')}\n"
            f"ملاحظة: {item.get('notes', '')}\n\n"
            "افتح لوحة الطلبات لمتابعته."
        )
        send_whatsapp_message(ADMIN_NOTIFY_PHONE, admin_msg)


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
:root { --bg:#f4f6f8; --card:#ffffff; --text:#202124; --muted:#687076; --line:#e3e6ea; --brand:#0f766e; --danger:#b42318; --ok:#15803d; --shadow:0 2px 14px rgba(16,24,40,.08); }
*{ box-sizing:border-box; }
body{ margin:0; padding:16px; background:var(--bg); color:var(--text); font-family:Arial,Tahoma,sans-serif; direction:rtl; }
a{ color:var(--brand); text-decoration:none; }
h1{ text-align:center; margin:12px 0 18px; font-size:28px; }
h2{ margin:8px 0 14px; font-size:22px; }
.container{ max-width:1050px; margin:0 auto; }
.box,.card{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; margin:12px 0; box-shadow:var(--shadow); }
.nav{ display:flex; flex-wrap:wrap; gap:8px; justify-content:center; margin:10px 0 16px; }
.btn,a.btn,button,input[type=submit]{ display:inline-block; border:0; border-radius:10px; padding:11px 14px; font-size:16px; background:var(--brand); color:#fff; cursor:pointer; text-align:center; }
.btn.secondary,a.btn.secondary{ background:#e8f3f1; color:#0f5f59; border:1px solid #b6dfd8; }
.btn.danger,a.btn.danger{ background:#fff1f0; color:var(--danger); border:1px solid #ffcbc5; }
.btn.ok,a.btn.ok{ background:#ecfdf3; color:var(--ok); border:1px solid #bbf7d0; }
.msg{ color:var(--ok); font-weight:700; text-align:center; }
.notice{ color:var(--muted); font-size:14px; line-height:1.8; }
.form-grid{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.field{ display:flex; flex-direction:column; gap:6px; }
label{ font-weight:700; }
input,textarea,select{ width:100%; border:1px solid #cfd6dd; border-radius:10px; padding:11px; font-size:16px; background:#fff; }
textarea{ min-height:220px; line-height:1.7; }
.product-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; }
.product-title{ font-size:20px; font-weight:800; margin-bottom:8px; }
.product-meta{ color:var(--muted); font-size:14px; margin:4px 0 12px; }
.actions{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:10px; }
.card-form{ display:grid; gap:10px; }
.order-card{ display:grid; gap:8px; }
.order-row{ display:flex; justify-content:space-between; gap:12px; border-bottom:1px dashed var(--line); padding:3px 0; }
.order-row strong{ white-space:nowrap; }
.status-new{ color:#b45309; font-weight:800; }
.status-done{ color:var(--ok); font-weight:800; }
.table-wrap{ overflow-x:auto; }
table{ width:100%; border-collapse:collapse; background:#fff; }
th,td{ border:1px solid var(--line); padding:9px; text-align:center; }
th{ background:#f0f2f4; }
@media(max-width:700px){ body{ padding:10px; } h1{ font-size:24px; } .form-grid{ grid-template-columns:1fr; } .box,.card{ padding:13px; border-radius:14px; } .nav{ justify-content:stretch; } .nav .btn{ flex:1 1 45%; } .product-grid{ grid-template-columns:1fr; } .actions .btn,.actions button{ flex:1 1 auto; } }
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


def admin_nav(key: str) -> str:
    key_q = urllib.parse.quote(key)
    return f"""
    <div class="nav">
      <a class="btn secondary" href="/admin?key={key_q}">المنتجات</a>
      <a class="btn secondary" href="/admin/upload?key={key_q}">رفع Excel/CSV</a>
      <a class="btn secondary" href="/admin/bulk?key={key_q}">إدخال بالجملة</a>
      <a class="btn secondary" href="/admin/orders?key={key_q}">الطلبات</a>
      <a class="btn secondary" href="/admin/settings?key={key_q}">الإعدادات والذكاء</a>
      <a class="btn secondary" href="/health">Health</a>
    </div>
    """


@app.get("/")
def home() -> dict:
    return {"status": "PriceBot WhatsApp bot is running", "version": "2.3.0", "business": business_name()}


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "version": "2.3.0",
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
    body = f"""
    <h1>إعدادات {e(business_name())}</h1>
    {admin_nav(key)}
    <div class="box">
      <p class="msg">{e(msg)}</p>
      <p class="notice">هنا تضبط اسم الصيدلية والذكاء الاصطناعي الحقيقي. لا تظهر مفاتيح API المحفوظة؛ يظهر عدد المفاتيح فقط.</p>
    </div>
    <div class="box">
      <h2>بيانات الصيدلية</h2>
      <form method="post" action="/admin/settings/save?key={urllib.parse.quote(key)}">
        <div class="form-grid">
          <div class="field"><label>اسم الصيدلية</label><input name="PHARMACY_NAME" value="{e(business_name())}"></div>
          <div class="field"><label>المدينة</label><input name="PHARMACY_CITY" value="{e(business_city())}"></div>
          <div class="field"><label>ساعات العمل</label><input name="PHARMACY_HOURS" value="{e(business_hours())}"></div>
          <div class="field"><label>نص التوصيل</label><input name="DELIVERY_TEXT" value="{e(delivery_text())}"></div>
        </div>
        <p><label><input type="checkbox" name="DELIVERY_AVAILABLE" value="yes" {'checked' if delivery_enabled() else ''}> التوصيل متوفر</label></p>

        <h2>الذكاء الاصطناعي الحقيقي API مع مفاتيح احتياطية</h2>
        <p class="notice">الحالة الحالية: <b>{e(ai_status_text())}</b></p>
        <p><label><input type="checkbox" name="AI_ENABLED" value="yes" {enabled_checked}> تفعيل AI API</label></p>
        <div class="form-grid">
          <div class="field"><label>ترتيب المحاولة</label><input name="AI_PROVIDER_ORDER" value="{e(order_value)}" placeholder="openrouter,gemini,groq,openai"></div>
          <div class="field"><label>OpenRouter model</label><input name="AI_OPENROUTER_MODEL" value="{e(ai_model_for('openrouter'))}" placeholder="openai/gpt-4o-mini"></div>
          <div class="field"><label>Gemini model</label><input name="AI_GEMINI_MODEL" value="{e(ai_model_for('gemini'))}" placeholder="gemini-1.5-flash"></div>
          <div class="field"><label>Groq model</label><input name="AI_GROQ_MODEL" value="{e(ai_model_for('groq'))}" placeholder="llama-3.1-8b-instant"></div>
          <div class="field"><label>OpenAI model</label><input name="AI_OPENAI_MODEL" value="{e(ai_model_for('openai'))}" placeholder="gpt-4o-mini"></div>
          <div class="field"><label>Custom API URL اختياري</label><input name="AI_CUSTOM_BASE_URL" value="{e(get_config('AI_CUSTOM_BASE_URL',''))}" placeholder="للمزود custom فقط"></div>
        </div>
        <p class="notice">الصق المفاتيح الجديدة فقط إذا تريد تغييرها. اترك الخانة فارغة للحفاظ على المفاتيح المحفوظة. يمكنك وضع أكثر من مفتاح؛ كل مفتاح في سطر.</p>
        <div class="form-grid">
          <div class="field"><label>OpenRouter keys جديدة — المحفوظ: {e(masked_count_for('openrouter'))}</label><textarea name="AI_OPENROUTER_KEYS_NEW" placeholder="sk-or-v1-...\nsk-or-v1-..."></textarea></div>
          <div class="field"><label>Gemini keys جديدة — المحفوظ: {e(masked_count_for('gemini'))}</label><textarea name="AI_GEMINI_KEYS_NEW" placeholder="AIza...\nAIza..."></textarea></div>
          <div class="field"><label>Groq keys جديدة — المحفوظ: {e(masked_count_for('groq'))}</label><textarea name="AI_GROQ_KEYS_NEW" placeholder="gsk_...\ngsk_..."></textarea></div>
          <div class="field"><label>OpenAI keys جديدة — المحفوظ: {e(masked_count_for('openai'))}</label><textarea name="AI_OPENAI_KEYS_NEW" placeholder="sk-...\nsk-..."></textarea></div>
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
        "AI_ENABLED": "yes" if form.get("AI_ENABLED") == "yes" else "no",
        "AI_PROVIDER_ORDER": str(form.get("AI_PROVIDER_ORDER", ",".join(ai_provider_order()))).strip() or "openrouter,gemini,groq,openai",
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
    products = load_products()
    if query:
        products = [
            item
            for item in products
            if query in normalize(" ".join([item.get("name", ""), item.get("aliases", ""), item.get("notes", "")]))
        ]

    cards = ""
    for idx, item in enumerate(products):
        real_index = load_products().index(item) if item in load_products() else idx
        cards += f"""
        <div class="card">
          <div class="product-title">{e(item.get('name'))}</div>
          <div class="product-meta">السعر: <b>{e(item.get('price'))}</b> | التوفر: <b>{e(item.get('available'))}</b> | ملاحظة: {e(item.get('notes'))}</div>
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
            <div class="actions">
              <button type="submit">حفظ التعديل</button>
              <a class="btn danger" href="/admin/delete?key={urllib.parse.quote(key)}&idx={real_index}" onclick="return confirm('حذف المنتج؟')">حذف</a>
            </div>
          </form>
        </div>
        """

    if not cards:
        cards = '<div class="box notice">لا توجد منتجات مطابقة. أضف منتجًا أو ارفع ملف Excel/CSV.</div>'

    body = f"""
    <h1>لوحة منتجات {e(business_name())}</h1>
    {admin_nav(key)}
    <div class="box">
      <p class="msg">{e(msg)}</p>
      <form method="get" action="/admin">
        <input type="hidden" name="key" value="{e(key)}">
        <div class="field"><label>بحث سريع</label><input name="q" value="{e(q)}" placeholder="ابحث باسم المنتج أو الاسم البديل"></div>
        <div class="actions"><button type="submit">بحث</button><a class="btn secondary" href="/admin?key={urllib.parse.quote(key)}">إظهار الكل</a></div>
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
    return HTMLResponse(page_layout("لوحة منتجات PriceBot", body))


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
def admin_orders(key: str = "", msg: str = "", status: str = "all"):
    if not check_admin(key):
        return PlainTextResponse("Forbidden", status_code=403)
    orders = read_orders()
    filtered: List[Tuple[int, dict]] = []
    for idx, row in enumerate(orders):
        if status == "new" and row.get("status", "new") == "done":
            continue
        if status == "done" and row.get("status", "new") != "done":
            continue
        filtered.append((idx, row))

    cards = ""
    for idx, row in filtered:
        row_status = row.get("status", "new") or "new"
        status_ar = "تم التنفيذ" if row_status == "done" else "جديد"
        status_class = "status-done" if row_status == "done" else "status-new"
        phone = row.get("phone", "")
        phone_link = f"https://wa.me/{urllib.parse.quote(phone)}" if phone else "#"
        done_button = ""
        if row_status != "done":
            done_button = f'<a class="btn ok" href="/admin/orders/done?key={urllib.parse.quote(key)}&idx={idx}">تم التنفيذ</a>'
        else:
            done_button = '<span class="btn secondary">منتهي</span>'
        cards += f"""
        <div class="card order-card">
          <div class="order-row"><strong>الوقت</strong><span>{e(row.get('time'))}</span></div>
          <div class="order-row"><strong>رقم الزبون</strong><a href="{phone_link}" target="_blank">{e(phone)}</a></div>
          <div class="order-row"><strong>المنتج</strong><span>{e(row.get('product'))}</span></div>
          <div class="order-row"><strong>السعر</strong><span>{e(row.get('price'))}</span></div>
          <div class="order-row"><strong>ملاحظة</strong><span>{e(row.get('notes'))}</span></div>
          <div class="order-row"><strong>الحالة</strong><span class="{status_class}">{status_ar}</span></div>
          <div class="actions">
            {done_button}
            <a class="btn danger" href="/admin/orders/delete?key={urllib.parse.quote(key)}&idx={idx}" onclick="return confirm('حذف الطلب؟')">حذف</a>
          </div>
        </div>
        """
    if not cards:
        cards = '<div class="box notice">لا توجد طلبات في هذا القسم.</div>'

    body = f"""
    <h1>طلبات الحجز - {e(business_name())}</h1>
    {admin_nav(key)}
    <div class="box">
      <p class="msg">{e(msg)}</p>
      <div class="nav">
        <a class="btn secondary" href="/admin/orders?key={urllib.parse.quote(key)}&status=all">كل الطلبات</a>
        <a class="btn secondary" href="/admin/orders?key={urllib.parse.quote(key)}&status=new">الجديدة</a>
        <a class="btn secondary" href="/admin/orders?key={urllib.parse.quote(key)}&status=done">المنفذة</a>
        <a class="btn secondary" href="/admin/orders/export?key={urllib.parse.quote(key)}">تصدير CSV</a>
      </div>
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
                        text = msg.get("text", {}).get("body", "")
                        reply = build_reply(text, from_number)
                    else:
                        reply = f"وصلت رسالتك إلى {business_name()}. حالياً أقدر أرد على أسماء المنتجات المكتوبة فقط."
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
