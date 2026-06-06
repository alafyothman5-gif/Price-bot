import asyncio
import base64
import hashlib
import hmac
import io
import json
import os
import re
import time
import traceback
from collections import OrderedDict, defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from PIL import Image

import admin
import database
import matcher
import product_intelligence as intel
from routes import merchant as merchant_routes
from services.security import mask_phone as v19_mask_phone


load_dotenv()


def get_env_var(possible_names: List[str], default: str = "") -> str:
    for name in possible_names:
        value = os.getenv(name)
        if value:
            return str(value).strip()
    return default


def split_secret_list(value: str) -> List[str]:
    keys = []
    for part in re.split(r"\|\||\||,|;|\s|\n", value or ""):
        token = part.strip()
        if token and token not in keys:
            keys.append(token)
    return keys


def get_valid_keys_list(possible_names: List[str]) -> List[str]:
    keys = []
    for name in possible_names:
        for token in split_secret_list(os.getenv(name, "")):
            if (token.startswith("sk-or") or token.startswith("sk")) and token not in keys:
                keys.append(token)
    return keys


META_TOKEN = get_env_var([
    "WHATSAPP_TOKEN", "WHATSAPP_API_TOKEN", "META_TOKEN", "META_ACCESS_TOKEN",
    "WHATSAPP_PERMANENT_TOKEN", "WHATSAPP_ACCESS_TOKEN", "WA_ACCESS_TOKEN", "WA_TOKEN",
    "META_WHATSAPP_TOKEN", "META_WHATSAPP_ACCESS_TOKEN", "FACEBOOK_ACCESS_TOKEN",
    "ACCESS_TOKEN", "GRAPH_API_TOKEN", "CLOUD_API_TOKEN",
])
PHONE_ID = get_env_var(["PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID_1", "WA_PHONE_NUMBER_ID"])
VERIFY_TOKEN = get_env_var(["VERIFY_TOKEN", "WEBHOOK_VERIFY_TOKEN", "META_VERIFY_TOKEN"], "pricebot_verify_2026")
AI_KEYS_LIST = get_valid_keys_list(["OPENROUTER_API_KEY", "OPENROUTER_KEYS", "OPENROUTER_KEY", "AI_OPENROUTER_KEYS", "AI_OPENROUTER_KEY"])
AI_MODEL = get_env_var(["OPENROUTER_MODEL", "AI_MODEL", "AI_OPENROUTER_MODEL"], "google/gemini-2.5-flash-lite")
ADMIN_NOTIFY_PHONE = re.sub(r"\D", "", get_env_var(["ADMIN_NOTIFY_PHONE"]))
META_APP_SECRET = get_env_var(["META_APP_SECRET", "FACEBOOK_APP_SECRET", "WHATSAPP_APP_SECRET"])
PRICEBOT_ENV = get_env_var(["PRICEBOT_ENV", "ENV", "APP_ENV"], "local").lower()
PRICEBOT_DEBUG_ENDPOINTS = get_env_var(["PRICEBOT_DEBUG_ENDPOINTS"], "false").lower() in {"1", "true", "yes", "on"}
PRICEBOT_REQUIRE_META_SIGNATURE = get_env_var(["PRICEBOT_REQUIRE_META_SIGNATURE"], "").lower() in {"1", "true", "yes", "on"}

TEXT_TIMEOUT_SECONDS = float(os.getenv("PRICEBOT_TEXT_TIMEOUT_SECONDS", "12"))
MEDIA_TIMEOUT_SECONDS = float(os.getenv("PRICEBOT_MEDIA_TIMEOUT_SECONDS", "8"))
VISION_TIMEOUT_SECONDS = float(os.getenv("PRICEBOT_VISION_TIMEOUT_SECONDS", "18"))
IMAGE_TOTAL_TIMEOUT_SECONDS = float(os.getenv("PRICEBOT_IMAGE_TOTAL_TIMEOUT_SECONDS", "28"))
QUEUE_MAXSIZE = int(os.getenv("PRICEBOT_QUEUE_MAXSIZE", "500"))
WORKERS_COUNT = int(os.getenv("PRICEBOT_WORKERS", "5"))
LOCK_CACHE_MAX = int(os.getenv("PRICEBOT_LOCK_CACHE_MAX", "2000"))
LOCK_TTL_SECONDS = int(os.getenv("PRICEBOT_LOCK_TTL_SECONDS", "1800"))
RATE_LIMIT_MESSAGES = int(os.getenv("PRICEBOT_RATE_LIMIT_MESSAGES", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("PRICEBOT_RATE_LIMIT_WINDOW_SECONDS", "60"))
DB_OP_TIMEOUT_SECONDS = float(os.getenv("PRICEBOT_DB_OP_TIMEOUT_SECONDS", "3"))
USER_LOCK_ACQUIRE_TIMEOUT_SECONDS = float(os.getenv("PRICEBOT_USER_LOCK_ACQUIRE_TIMEOUT_SECONDS", "6"))
STALE_ORDER_HOURS = int(os.getenv("PRICEBOT_STALE_ORDER_HOURS", "6"))
AI_COST_PER_1K_TOKENS = float(os.getenv("OPENROUTER_ESTIMATED_COST_PER_1K_TOKENS", "0"))


http_client: Optional[httpx.AsyncClient] = None
queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
user_locks: "OrderedDict[str, Tuple[asyncio.Lock, float]]" = OrderedDict()
rate_buckets: Dict[str, Deque[float]] = defaultdict(deque)
background_tasks: List[asyncio.Task] = []
health_cache = {"ts": 0.0, "data": {}}


def mask_token(token: str) -> str:
    if not token:
        return "NONE"
    return f"{token[:4]}...HIDDEN" if len(token) > 8 else "HIDDEN"


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) < 7:
        return "MASKED" if digits else ""
    return f"{digits[:5]}****{digits[-3:]}"


def _safe_log_value(key: str, value):
    key_low = str(key or "").lower()
    if value is None or value == "":
        return value
    if any(word in key_low for word in ["token", "secret", "password", "authorization", "api_key", "access_key"]):
        return "HIDDEN"
    if key_low in {"phone", "to", "from", "sender", "recipient", "customer", "admin_phone"}:
        return mask_phone(str(value))
    if key_low == "response":
        return str(value)[:160].replace(os.getenv("WHATSAPP_ACCESS_TOKEN", "__NO_TOKEN__"), "HIDDEN")
    return value


def log_event(event: str, **fields) -> None:
    safe_fields = {}
    for key, value in fields.items():
        if event in {"RAW_QUERY", "NORMALIZED_QUERY"} and str(key).lower() == "value":
            text = str(value or "")
            value = "[redacted_empty]" if not text else f"[redacted_len={len(text)}]"
        safe_fields[key] = value
    details = " | ".join(
        f"{key}={_safe_log_value(key, value)}"
        for key, value in safe_fields.items()
        if value is not None and value != ""
    )
    print(f"{event}{' | ' + details if details else ''}")


def _is_production_env() -> bool:
    return PRICEBOT_ENV in {"prod", "production", "live"}


def _meta_signature_required() -> bool:
    return bool(META_APP_SECRET or PRICEBOT_REQUIRE_META_SIGNATURE or _is_production_env())


def verify_meta_signature(body: bytes, signature_header: str = "") -> bool:
    """Verify Meta X-Hub-Signature-256 without logging secrets."""
    if not _meta_signature_required():
        return True
    if not META_APP_SECRET:
        log_event("META_SIGNATURE_CONFIG_ERROR", reason="META_APP_SECRET_missing")
        return False
    signature_header = str(signature_header or "").strip()
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(META_APP_SECRET.encode("utf-8"), body or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header, expected)


async def run_db_op(label: str, func, *args, timeout: float = DB_OP_TIMEOUT_SECONDS, default=None):
    """Run potentially blocking SQLite work outside the event loop.

    This prevents WhatsApp workers from freezing after MESSAGE_ID when SQLite is
    locked or slow. The customer should receive a safe reply instead of the
    whole FastAPI app becoming unresponsive.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(func, *args), timeout=timeout)
    except asyncio.TimeoutError:
        log_event("DB_OP_TIMEOUT", op=label, timeout=timeout)
        return default
    except Exception as exc:
        log_event("DB_OP_ERROR", op=label, error=repr(exc))
        return default


async def get_user_state_safe(phone: str) -> dict:
    state = await run_db_op("get_user_state", database.get_user_state, phone, default={})
    return state if isinstance(state, dict) else {}



def safe_update_user_state(phone: str, state: dict) -> None:
    try:
        database.update_user_state(phone, state)
    except Exception as exc:
        log_event("USER_STATE_WRITE_ERROR", error=repr(exc))


def safe_clear_user_state(phone: str) -> None:
    try:
        database.clear_user_state(phone)
    except Exception as exc:
        log_event("USER_STATE_CLEAR_ERROR", error=repr(exc))

def get_user_lock(phone: str) -> asyncio.Lock:
    now = time.time()
    item = user_locks.get(phone)
    if item:
        lock, _ = item
        user_locks.move_to_end(phone)
        user_locks[phone] = (lock, now)
        return lock
    lock = asyncio.Lock()
    user_locks[phone] = (lock, now)
    if len(user_locks) > LOCK_CACHE_MAX:
        # Remove unlocked oldest locks only.
        for key in list(user_locks.keys()):
            old_lock, _ = user_locks[key]
            if not old_lock.locked():
                user_locks.pop(key, None)
                break
    return lock


def cleanup_user_locks() -> int:
    now = time.time()
    removed = 0
    for key in list(user_locks.keys()):
        lock, last_seen = user_locks[key]
        if not lock.locked() and now - last_seen > LOCK_TTL_SECONDS:
            user_locks.pop(key, None)
            removed += 1
    return removed


def rate_limit_ok(phone: str) -> bool:
    now = time.time()
    bucket = rate_buckets[phone]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MESSAGES:
        return False
    bucket.append(now)
    return True


def cleanup_rate_buckets() -> int:
    now = time.time()
    removed = 0
    for phone in list(rate_buckets.keys()):
        bucket = rate_buckets[phone]
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if not bucket:
            del rate_buckets[phone]
            removed += 1
    return removed


async def send_whatsapp_message(to_number: str, text: str) -> bool:
    log_event("SEND_ATTEMPT", to=to_number)
    if not text:
        log_event("SEND_ERROR", reason="empty_reply")
        return False
    if not META_TOKEN or not PHONE_ID:
        log_event("SEND_ERROR", reason="whatsapp_config_missing")
        return False
    if http_client is None:
        log_event("SEND_ERROR", reason="http_client_not_ready")
        return False

    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_number, "type": "text", "text": {"body": text}}
    try:
        response = await http_client.post(url, json=payload, headers=headers, timeout=10.0)
        if 200 <= response.status_code < 300:
            log_event("SEND_OK", status=response.status_code)
            return True
        log_event("SEND_ERROR", status=response.status_code, response=response.text[:300])
        return False
    except Exception as exc:
        log_event("SEND_ERROR", error=exc)
        return False


async def notify_admin(message: str) -> None:
    if ADMIN_NOTIFY_PHONE:
        await send_whatsapp_message(ADMIN_NOTIFY_PHONE, f"🔔 إشعار للصيدلية:\n{message}")


async def notify_stale_pending_orders_once() -> None:
    if not ADMIN_NOTIFY_PHONE:
        return
    try:
        stale = database.get_stale_pending_orders(STALE_ORDER_HOURS, limit=20)
        for order in stale:
            await notify_admin(
                f"طلب حجز ما زال قيد الانتظار منذ أكثر من {STALE_ORDER_HOURS} ساعات:\n"
                f"رقم الطلب: #{order.get('id')}\n"
                f"الزبون: {order.get('phone','')}\n"
                f"المنتج: {order.get('product_name','')}\n"
                f"السعر: {order.get('price','')}\n"
                f"التاريخ: {order.get('created_at','')}"
            )
            database.mark_order_stale_notified(int(order.get("id")))
    except Exception as exc:
        log_event("STALE_ORDER_NOTIFY_ERROR", error=exc)


async def cleanup_loop() -> None:
    while True:
        try:
            locks_removed = cleanup_user_locks()
            rate_removed = cleanup_rate_buckets()
            db_removed = await run_db_op("cleanup_old_processed_messages", database.cleanup_old_processed_messages, 30, timeout=5.0, default=0)
            state_removed = await run_db_op("cleanup_old_conversation_state", database.cleanup_old_conversation_state, 30, timeout=5.0, default=0)
            log_event("CLEANUP_OK", locks=locks_removed, rate_buckets=rate_removed, processed_messages=db_removed, states=state_removed)
            # Stale-order notifications are non-critical and must not block workers.
            try:
                await asyncio.wait_for(notify_stale_pending_orders_once(), timeout=5.0)
            except asyncio.TimeoutError:
                log_event("STALE_ORDER_NOTIFY_TIMEOUT")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event("CLEANUP_ERROR", error=exc)
        await asyncio.sleep(3600)


def resize_image_b64(b64_img: str) -> str:
    try:
        image_data = base64.b64decode(b64_img)
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        image.thumbnail((1024, 1024))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=82)
        return base64.b64encode(output.getvalue()).decode("utf-8")
    except Exception as exc:
        log_event("IMAGE_RESIZE_WARNING", error=exc)
        return b64_img


def extract_robust_json(text: str) -> dict:
    try:
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except Exception as exc:
        log_event("AI_JSON_PARSE_ERROR", error=exc)
        return {}


def validate_ai_data(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    allowed_types = {"product_packaging", "prescription", "unclear", "other", "unknown", "prescription_or_unclear"}
    allowed_areas = {"face", "body", "baby", "hair", "mouth", "unknown", ""}
    allowed_clarity = {"good", "medium", "bad", ""}
    data = dict(raw)
    image_type = str(data.get("image_type") or "unknown").lower().strip()
    if image_type not in allowed_types:
        image_type = "unknown"
    target_area = str(data.get("target_area") or "unknown").lower().strip()
    if target_area not in allowed_areas:
        target_area = "unknown"
    clarity = str(data.get("clarity") or "").lower().strip()
    if clarity not in allowed_clarity:
        clarity = ""
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0) or 0.0)))
    except Exception:
        confidence = 0.0
    product_names = data.get("product_names")
    if not isinstance(product_names, list):
        product_names = [str(product_names)] if product_names else []
    return {
        "image_type": image_type,
        "brand": str(data.get("brand") or "").strip(),
        "product_name": str(data.get("product_name") or "").strip(),
        "product_names": [str(x).strip() for x in product_names if str(x).strip()],
        "visible_text": str(data.get("visible_text") or "").strip(),
        "product_type": str(data.get("product_type") or "").strip(),
        "target_area": target_area,
        "size": str(data.get("size") or "").strip(),
        "strength": str(data.get("strength") or "").strip(),
        "barcode": str(data.get("barcode") or "").strip(),
        "ocr_text": str(data.get("ocr_text") or data.get("visible_text") or "").strip(),
        "visual_similarity_product_id": str(data.get("visual_similarity_product_id") or "").strip(),
        "skin_concern": str(data.get("skin_concern") or data.get("concern") or "").strip(),
        "usage_purpose": str(data.get("usage_purpose") or data.get("purpose") or "").strip(),
        "confidence": confidence,
        "clarity": clarity,
        "requires_admin_review": bool(data.get("requires_admin_review")),
    }


def extract_best_visible_name(text: str) -> str:
    if not text:
        return ""
    ignore_patterns = [
        r"\b\d+\s*(ml|oz|fl\s*oz|g|mg|kg|l)\b",
        r"\b\d+(\.\d+)?\s*(fl\s*)?oz\b",
        r"ingredients", r"directions", r"for normal skin", r"for dry skin", r"dermatologist", r"made in",
    ]
    lines = []
    for line in re.split(r"[\n\r]+", text):
        clean_line = " ".join(line.strip().split())
        if not clean_line:
            continue
        low = clean_line.lower()
        if any(re.search(pattern, low) for pattern in ignore_patterns):
            continue
        if len(clean_line) <= 2:
            continue
        lines.append(clean_line)
    return " ".join(lines[:2]).strip()


def clean_image_query(query: str) -> str:
    q = " ".join(str(query or "").split())
    q = re.sub(r"\b\d+(\.\d+)?\s*(ml|oz|fl\s*oz|g|mg|kg|l)\b", " ", q, flags=re.I)
    q = re.sub(r"\b\d+\s*x\s*\d+\b", " ", q, flags=re.I)
    q = re.sub(r"\b(for normal skin|for dry skin|for oily skin)\b", " ", q, flags=re.I)
    return " ".join(q.split())


def _as_product_names(value) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def visible_text_has_product_signal(ai_data: dict) -> bool:
    """Cheap, non-blocking signal check for images.

    This deliberately avoids matcher.inspect_query() and any catalog/database scan.
    Image AI may provide weak words such as "cream" or "gel"; those alone must
    not trigger product matching or alternatives.
    """
    combined = " ".join([
        str(ai_data.get("brand", "") or ""),
        str(ai_data.get("product_name", "") or ""),
        str(ai_data.get("visible_text", "") or ""),
        *(_as_product_names(ai_data.get("product_names", []))),
    ])
    normalized = re.sub(r"[^a-z0-9\u0600-\u06FF]+", " ", combined.lower()).strip()
    if not normalized:
        return False
    tokens = [t for t in normalized.split() if len(t) >= 3]
    weak = {"skin","face","cream","gel","oil","daily","active","hydrating","moisturizing","moisturising","lotion","serum","balm","cleanser","sunscreen","100ml","50ml","200ml"}
    strong = [t for t in tokens if t not in weak and not re.fullmatch(r"\d+ml|\d+mg|\d+", t)]
    return len(strong) >= 2 or (len(strong) >= 1 and any(t in tokens for t in {"cleanser","serum","lotion","cream","sunscreen","balm"}))


async def analyze_image_with_ai(phone: str, base64_img: str) -> Optional[dict]:
    log_event("AI_START", model=AI_MODEL)
    if not AI_KEYS_LIST:
        database.log_ai_usage(phone=phone, model=AI_MODEL, success=False, error="no_openrouter_keys")
        database.log_ai_usage_v19(customer_phone_masked=v19_mask_phone(phone), model=AI_MODEL, purpose="vision", image_count=1, success=False, error="no_openrouter_keys")
        log_event("AI_ERROR", reason="no_openrouter_keys")
        return None
    if http_client is None:
        database.log_ai_usage(phone=phone, model=AI_MODEL, success=False, error="http_client_not_ready")
        database.log_ai_usage_v19(customer_phone_masked=v19_mask_phone(phone), model=AI_MODEL, purpose="vision", image_count=1, success=False, error="http_client_not_ready")
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    prompt_msg = (
        "Extract visible product information only. Return ONLY valid JSON. "
        "Do not guess availability. Do not guess price. Do not recommend alternatives. "
        "Do not give medical advice or dose instructions. The local database will decide price/stock. "
        "If it is a prescription/روشتة, set image_type to prescription. If unclear, set image_quality to blurry/partial/dark. "
        "If the image contains more than one product, set image_quality to multiple_products. "
        "For product packaging, extract only text clearly visible on the front label: brand, product_family/product_name, form/type, strength, and size. "
        "Classify form/product_type as one of: cleanser, sunscreen, serum, shampoo, lotion, moisturizer, cream, gel, oil, balm, drops, spray, syrup, tablet, capsule, suppository, injection, unknown.\n\n"
        "{\n"
        '"image_type": "product_packaging|prescription|unclear|other|unknown",\n'
        '"brand": "",\n"product_name": "",\n"product_family": "",\n"product_names": [],\n'
        '"form": "",\n"product_type": "",\n"category": "medicine|cosmetic|other|unknown",\n'
        '"strength": "",\n"size": "",\n"visible_text": [],\n"ocr_text": "",\n'
        '"target_area": "face|body|baby|hair|mouth|unknown",\n'
        '"skin_concern": "",\n"usage_purpose": "",\n'
        '"confidence": 0.0,\n"image_quality": "clear|blurry|partial|dark|multiple_products",\n"clarity": "good|medium|bad",\n"notes": "",\n"requires_admin_review": false\n}'
    )

    for idx, key in enumerate(AI_KEYS_LIST):
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "HTTP-Referer": "https://pricebot-libya.com", "X-Title": "PriceBot"}
        payload = {
            "model": AI_MODEL,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt_msg},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}},
            ]}],
        }
        try:
            response = await http_client.post(url, json=payload, headers=headers, timeout=VISION_TIMEOUT_SECONDS)
            if response.status_code == 400 and "response_format" in response.text.lower():
                payload.pop("response_format", None)
                response = await http_client.post(url, json=payload, headers=headers, timeout=VISION_TIMEOUT_SECONDS)
            if response.status_code == 200:
                body = response.json()
                usage = body.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
                estimated_cost = (total_tokens / 1000.0) * AI_COST_PER_1K_TOKENS if AI_COST_PER_1K_TOKENS else 0.0
                content = body["choices"][0]["message"]["content"]
                ai_data = validate_ai_data(extract_robust_json(content))
                database.log_ai_usage(phone=phone, model=AI_MODEL, image_type=ai_data.get("image_type", "unknown"), success=bool(ai_data), prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens, estimated_cost=estimated_cost)
                database.log_ai_usage_v19(customer_phone_masked=v19_mask_phone(phone), model=AI_MODEL, purpose="vision", tokens_in=prompt_tokens, tokens_out=completion_tokens, image_count=1, cost_estimate=estimated_cost, success=bool(ai_data))
                log_event("AI_PARSED_JSON", data={k: ai_data.get(k) for k in ["image_type", "brand", "product_name", "product_type", "target_area", "skin_concern", "usage_purpose", "confidence", "clarity"]})
                return ai_data if ai_data else None
            database.log_ai_usage(phone=phone, model=AI_MODEL, success=False, error=f"http_{response.status_code}")
            database.log_ai_usage_v19(customer_phone_masked=v19_mask_phone(phone), model=AI_MODEL, purpose="vision", image_count=1, success=False, error=f"http_{response.status_code}")
            log_event("AI_HTTP_STATUS", status=response.status_code, response=response.text[:300])
            if response.status_code in {401, 402, 429} or 500 <= response.status_code <= 599:
                if idx < len(AI_KEYS_LIST) - 1:
                    log_event("AI_RETRY_NEXT_KEY", failed_status=response.status_code)
                    continue
            return None
        except Exception as exc:
            database.log_ai_usage(phone=phone, model=AI_MODEL, success=False, error=str(exc)[:250])
            database.log_ai_usage_v19(customer_phone_masked=v19_mask_phone(phone), model=AI_MODEL, purpose="vision", image_count=1, success=False, error=str(exc)[:250])
            log_event("AI_ERROR", error=exc)
            if idx < len(AI_KEYS_LIST) - 1:
                log_event("AI_RETRY_NEXT_KEY", reason="exception")
                continue
            return None
    return None


def build_image_queries(ai_data: dict) -> List[str]:
    brand = str(ai_data.get("brand", "") or "").strip()
    product_name = str(ai_data.get("product_name", "") or "").strip()
    product_type = str(ai_data.get("product_type", "") or "").strip()
    skin_concern = str(ai_data.get("skin_concern", "") or "").strip()
    usage_purpose = str(ai_data.get("usage_purpose", "") or "").strip()
    visible = extract_best_visible_name(str(ai_data.get("visible_text", "") or ""))
    visible = intel.normalize_visible_label(visible)
    product_names = _as_product_names(ai_data.get("product_names", []))
    raw_queries = [
        f"{brand} {product_name}".strip(),
        f"{brand} {product_name} {product_type}".strip(),
        f"{brand} {product_name} {product_type} {skin_concern} {usage_purpose}".strip(),
        f"{brand} {visible}".strip() if visible else "",
        f"{brand} {visible} {product_type} {skin_concern}".strip() if visible else "",
        *[f"{brand} {name}".strip() for name in product_names],
        *[f"{brand} {name} {product_type}".strip() for name in product_names],
        product_name,
        visible,
    ]
    queries, seen = [], set()
    for raw in raw_queries:
        query = clean_image_query(raw)
        key = matcher.normalize_text(query)
        if len(key) <= 2 or key in seen:
            continue
        seen.add(key)
        queries.append(query)
    return queries


async def run_image_matching(phone: str, ai_data: dict, user_state: dict) -> str:
    ai_data = validate_ai_data(ai_data)
    if ai_data.get("invalid_vision_output"):
        log_event("VISION_INVALID_OUTPUT_REJECTED", reason="model_returned_stock_price_or_recommendation")
        return matcher.build_unclear_image_reply()
    image_type = ai_data.get("image_type", "unknown")
    clarity = ai_data.get("clarity", "")
    confidence = float(ai_data.get("confidence", 0.0) or 0.0)

    if image_type in {"prescription", "prescription_or_unclear"}:
        await notify_admin(f"روشتة طبية تحتاج مراجعة من الرقم:\n{phone}")
        log_event("FINAL_DECISION", decision="prescription_review")
        return matcher.build_prescription_reply()
    if ai_data.get("requires_admin_review"):
        await notify_admin(f"مراجعة صورة مطلوبة من الرقم:\n{phone}")
        log_event("FINAL_DECISION", decision="admin_review")
        return matcher.with_header("تم استلام الصورة وسيتم مراجعتها من قبل الصيدلية للرد عليك قريباً.")
    if image_type in {"unclear", "other", "unknown"} or clarity == "bad":
        log_event("FINAL_DECISION", decision="unclear_image")
        return matcher.build_unclear_image_reply()
    if confidence < 0.75:
        log_event("FINAL_DECISION", decision="low_confidence_unclear", confidence=confidence)
        return matcher.build_unclear_image_reply()

    target_area = str(ai_data.get("target_area", "") or "").strip().lower()
    if target_area in {"unknown", "none", "null"}:
        target_area = ""
    queries = build_image_queries(ai_data)
    try:
        direct_image_decision = await asyncio.wait_for(
            asyncio.to_thread(matcher.resolve_image_query_decision, ai_data),
            timeout=TEXT_TIMEOUT_SECONDS,
        )
        dtype = direct_image_decision.decision_type.name
        if dtype == "EXACT_MATCH" and direct_image_decision.product:
            item = direct_image_decision.product
            if matcher.is_available(item.get("available", "")):
                await run_db_op("image_set_last_product", database.update_user_state, phone, {"last_product": item})
            else:
                await run_db_op("image_clear_state", database.clear_user_state, phone)
            log_event("FINAL_DECISION", decision="matched_from_image_v4", product=item.get("name", ""), reason=direct_image_decision.reason)
            return matcher.build_product_reply(item)
        if dtype == "ASK_CLARIFICATION":
            log_event("FINAL_DECISION", decision="image_ask_clarification_v4", reason=direct_image_decision.reason)
            return matcher.build_v2_clarification_reply(phone, direct_image_decision)
        if dtype == "COSMETIC_ALTERNATIVES":
            log_event("FINAL_DECISION", decision="cosmetic_alternatives_from_image_v4", reason=direct_image_decision.reason)
            return matcher.build_v2_alternatives_reply(phone, direct_image_decision)
        if dtype == "NOT_AVAILABLE":
            await run_db_op("image_clear_state", database.clear_user_state, phone)
            log_event("FINAL_DECISION", decision="image_not_available_v4", reason=direct_image_decision.reason)
            return matcher.build_unavailable_reply(matcher.clean_query(" ".join(queries)), direct_image_decision.product, phone)
        if dtype in {"IMAGE_UNCLEAR", "LOW_CONFIDENCE"}:
            await run_db_op("image_clear_state", database.clear_user_state, phone)
            log_event("FINAL_DECISION", decision="image_unclear_or_low_confidence_v4", reason=direct_image_decision.reason, confidence=confidence)
            return matcher.build_unclear_image_reply()
    except Exception as exc:
        log_event("MATCHER_V4_IMAGE_DIRECT_WARNING", error=exc)
        return matcher.with_header("لم أتمكن من تحديد المنتج من الصورة بدقة. الرجاء كتابة الاسم الكامل أو إرسال صورة أوضح للواجهة الأمامية.")

    # V4 is the only final decision engine for images. Do not fall back to
    # generated text queries or legacy fuzzy matching; that caused wrong
    # unavailable/alternative replies from weak OCR.
    log_event("FINAL_DECISION", decision="image_no_final_v4_decision")
    return matcher.build_unclear_image_reply()



async def handle_image_logic(phone: str, image_id: str, user_state: dict) -> str:
    if not image_id:
        return matcher.build_unclear_image_reply()
    if not META_TOKEN or http_client is None:
        log_event("MEDIA_DOWNLOAD_ERROR", reason="whatsapp_token_or_client_missing")
        return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")
    headers = {"Authorization": f"Bearer {META_TOKEN}"}
    info_url = f"https://graph.facebook.com/v20.0/{image_id}"
    try:
        log_event("MEDIA_DOWNLOAD_START", image_id=image_id)
        info_response = await http_client.get(info_url, headers=headers, timeout=MEDIA_TIMEOUT_SECONDS)
        if info_response.status_code != 200:
            log_event("MEDIA_DOWNLOAD_ERROR", status=info_response.status_code, response=info_response.text[:300])
            return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")
        media_url = info_response.json().get("url")
        if not media_url:
            return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")
        image_response = await http_client.get(media_url, headers=headers, timeout=MEDIA_TIMEOUT_SECONDS)
        if image_response.status_code != 200:
            log_event("MEDIA_DOWNLOAD_ERROR", status=image_response.status_code, response=image_response.text[:300])
            return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")
        log_event("MEDIA_DOWNLOAD_OK", bytes=len(image_response.content))
        b64 = resize_image_b64(base64.b64encode(image_response.content).decode("utf-8"))
    except httpx.TimeoutException:
        log_event("MEDIA_DOWNLOAD_TIMEOUT")
        return matcher.with_header("تعذر تحميل الصورة خلال الوقت المحدد. الرجاء كتابة اسم المنتج كما هو على العلبة.")
    except Exception as exc:
        log_event("MEDIA_DOWNLOAD_ERROR", error=exc)
        return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")

    ai_data = await analyze_image_with_ai(phone, b64)
    if not ai_data:
        log_event("FINAL_DECISION", decision="ai_error_fallback")
        return matcher.with_header("تعذر قراءة الصورة حالياً. الرجاء كتابة اسم المنتج كما هو على العلبة.")
    return await run_image_matching(phone, ai_data, user_state)


async def process_single_message(phone: str, msg_id: str, msg_type: str, msg: dict) -> None:
    log_event("PROCESS_SINGLE_START", phone=phone, msg_type=msg_type)
    if not rate_limit_ok(phone):
        reply = matcher.with_header("تم إرسال رسائل كثيرة خلال وقت قصير. الرجاء المحاولة بعد دقيقة.")
        send_ok = await send_whatsapp_message(phone, reply)
        await run_db_op("mark_rate_limited", database.mark_message_done, msg_id, "done" if send_ok else "failed")
        await run_db_op("log_rate_limited", database.log_product_inquiry, phone, "[RATE_LIMIT]", "", msg_type, "rate_limited", "", msg_id)
        return

    user_state = {}
    final_reply = ""
    final_decision = "fallback"
    matched_product = ""
    raw_query = ""
    normalized_query = ""
    order_item_for_notify = None

    try:
        if msg_type == "text":
            raw_query = msg.get("text", {}).get("body", "")
            log_event("SOURCE", value="text")
            log_event("RAW_QUERY", value=raw_query)
            # v15: no debug catalog inspection in the live text path.
            # The final decision engine is called once below in a worker thread.
            normalized_query = matcher.clean_query(raw_query) if hasattr(matcher, "clean_query") else str(raw_query or "")
            log_event("NORMALIZED_QUERY", value=normalized_query)
            user_state = await get_user_state_safe(phone)
            result = await asyncio.wait_for(asyncio.to_thread(matcher.handle_text_query_result, phone, raw_query, user_state), timeout=TEXT_TIMEOUT_SECONDS)
            final_reply = result.reply
            final_decision = result.decision
            matched_product = (result.product or {}).get("name", "")
            order_item_for_notify = result.order_item
        elif msg_type == "image":
            raw_query = "[IMAGE]"
            log_event("SOURCE", value="image")
            log_event("RAW_QUERY", value=raw_query)
            image_id = msg.get("image", {}).get("id", "")
            user_state = await get_user_state_safe(phone)
            await send_whatsapp_message(phone, "جاري فحص الصورة، انتظر لحظات...")
            final_reply = await asyncio.wait_for(handle_image_logic(phone, image_id, user_state), timeout=IMAGE_TOTAL_TIMEOUT_SECONDS)
            final_decision = "image_reply"
            normalized_query = "[IMAGE]"
        else:
            raw_query = f"[{msg_type}]"
            final_reply = matcher.with_header("عذراً، أنا أدعم الرسائل النصية والصور فقط.")
            final_decision = "unsupported"
    except asyncio.TimeoutError:
        log_event("TIMEOUT_FALLBACK", message_id=msg_id)
        final_reply = matcher.with_header("عذراً، استغرق البحث وقتاً أطول من المتوقع. الرجاء المحاولة مرة أخرى.")
        final_decision = "timeout_fallback"
    except Exception as exc:
        log_event("ERROR_FALLBACK", error=exc)
        final_reply = matcher.with_header("صار خطأ مؤقت، حاول مرة ثانية بعد لحظات.")
        final_decision = "error_fallback"

    if not final_reply:
        final_reply = matcher.build_fallback_reply()
        final_decision = "fallback"

    log_event("FINAL_DECISION", decision=final_decision)
    send_ok = await send_whatsapp_message(phone, final_reply)
    await run_db_op("mark_message_done", database.mark_message_done, msg_id, "done" if send_ok else "failed")
    await run_db_op("log_product_inquiry", database.log_product_inquiry, phone, raw_query, normalized_query, msg_type, final_decision, matched_product, msg_id)
    await run_db_op("log_query_miss", matcher._log_query_miss_if_needed, phone, raw_query, normalized_query, final_decision)

    if send_ok and final_decision == "order_created" and order_item_for_notify:
        await notify_admin(
            f"حجز جديد:\nالرقم: {phone}\nالمنتج: {order_item_for_notify.get('name', '')}\nالسعر: {order_item_for_notify.get('price', '')}\nالوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )


async def process_message(payload: dict) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "statuses" in value:
                continue
            for msg in value.get("messages", []):
                phone = msg.get("from")
                msg_id = msg.get("id")
                msg_type = msg.get("type")
                if not phone or not msg_id:
                    continue
                should_process = await run_db_op("start_processing_message", database.start_processing_message, msg_id, phone, default=False)
                if not should_process:
                    log_event("MESSAGE_SKIPPED", message_id=msg_id, reason="done_or_processing_or_db_error")
                    continue
                print("\n--- LOG START ---")
                log_event("MESSAGE_ID", value=msg_id)
                lock = get_user_lock(phone)
                acquired = False
                try:
                    try:
                        await asyncio.wait_for(lock.acquire(), timeout=USER_LOCK_ACQUIRE_TIMEOUT_SECONDS)
                        acquired = True
                        log_event("USER_LOCK_ACQUIRED", phone=phone)
                    except asyncio.TimeoutError:
                        log_event("USER_LOCK_TIMEOUT", phone=phone, timeout=USER_LOCK_ACQUIRE_TIMEOUT_SECONDS)
                        await run_db_op("mark_lock_timeout", database.mark_message_done, msg_id, "failed")
                        await send_whatsapp_message(phone, matcher.with_header("البوت مشغول بمعالجة طلب سابق. الرجاء إرسال الطلب مرة أخرى بعد لحظات."))
                        continue
                    await process_single_message(phone, msg_id, msg_type, msg)
                except Exception as exc:
                    await run_db_op("mark_failed_message", database.mark_message_done, msg_id, "failed")
                    log_event("MESSAGE_PROCESS_ERROR", error=repr(exc))
                    print(traceback.format_exc())
                    try:
                        await send_whatsapp_message(phone, matcher.with_header("صار خطأ مؤقت، حاول مرة ثانية بعد لحظات."))
                    except Exception:
                        pass
                finally:
                    if acquired and lock.locked():
                        lock.release()
                        log_event("USER_LOCK_RELEASED", phone=phone)
                    print("--- LOG END ---\n")


async def webhook_worker(worker_id: int) -> None:
    while True:
        payload = await queue.get()
        try:
            await process_message(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event("WORKER_ERROR", worker=worker_id, error=exc)
        finally:
            queue.task_done()


async def spawn_worker(worker_id: int) -> None:
    while True:
        try:
            await webhook_worker(worker_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event("WORKER_CRASH_RESTART", worker=worker_id, error=exc)
            await asyncio.sleep(1)


async def warmup_matcher_indexes_background() -> None:
    """Build matcher indexes after FastAPI is already serving requests.

    PRICEBOT_FAST_STARTUP_READY_V1: startup must never wait on the heavy
    4,991-product matcher index. The first boot should reach /health quickly;
    warmup is best-effort in the background. Matching still stays deterministic:
    resolver calls use the same local catalog index and no legacy fuzzy fallback.
    """
    try:
        started = time.time()
        log_event("MATCHER_BACKGROUND_WARMUP_START")
        # V4 strict index. Do not build the older product index here; it is not
        # required for the V4 decision path and it can slow or block startup.
        records = await asyncio.to_thread(matcher.warmup_matcher_v3_cache)
        log_event("MATCHER_BACKGROUND_WARMUP_DONE", records=records, seconds=round(time.time() - started, 2))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log_event("MATCHER_BACKGROUND_WARMUP_ERROR", error=repr(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PRICEBOT_FAST_REPLY_NO_TIMEOUT_CLEAN_V3
    global http_client, queue, background_tasks
    database.init_db()
    database.ensure_v19_tables()
    queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    print("========================================", flush=True)
    log_event("STARTING", version="v19.1-company-level-safe-ready")
    log_event("PRODUCTS_COUNT", value=database.count_products())
    log_event("PHONE_ID_SET", value="YES" if PHONE_ID else "NO")
    log_event("WHATSAPP_TOKEN_SET", value="YES" if META_TOKEN else "NO")
    log_event("META_APP_SECRET_SET", value="YES" if META_APP_SECRET else "NO")
    if _is_production_env() and not META_APP_SECRET:
        log_event("HIGH_RISK_SECURITY_WARNING", reason="META_APP_SECRET_missing_in_production")
    log_event("AI_KEYS_AVAILABLE", count=len(AI_KEYS_LIST), first=mask_token(AI_KEYS_LIST[0]) if AI_KEYS_LIST else "NONE")
    log_event("WORKERS", value=WORKERS_COUNT, queue_maxsize=QUEUE_MAXSIZE, db_path=database.DB_FILE)
    background_tasks = [asyncio.create_task(spawn_worker(i + 1)) for i in range(WORKERS_COUNT)]
    background_tasks.append(asyncio.create_task(cleanup_loop()))
    background_tasks.append(asyncio.create_task(warmup_matcher_indexes_background()))
    print("FAST_SAFE_STARTUP | ready=1", flush=True)
    print("========================================", flush=True)
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        if http_client is not None:
            await http_client.aclose()

app = FastAPI(title="PriceBot / WhatsPrice Bot", version="v19.1-company-level-safe-ready", lifespan=lifespan)
app.include_router(admin.router)
app.include_router(merchant_routes.router)


@app.get("/health")
async def health_check():
    return JSONResponse({"ok": True, "service": "pricebot"})


@app.get("/test_local")
async def test_local(q: str = "", phone: str = "test_user"):
    if not PRICEBOT_DEBUG_ENDPOINTS:
        return PlainTextResponse("Not found", status_code=404)
    user_state = database.get_user_state(phone)
    result = matcher.handle_text_query_result(phone, q, user_state)
    return PlainTextResponse(f"Query: {q}\nDecision: {result.decision}\n---\n{result.reply}")


@app.get("/test_local_image")
async def test_local_image(brand: str = "", name: str = "", type: str = "", area: str = "", phone: str = "test_user"):
    if not PRICEBOT_DEBUG_ENDPOINTS:
        return PlainTextResponse("Not found", status_code=404)
    ai_data = {"image_type": "product_packaging", "brand": brand, "product_name": name, "product_names": [name] if name else [], "visible_text": " ".join(x for x in [brand, name, type] if x), "product_type": type, "target_area": area or "unknown", "confidence": 0.9, "clarity": "good", "requires_admin_review": False}
    reply = await run_image_matching(phone, ai_data, database.get_user_state(phone))
    return PlainTextResponse(f"Mock AI Data: {ai_data}\n---\n{reply}")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    body = await request.body()
    if not verify_meta_signature(body, request.headers.get("X-Hub-Signature-256", "")):
        log_event("META_SIGNATURE_REJECTED", reason="missing_or_invalid")
        return JSONResponse({"ok": False, "error": "invalid_signature"}, status_code=403)
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=200)
    try:
        queue.put_nowait(payload)
        return JSONResponse({"ok": True, "queued": True, "queue_size": queue.qsize()})
    except asyncio.QueueFull:
        log_event("QUEUE_FULL", maxsize=QUEUE_MAXSIZE)
        return JSONResponse({"ok": False, "queued": False, "error": "queue_full"}, status_code=503)


@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)

# ---------------------------------------------------------------------------
# FINAL STRICT V17.5 VISION VALIDATION + IMAGE CACHE OVERRIDES
# ---------------------------------------------------------------------------
import hashlib as _v17_4_hashlib


def validate_ai_data(raw: dict) -> dict:  # type: ignore[override]
    """Sanitize Vision output.

    Vision is extraction-only. If the model returns stock/price/recommendations,
    we keep the visible fields but mark the output unsafe so matcher refuses to
    use it as a product decision.
    """
    if not isinstance(raw, dict):
        return {}
    forbidden = {"price", "availability", "available", "stock", "recommendation", "alternative", "alternatives", "is_available"}
    invalid_claims = any(k in raw and raw.get(k) not in (None, "", [], {}) for k in forbidden)
    allowed_types = {"product_packaging", "prescription", "unclear", "other", "unknown", "prescription_or_unclear", "multiple_products"}
    allowed_areas = {"face", "body", "baby", "hair", "mouth", "unknown", ""}
    allowed_clarity = {"good", "medium", "bad", ""}
    allowed_quality = {"clear", "blurry", "partial", "dark", "multiple_products", "good", "medium", "bad", ""}
    data = dict(raw)
    image_type = str(data.get("image_type") or "unknown").lower().strip()
    if image_type not in allowed_types:
        image_type = "unknown"
    target_area = str(data.get("target_area") or "unknown").lower().strip()
    if target_area not in allowed_areas:
        target_area = "unknown"
    clarity = str(data.get("clarity") or "").lower().strip()
    if clarity not in allowed_clarity:
        clarity = ""
    image_quality = str(data.get("image_quality") or "").lower().strip()
    if image_quality not in allowed_quality:
        image_quality = ""
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0) or 0.0)))
    except Exception:
        confidence = 0.0
    product_names = data.get("product_names")
    if not isinstance(product_names, list):
        product_names = [str(product_names)] if product_names else []
    visible_text = data.get("visible_text")
    if isinstance(visible_text, list):
        visible_text = " ".join(str(x) for x in visible_text if str(x).strip())
    return {
        "image_type": image_type,
        "brand": str(data.get("brand") or "").strip(),
        "product_name": str(data.get("product_name") or "").strip(),
        "product_family": str(data.get("product_family") or "").strip(),
        "product_names": [str(x).strip() for x in product_names if str(x).strip()],
        "visible_text": str(visible_text or "").strip(),
        "product_type": str(data.get("product_type") or data.get("form") or data.get("type") or "").strip(),
        "form": str(data.get("form") or data.get("product_type") or "").strip(),
        "category": str(data.get("category") or "").strip(),
        "target_area": target_area,
        "size": str(data.get("size") or "").strip(),
        "strength": str(data.get("strength") or "").strip(),
        "barcode": str(data.get("barcode") or "").strip(),
        "ocr_text": str(data.get("ocr_text") or str(visible_text or "") or "").strip(),
        "visual_similarity_product_id": str(data.get("visual_similarity_product_id") or "").strip(),
        "skin_concern": str(data.get("skin_concern") or data.get("concern") or "").strip(),
        "usage_purpose": str(data.get("usage_purpose") or data.get("purpose") or "").strip(),
        "confidence": confidence,
        "clarity": clarity,
        "image_quality": image_quality,
        "notes": str(data.get("notes") or "").strip(),
        "requires_admin_review": bool(data.get("requires_admin_review")),
        "invalid_vision_output": bool(invalid_claims),
    }


def _v17_4_image_hash(content: bytes) -> str:
    return _v17_4_hashlib.sha256(content or b"").hexdigest()


def _v17_4_perceptual_hash(content: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(content)).convert("L").resize((8, 8))
        pixels = list(image.getdata())
        avg = sum(pixels) / max(len(pixels), 1)
        bits = ''.join('1' if p >= avg else '0' for p in pixels)
        return f"{int(bits, 2):016x}"
    except Exception:
        return ""


def _v17_4_cache_decision_for_ai(ai_data: dict) -> str:
    if not ai_data:
        return "LOW_CONFIDENCE"
    try:
        d = matcher.resolve_image_query_decision(ai_data)
        return d.decision_type.name
    except Exception:
        quality = str(ai_data.get("image_quality") or ai_data.get("clarity") or "").lower()
        if quality in {"bad", "blurry", "partial", "dark"} or float(ai_data.get("confidence") or 0) < 0.75:
            return "IMAGE_UNCLEAR"
        return "VISION_EXTRACTED"


async def handle_image_logic(phone: str, image_id: str, user_state: dict) -> str:  # type: ignore[override]
    if not image_id:
        return matcher.build_unclear_image_reply()
    if not META_TOKEN or http_client is None:
        log_event("MEDIA_DOWNLOAD_ERROR", reason="whatsapp_token_or_client_missing")
        return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")
    headers = {"Authorization": f"Bearer {META_TOKEN}"}
    info_url = f"https://graph.facebook.com/v20.0/{image_id}"
    try:
        log_event("MEDIA_DOWNLOAD_START", image_id=image_id)
        info_response = await http_client.get(info_url, headers=headers, timeout=MEDIA_TIMEOUT_SECONDS)
        if info_response.status_code != 200:
            log_event("MEDIA_DOWNLOAD_ERROR", status=info_response.status_code, response=info_response.text[:300])
            return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")
        media_url = info_response.json().get("url")
        if not media_url:
            return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")
        image_response = await http_client.get(media_url, headers=headers, timeout=MEDIA_TIMEOUT_SECONDS)
        if image_response.status_code != 200:
            log_event("MEDIA_DOWNLOAD_ERROR", status=image_response.status_code, response=image_response.text[:300])
            return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")
        image_bytes = image_response.content or b""
        log_event("MEDIA_DOWNLOAD_OK", bytes=len(image_bytes))
        image_hash = _v17_4_image_hash(image_bytes)
        perceptual_hash = _v17_4_perceptual_hash(image_bytes)
        cached = await run_db_op("image_cache_get", database.get_image_cache, image_hash, default=None)
        cache_source = "exact"
        if not cached and perceptual_hash:
            cached = await run_db_op("image_cache_get_perceptual", database.get_image_cache_by_perceptual_hash, perceptual_hash, 5, default=None)
            cache_source = "perceptual"
        if cached and isinstance(cached.get("vision_output"), dict) and cached.get("vision_output"):
            ai_data = validate_ai_data(cached.get("vision_output") or {})
            ai_data["_vision_cache_hit"] = True
            log_event("VISION_CACHE_HIT", image_hash=image_hash[:12], perceptual_hash=perceptual_hash[:12], source=cache_source, decision=cached.get("decision"), used_count=cached.get("used_count"))
            return await run_image_matching(phone, ai_data, user_state)
        log_event("VISION_CACHE_MISS", image_hash=image_hash[:12], perceptual_hash=perceptual_hash[:12])
        b64 = resize_image_b64(base64.b64encode(image_bytes).decode("utf-8"))
    except httpx.TimeoutException:
        log_event("MEDIA_DOWNLOAD_TIMEOUT")
        return matcher.with_header("تعذر تحميل الصورة خلال الوقت المحدد. الرجاء كتابة اسم المنتج كما هو على العلبة.")
    except Exception as exc:
        log_event("MEDIA_DOWNLOAD_ERROR", error=exc)
        return matcher.with_header("تعذر تحميل الصورة من واتساب. الرجاء كتابة اسم المنتج كما هو على العلبة.")

    ai_data = await analyze_image_with_ai(phone, b64)
    if not ai_data:
        log_event("FINAL_DECISION", decision="ai_error_fallback")
        return matcher.with_header("تعذر قراءة الصورة حالياً. الرجاء كتابة اسم المنتج كما هو على العلبة.")
    ai_data = validate_ai_data(ai_data)
    cache_decision = await asyncio.to_thread(_v17_4_cache_decision_for_ai, ai_data)
    matched_id = ""
    try:
        d = matcher.resolve_image_query_decision(ai_data)
        if d.product:
            matched_id = str(d.product.get("id") or d.product.get("product_id") or "")
    except Exception:
        pass
    await run_db_op("image_cache_save", database.save_image_cache, image_hash, ai_data, matched_id, cache_decision, float(ai_data.get("confidence") or 0.0), perceptual_hash, default=None)
    log_event("VISION_CACHE_SAVE", image_hash=image_hash[:12], decision=cache_decision)
    return await run_image_matching(phone, ai_data, user_state)
