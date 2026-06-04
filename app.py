import asyncio
import base64
import io
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from PIL import Image

import admin
import database
import matcher


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


META_TOKEN = get_env_var(
    [
        "WHATSAPP_TOKEN",
        "WHATSAPP_API_TOKEN",
        "META_TOKEN",
        "META_ACCESS_TOKEN",
        "WHATSAPP_PERMANENT_TOKEN",
        "WHATSAPP_ACCESS_TOKEN",
        "WA_ACCESS_TOKEN",
        "WA_TOKEN",
        "META_WHATSAPP_TOKEN",
        "META_WHATSAPP_ACCESS_TOKEN",
        "FACEBOOK_ACCESS_TOKEN",
        "ACCESS_TOKEN",
        "GRAPH_API_TOKEN",
        "CLOUD_API_TOKEN",
    ]
)
PHONE_ID = get_env_var(["PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID_1", "WA_PHONE_NUMBER_ID"])
VERIFY_TOKEN = get_env_var(["VERIFY_TOKEN", "WEBHOOK_VERIFY_TOKEN", "META_VERIFY_TOKEN"], "pricebot_verify_2026")
AI_KEYS_LIST = get_valid_keys_list(["OPENROUTER_API_KEY", "OPENROUTER_KEYS", "OPENROUTER_KEY", "AI_OPENROUTER_KEYS", "AI_OPENROUTER_KEY"])
AI_MODEL = get_env_var(["OPENROUTER_MODEL", "AI_MODEL", "AI_OPENROUTER_MODEL"], "google/gemini-2.5-flash-lite")
ADMIN_NOTIFY_PHONE = re.sub(r"\D", "", get_env_var(["ADMIN_NOTIFY_PHONE"]))

TEXT_TIMEOUT_SECONDS = 5.0
MEDIA_TIMEOUT_SECONDS = 8.0
VISION_TIMEOUT_SECONDS = 18.0
IMAGE_TOTAL_TIMEOUT_SECONDS = 28.0


def mask_token(token: str) -> str:
    if not token:
        return "NONE"
    return f"{token[:4]}...HIDDEN" if len(token) > 8 else "HIDDEN"


def log_event(event: str, **fields) -> None:
    details = " | ".join(f"{key}={value}" for key, value in fields.items() if value is not None and value != "")
    print(f"{event}{' | ' + details if details else ''}")


app = FastAPI(title="PriceBot / WhatsPrice Bot", version="stable-v4-admin")
app.include_router(admin.router)

http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
queue: asyncio.Queue = asyncio.Queue()
user_locks: Dict[str, asyncio.Lock] = {}


def get_user_lock(phone: str) -> asyncio.Lock:
    if phone not in user_locks:
        user_locks[phone] = asyncio.Lock()
    return user_locks[phone]


@app.get("/health")
async def health_check():
    try:
        products_count = len(database.load_products())
    except Exception as exc:
        log_event("HEALTH_PRODUCTS_ERROR", error=exc)
        products_count = 0
    return JSONResponse(
        {
            "ok": True,
            "products_count": products_count,
            "ai_enabled": bool(AI_KEYS_LIST),
            "whatsapp_configured": bool(META_TOKEN and PHONE_ID),
            "version": "stable-v4-admin",
        }
    )


@app.get("/test_local")
async def test_local(q: str = "", phone: str = "test_user"):
    user_state = database.get_user_state(phone)
    reply = matcher.handle_text_query(phone, q, user_state)
    return PlainTextResponse(f"Query: {q}\n---\n{reply}")


@app.get("/test_local_image")
async def test_local_image(brand: str = "", name: str = "", type: str = "", area: str = "", phone: str = "test_user"):
    ai_data = {
        "image_type": "product_packaging",
        "brand": brand,
        "product_name": name,
        "product_names": [name] if name else [],
        "visible_text": " ".join(x for x in [brand, name, type] if x),
        "product_type": type,
        "target_area": area or "unknown",
        "confidence": 0.9,
        "clarity": "good",
        "requires_admin_review": False,
    }
    reply = await run_image_matching(phone, ai_data, database.get_user_state(phone))
    return PlainTextResponse(f"Mock AI Data: {ai_data}\n---\n{reply}")


async def send_whatsapp_message(to_number: str, text: str) -> bool:
    log_event("SEND_ATTEMPT", to=to_number)
    if not text:
        log_event("SEND_ERROR", reason="empty_reply")
        return False
    if not META_TOKEN or not PHONE_ID:
        log_event("SEND_ERROR", reason="whatsapp_config_missing")
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


def extract_best_visible_name(text: str) -> str:
    if not text:
        return ""
    ignore_patterns = [
        r"\b\d+\s*(ml|oz|fl\s*oz|g|mg|kg|l)\b",
        r"\b\d+(\.\d+)?\s*(fl\s*)?oz\b",
        r"ingredients",
        r"directions",
        r"for normal skin",
        r"for dry skin",
        r"dermatologist",
        r"made in",
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
    brand = str(ai_data.get("brand", "") or "").strip()
    name = str(ai_data.get("product_name", "") or "").strip()
    visible = str(ai_data.get("visible_text", "") or "").strip()
    product_names = _as_product_names(ai_data.get("product_names", []))
    combined = " ".join([brand, name, visible] + product_names)
    info = matcher.inspect_query(combined)
    return bool(info["detected_brand"] and (info["detected_type"] or matcher.distinctive_tokens(info["clean_query"])))


async def analyze_image_with_ai(base64_img: str) -> Optional[dict]:
    log_event("AI_START", model=AI_MODEL)
    if not AI_KEYS_LIST:
        log_event("AI_ERROR", reason="no_openrouter_keys")
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    prompt_msg = (
        "You are reading a pharmacy product image. Return ONLY valid JSON. "
        "Do not invent stock, price, or product availability. If this is a prescription, set image_type to prescription. "
        "If packaging text is visible, extract the exact brand and product name from the front label.\n\n"
        "{\n"
        '"image_type": "product_packaging|prescription|unclear|other|unknown",\n'
        '"brand": "",\n'
        '"product_name": "",\n'
        '"product_names": [],\n'
        '"visible_text": "",\n'
        '"product_type": "",\n'
        '"target_area": "face|body|baby|hair|mouth|unknown",\n'
        '"size": "",\n'
        '"confidence": 0.0,\n'
        '"clarity": "good|medium|bad",\n'
        '"requires_admin_review": false\n'
        "}"
    )

    for idx, key in enumerate(AI_KEYS_LIST):
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://pricebot-libya.com",
            "X-Title": "PriceBot",
        }
        payload = {
            "model": AI_MODEL,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_msg},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}},
                    ],
                }
            ],
        }
        try:
            response = await http_client.post(url, json=payload, headers=headers, timeout=VISION_TIMEOUT_SECONDS)
            if response.status_code == 400 and "response_format" in response.text.lower():
                payload.pop("response_format", None)
                response = await http_client.post(url, json=payload, headers=headers, timeout=VISION_TIMEOUT_SECONDS)

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                ai_data = extract_robust_json(content)
                log_event("AI_PARSED_JSON", data={k: ai_data.get(k) for k in ["image_type", "brand", "product_name", "product_type", "target_area", "confidence", "clarity"]})
                return ai_data

            log_event("AI_HTTP_STATUS", status=response.status_code, response=response.text[:300])
            if response.status_code in {401, 402, 429} or 500 <= response.status_code <= 599:
                if idx < len(AI_KEYS_LIST) - 1:
                    log_event("AI_RETRY_NEXT_KEY", failed_status=response.status_code)
                    continue
            return None
        except Exception as exc:
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
    visible = extract_best_visible_name(str(ai_data.get("visible_text", "") or ""))
    product_names = _as_product_names(ai_data.get("product_names", []))

    raw_queries = [
        f"{brand} {product_name}".strip(),
        f"{brand} {product_name} {product_type}".strip(),
        f"{brand} {visible}".strip() if visible else "",
        *[f"{brand} {name}".strip() for name in product_names],
        product_name,
        visible,
    ]

    queries = []
    seen = set()
    for raw in raw_queries:
        query = clean_image_query(raw)
        key = matcher.normalize_text(query)
        if len(key) <= 2 or key in seen:
            continue
        seen.add(key)
        queries.append(query)
    return queries


async def run_image_matching(phone: str, ai_data: dict, user_state: dict) -> str:
    image_type = str(ai_data.get("image_type", "unknown") or "unknown").lower()
    clarity = str(ai_data.get("clarity", "") or "").lower()
    try:
        confidence = float(ai_data.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0

    if image_type == "prescription":
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

    if confidence < 0.65 and not visible_text_has_product_signal(ai_data):
        log_event("FINAL_DECISION", decision="low_confidence_unclear", confidence=confidence)
        return matcher.build_unclear_image_reply()

    target_area = str(ai_data.get("target_area", "") or "").strip().lower()
    if target_area in {"unknown", "none", "null"}:
        target_area = ""

    queries = build_image_queries(ai_data)
    log_event("INTERNAL_IMAGE_QUERY", queries=queries)
    if not queries:
        log_event("FINAL_DECISION", decision="no_image_query")
        return matcher.build_unclear_image_reply()

    saw_clear_product_query = False
    for query in queries:
        debug = matcher.inspect_query(query)
        log_event(
            "IMAGE_MATCH_TRY",
            query=query,
            normalized=debug["clean_query"],
            brand=debug["detected_brand"],
            type=debug["detected_type"],
            area=debug["detected_area"],
            result=debug["match_result"],
            product=debug["matched_product"],
        )
        status, item = matcher.safe_match(query)
        if status == "MATCHED" and item:
            if matcher.is_available(item.get("available", "متوفر")):
                database.update_user_state(phone, {"last_product": item})
            else:
                database.clear_user_state(phone)
            log_event("FINAL_DECISION", decision="matched_from_image", product=item.get("name", ""))
            return matcher.build_product_reply(item)
        if status == "UNAVAILABLE":
            saw_clear_product_query = True

    if saw_clear_product_query or visible_text_has_product_signal(ai_data):
        unavailable_query = queries[0]
        log_event("FINAL_DECISION", decision="unavailable_from_image", query=unavailable_query, area=target_area)
        return matcher.build_unavailable_reply(unavailable_query, None, phone, explicit_area=target_area or None)

    log_event("FINAL_DECISION", decision="ambiguous_image")
    return matcher.build_unclear_image_reply()


async def handle_image_logic(phone: str, image_id: str, user_state: dict) -> str:
    if not image_id:
        log_event("MEDIA_DOWNLOAD_ERROR", reason="missing_image_id")
        return matcher.build_unclear_image_reply()
    if not META_TOKEN:
        log_event("MEDIA_DOWNLOAD_ERROR", reason="whatsapp_token_missing")
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
            log_event("MEDIA_DOWNLOAD_ERROR", reason="missing_media_url")
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

    ai_data = await analyze_image_with_ai(b64)
    if not ai_data:
        log_event("FINAL_DECISION", decision="ai_error_fallback")
        return matcher.with_header("تعذر قراءة الصورة حالياً. الرجاء كتابة اسم المنتج كما هو على العلبة.")
    return await run_image_matching(phone, ai_data, user_state)


def classify_reply(reply: str) -> str:
    if "تم تسجيل طلب الحجز" in reply:
        return "order_created"
    if "للحجز اكتب" in reply:
        return "matched"
    if "بدائل متوفرة" in reply:
        return "alternatives"
    if "غير متوفر حالياً في قائمة الصيدلية" in reply:
        return "unavailable"
    if "الصورة غير واضحة" in reply:
        return "unclear_image"
    if "لم أفهم" in reply:
        return "fallback"
    return "reply"


async def process_single_message(phone: str, msg_id: str, msg_type: str, msg: dict) -> None:
    user_state = database.get_user_state(phone)
    final_reply = ""
    final_decision = "fallback"
    order_item_for_notify = None

    try:
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
            debug = matcher.inspect_query(text)
            log_event("SOURCE", value="text")
            log_event("RAW_QUERY", value=text)
            log_event("NORMALIZED_QUERY", value=debug["normalized_query"])
            log_event("DETECTED_BRAND", value=debug["detected_brand"])
            log_event("DETECTED_TYPE", value=debug["detected_type"])
            log_event("DETECTED_AREA", value=debug["detected_area"])
            log_event("MATCH_RESULT", value=debug["match_result"], product=debug["matched_product"])

            if matcher.normalize_text(text) in [matcher.normalize_text(w) for w in matcher.YES_WORDS]:
                order_item_for_notify = user_state.get("last_product")
            final_reply = await asyncio.wait_for(
                asyncio.to_thread(matcher.handle_text_query, phone, text, user_state),
                timeout=TEXT_TIMEOUT_SECONDS,
            )
            final_decision = classify_reply(final_reply)

        elif msg_type == "image":
            log_event("SOURCE", value="image")
            log_event("RAW_QUERY", value="[IMAGE]")
            image_id = msg.get("image", {}).get("id", "")
            await send_whatsapp_message(phone, "جاري فحص الصورة، انتظر لحظات...")
            final_reply = await asyncio.wait_for(
                handle_image_logic(phone, image_id, user_state),
                timeout=IMAGE_TOTAL_TIMEOUT_SECONDS,
            )
            final_decision = classify_reply(final_reply)
        else:
            log_event("SOURCE", value=msg_type)
            final_reply = matcher.with_header("عذراً، أنا أدعم الرسائل النصية والصور فقط.")
            final_decision = "fallback"
    except asyncio.TimeoutError:
        log_event("TIMEOUT_FALLBACK", message_id=msg_id)
        final_reply = matcher.with_header("عذراً، استغرق البحث وقتاً أطول من المتوقع. الرجاء المحاولة مرة أخرى.")
        final_decision = "timeout_fallback"
    except Exception as exc:
        log_event("ERROR_FALLBACK", error=exc)
        final_reply = matcher.with_header("حدث خطأ غير متوقع. الرجاء المحاولة لاحقاً.")
        final_decision = "error_fallback"

    if not final_reply:
        final_reply = matcher.build_fallback_reply()
        final_decision = "fallback"

    log_event("FINAL_DECISION", decision=final_decision)
    send_ok = await send_whatsapp_message(phone, final_reply)
    database.mark_message_done(msg_id, "done" if send_ok else "failed")

    if send_ok and final_decision == "order_created" and order_item_for_notify:
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await notify_admin(
            f"حجز جديد:\n"
            f"الرقم: {phone}\n"
            f"المنتج: {order_item_for_notify.get('name', '')}\n"
            f"السعر: {order_item_for_notify.get('price', '')}\n"
            f"الوقت: {time_str}"
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

                if not database.start_processing_message(msg_id, phone):
                    log_event("MESSAGE_SKIPPED", message_id=msg_id, reason="done_or_processing")
                    continue

                print("\n--- LOG START ---")
                log_event("MESSAGE_ID", value=msg_id)
                lock = get_user_lock(phone)
                async with lock:
                    await process_single_message(phone, msg_id, msg_type, msg)
                print("--- LOG END ---\n")


async def webhook_worker() -> None:
    while True:
        payload = await queue.get()
        try:
            await process_message(payload)
        except Exception as exc:
            log_event("WORKER_ERROR", error=exc)
        finally:
            queue.task_done()


@app.on_event("startup")
async def startup_event():
    print("========================================")
    log_event("STARTING", version="stable-v4-admin")
    log_event("PRODUCTS_COUNT", value=len(database.load_products()))
    matcher.get_product_index()
    log_event("PRODUCT_INDEX_READY", value="YES")
    log_event("AI_MODEL", value=AI_MODEL)
    log_event("AI_KEYS_AVAILABLE", count=len(AI_KEYS_LIST), first=mask_token(AI_KEYS_LIST[0]) if AI_KEYS_LIST else "NONE")
    log_event("PHONE_ID_SET", value="YES" if PHONE_ID else "NO")
    log_event("WHATSAPP_TOKEN_SET", value="YES" if META_TOKEN else "NO")
    log_event("ADMIN_KEY_SET", value="YES" if admin.admin_key_configured() else "NO")
    log_event("WORKERS", value=5, db_path=database.DB_FILE)
    print("========================================")
    for _ in range(5):
        asyncio.create_task(webhook_worker())


@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    payload = await request.json()
    await queue.put(payload)
    return JSONResponse({"ok": True})


@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)
