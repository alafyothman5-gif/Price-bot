import os
import asyncio
import httpx
import base64
import json
import re
import io
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from dotenv import load_dotenv
from PIL import Image

import database
import matcher
import admin

load_dotenv()

def get_valid_keys_list(possible_names: list) -> list:
    keys = []
    for name in possible_names:
        val = os.getenv(name, "")
        if val:
            parts = re.split(r'\|\||\||,|\s|\n|;', val)
            for p in parts:
                p = p.strip()
                if (p.startswith("sk-or") or p.startswith("sk")) and p not in keys: 
                    keys.append(p)
    return keys

def get_env_var(possible_names: list, default: str = "") -> str:
    for name in possible_names:
        val = os.getenv(name)
        if val: return str(val).strip()
    return default

META_TOKEN = get_env_var([
    "WHATSAPP_TOKEN", "WHATSAPP_API_TOKEN", "META_TOKEN", "META_ACCESS_TOKEN", 
    "WHATSAPP_PERMANENT_TOKEN", "WHATSAPP_ACCESS_TOKEN", "WA_ACCESS_TOKEN", 
    "WA_TOKEN", "META_WHATSAPP_TOKEN", "META_WHATSAPP_ACCESS_TOKEN", 
    "FACEBOOK_ACCESS_TOKEN", "ACCESS_TOKEN", "GRAPH_API_TOKEN", "CLOUD_API_TOKEN"
])
PHONE_ID = get_env_var([
    "PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID", 
    "META_PHONE_NUMBER_ID_1", "WA_PHONE_NUMBER_ID"
])
VERIFY_TOKEN = get_env_var(["VERIFY_TOKEN", "WEBHOOK_VERIFY_TOKEN", "META_VERIFY_TOKEN"], "pricebot_verify_2026")
AI_KEYS_LIST = get_valid_keys_list(["OPENROUTER_API_KEY", "OPENROUTER_KEYS", "OPENROUTER_KEY", "AI_OPENROUTER_KEYS", "AI_OPENROUTER_KEY"])
AI_MODEL = get_env_var(["OPENROUTER_MODEL", "AI_MODEL", "AI_OPENROUTER_MODEL"], "google/gemini-2.5-flash-lite")

ADMIN_NOTIFY_PHONE = re.sub(r"\D", "", get_env_var(["ADMIN_NOTIFY_PHONE"]))

def mask_token(token: str):
    return f"{token[:4]}...HIDDEN" if token and len(token) > 8 else "NONE"

app = FastAPI(title="PriceBot Pro", version="stable-v1")
app.include_router(admin.router)

http_client = httpx.AsyncClient(timeout=30.0)
queue = asyncio.Queue()

user_locks = {}
def get_user_lock(phone: str):
    if phone not in user_locks: user_locks[phone] = asyncio.Lock()
    return user_locks[phone]

@app.get("/health")
async def health_check():
    try: pc = len(database.load_products())
    except: pc = 0
    return JSONResponse({"ok": True, "products_count": pc, "ai_enabled": bool(AI_KEYS_LIST), "whatsapp_configured": bool(META_TOKEN and PHONE_ID), "version": "stable-v1"})

@app.get("/test_local")
async def test_local(q: str = "", phone: str = "test_user"):
    user_state = database.get_user_state(phone)
    reply = matcher.handle_text_query(phone, q, user_state)
    return PlainTextResponse(f"Query: {q}\n---\n{reply}")

@app.get("/test_local_image")
async def test_local_image(brand: str = "", name: str = "", type: str = "", area: str = "", phone: str = "test_user"):
    ai_data = {"brand": brand, "product_name": name, "product_type": type, "target_area": area, "confidence": 0.9, "clarity": "good", "image_type": "product_packaging"}
    reply = await run_image_matching(phone, ai_data, database.get_user_state(phone))
    return PlainTextResponse(f"Mock AI Data: {ai_data}\n---\n{reply}")

async def send_whatsapp_message(to_number: str, text: str) -> bool:
    print(f"SEND_ATTEMPT to {to_number}")
    if not META_TOKEN or not PHONE_ID: return False
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_number, "type": "text", "text": {"body": text}}
    try:
        res = await http_client.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            print("SEND_OK")
            return True
        print(f"SEND_ERROR: {res.status_code} | {res.text[:300]}")
        return False
    except Exception as e:
        print(f"SEND_ERROR (Exception): {e}")
        return False

async def notify_admin(message: str):
    if ADMIN_NOTIFY_PHONE:
        await send_whatsapp_message(ADMIN_NOTIFY_PHONE, f"🔔 إشعار للصيدلية:\n{message}")

def resize_image_b64(b64_img: str) -> str:
    try:
        img_data = base64.b64decode(b64_img)
        img = Image.open(io.BytesIO(img_data)).convert("RGB")
        img.thumbnail((1024, 1024))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80)
        return base64.b64encode(out.getvalue()).decode("utf-8")
    except: return b64_img

def extract_best_visible_name(text: str) -> str:
    if not text: return ""
    lines = text.split('\n')
    ignore_patterns = [r'\d+\s*(ml|oz|fl\s*oz|g|mg)', 'for normal skin', 'ingredients', 'claims']
    good_lines = []
    
    for line in lines:
        line_lower = line.lower()
        if any(re.search(pat, line_lower) for pat in ignore_patterns): continue
        good_lines.append(line.strip())
        
    if len(good_lines) >= 2: return " ".join(good_lines[:2])
    return good_lines[0] if good_lines else ""

def extract_robust_json(text: str) -> dict:
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match: return json.loads(match.group(0))
        return json.loads(text)
    except: return {}

async def analyze_image_with_ai(base64_img: str):
    print("AI_START")
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    prompt_msg = (
        "Analyze this image carefully. Return ONLY valid JSON format:\n"
        "{\n"
        "\"image_type\": \"product_packaging|prescription|unclear|other\",\n"
        "\"brand\": \"\", \"product_name\": \"\", \"visible_text\": \"\",\n"
        "\"product_type\": \"\", \"target_area\": \"face|body|baby|hair|mouth|unknown\", \"size\": \"\",\n"
        "\"confidence\": 0.9,\n"
        "\"clarity\": \"good|medium|bad\",\n"
        "\"requires_admin_review\": false\n"
        "}"
    )
    
    for idx, key in enumerate(AI_KEYS_LIST):
        # إضافة الهيدرات المطلوبة لـ OpenRouter
        headers = {
            "Authorization": f"Bearer {key}", 
            "Content-Type": "application/json",
            "HTTP-Referer": "https://pricebot-libya.com",
            "X-Title": "PriceBot Pro"
        }
        payload = {"model": AI_MODEL, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_msg}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}]}]}
        
        try:
            res = await http_client.post(url, json=payload, headers=headers)
            
            if res.status_code == 400 and "response_format" in res.text.lower():
                del payload["response_format"]
                res = await http_client.post(url, json=payload, headers=headers)
                
            if res.status_code == 200:
                ai_text = res.json()["choices"][0]["message"]["content"]
                ai_data = extract_robust_json(ai_text)
                print(f"AI_MODEL_USED: {AI_MODEL} | AI_PARSED_JSON: {ai_data}")
                return ai_data
            else:
                print(f"AI_HTTP_STATUS: {res.status_code} | MODEL: {AI_MODEL} | RESPONSE: {res.text[:300]}")
                # تضمين 500 في حالات الفشل لإعادة المحاولة
                if res.status_code in [401, 402, 429, 500, 502, 503] and idx < len(AI_KEYS_LIST) - 1:
                    print(f"Switching to next AI key...")
                    continue
                return None
                
        except Exception as e:
            print(f"AI_ERROR: {e}")
            if idx < len(AI_KEYS_LIST) - 1: continue
            return None
    return None

async def run_image_matching(phone: str, ai_data: dict, user_state: dict) -> str:
    img_type = ai_data.get("image_type", "")
    if img_type in ["prescription", "prescription_or_unclear"]:
        await notify_admin(f"روشتة طبية من الرقم:\n{phone}")
        return "الصورة تبدو كوصفة طبية (روشتة). تم تحويلها للصيدلي للمراجعة وسيتم الرد عليك قريباً."
    
    if ai_data.get("requires_admin_review"):
        await notify_admin(f"مراجعة مطلوبة لمنتج من الرقم:\n{phone}")
        return "تم استلام الصورة وسيتم مراجعتها من قبل الصيدلي للرد عليك قريباً."

    conf = float(ai_data.get("confidence", 0.0))
    if conf < 0.65 or ai_data.get("clarity", "").lower() == "bad" or img_type in ["unclear", "other", "unknown"]:
        return matcher.build_unclear_image_reply()
        
    brand = str(ai_data.get("brand", "")).strip()
    name = str(ai_data.get("product_name", "")).strip()
    p_type = str(ai_data.get("product_type", "")).strip()
    target_area = str(ai_data.get("target_area", "")).strip()
    if target_area.lower() in ["unknown", "none", "null", ""]:
        target_area = ""
    best_visible = extract_best_visible_name(ai_data.get("visible_text", ""))
    
    # Try several safe query forms. Size/area/type should help alternatives, not block exact matching.
    queries_to_try = [
        f"{brand} {name}".strip(),
        f"{brand} {name} {p_type}".strip(),
        f"{brand} {name} {p_type} {target_area}".strip(),
        f"{brand} {best_visible}".strip() if best_visible else "",
        f"{name} {p_type}".strip(),
        name,
    ]
    seen_q = set()
    valid_queries = []
    for q in queries_to_try:
        q = " ".join(str(q or "").split())
        if len(q) > 2 and q.lower() not in seen_q:
            seen_q.add(q.lower())
            valid_queries.append(q)
    
    for q in valid_queries:
        status, item = matcher.safe_match(matcher.clean_query(q))
        if status == "MATCHED" and item:
            if matcher.is_available(item.get("available", "متوفر")):
                database.update_user_state(phone, {"last_product": item})
            else: database.clear_user_state(phone)
            return matcher.build_product_reply(item)
            
    if not valid_queries:
        return "لم أتمكن من استخراج اسم واضح للمنتج. الرجاء كتابة اسمه."

    unavailable_query = " ".join(x for x in [brand, name or best_visible, p_type, target_area] if x).strip() or valid_queries[0]
    return matcher.build_unavailable_reply(unavailable_query, None, phone, explicit_area=target_area or None)

async def handle_image_logic(phone: str, image_id: str, user_state: dict) -> str:
    url = f"https://graph.facebook.com/v20.0/{image_id}"
    headers = {"Authorization": f"Bearer {META_TOKEN}"}
    try:
        res_info = await http_client.get(url, headers=headers)
        media_url = res_info.json().get("url")
        if not media_url: return "فشل تحميل الصورة من الواتساب. الرجاء كتابة اسم المنتج."
        
        img_res = await http_client.get(media_url, headers=headers)
        b64 = resize_image_b64(base64.b64encode(img_res.content).decode("utf-8"))
    except Exception as e:
        print(f"MEDIA_DOWNLOAD_ERROR: {e}")
        return "فشل تحميل الصورة من الواتساب. الرجاء كتابة اسم المنتج."
        
    ai_data = await analyze_image_with_ai(b64)
    if not ai_data: return "حدث خطأ في السيرفر أثناء قراءة الصورة. الرجاء كتابة اسم المنتج يدوياً."
    
    return await run_image_matching(phone, ai_data, user_state)

async def process_message(payload: dict):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "statuses" in value: continue
            
            for msg in value.get("messages", []):
                phone = msg.get("from")
                msg_id = msg.get("id")
                msg_type = msg.get("type")
                if not phone or not msg_id: continue
                
                if not database.start_processing_message(msg_id, phone):
                    print(f"Message {msg_id} is processing or done. Ignored.")
                    continue
                
                print(f"\n--- LOG START ---\nMESSAGE_ID: {msg_id}\nSOURCE: WhatsApp")
                
                lock = get_user_lock(phone)
                async with lock:
                    user_state = database.get_user_state(phone)
                    final_reply = ""
                    send_status = False
                    
                    try:
                        if msg_type == "text":
                            text = msg.get("text", {}).get("body", "")
                            print(f"RAW_QUERY: {text}\nNORMALIZED: {matcher.normalize_text(text)}")
                            final_reply = matcher.handle_text_query(phone, text, user_state)
                            
                        elif msg_type == "image":
                            image_id = msg.get("image", {}).get("id", "")
                            print("RAW_QUERY: [IMAGE]")
                            await send_whatsapp_message(phone, "جاري فحص الصورة، انتظر لحظات...")
                            final_reply = await asyncio.wait_for(handle_image_logic(phone, image_id, user_state), timeout=25.0)
                        else:
                            final_reply = "عذراً، أنا أدعم الرسائل النصية والصور فقط."
                            
                    except asyncio.TimeoutError:
                        print("TIMEOUT_FALLBACK")
                        final_reply = "عذراً، استغرق البحث وقتاً أطول من المتوقع. الرجاء المحاولة مرة أخرى."
                    except Exception as e:
                        print(f"ERROR_FALLBACK: {e}")
                        final_reply = "حدث خطأ غير متوقع. الرجاء المحاولة لاحقاً."

                    print(f"FINAL_DECISION: Ready to send reply")
                    send_status = await send_whatsapp_message(phone, final_reply)
                    database.mark_message_done(msg_id, "done" if send_status else "failed")
                    
                    if "تم تسجيل طلب الحجز للمنتج" in final_reply:
                        item = database.get_user_state(phone).get("last_product", {})
                        if not item:
                            orders = database.get_all_orders()
                            if orders: item = {"name": orders[0]["product_name"], "price": orders[0]["price"]}
                        time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        await notify_admin(f"🛒 حجز جديد:\n📞 الرقم: {phone}\n📦 المنتج: {item.get('name', '')}\n💰 السعر: {item.get('price', '')}\n⏰ الوقت: {time_str}")
                        
                    print("--- LOG END ---\n")

async def webhook_worker():
    while True:
        payload = await queue.get()
        try: await process_message(payload)
        except Exception as e: print(f"Worker Error: {e}")
        finally: queue.task_done()

@app.on_event("startup")
async def startup_event():
    print("========================================")
    print(f"🚀 STARTING PriceBot Pro (VERSION: stable-v1)")
    print(f"📦 Products Count: {len(database.load_products())}")
    print(f"🧠 AI Model: {AI_MODEL}")
    print(f"🔑 AI Keys Available: {len(AI_KEYS_LIST)} (First Key: {mask_token(AI_KEYS_LIST[0]) if AI_KEYS_LIST else 'NONE'})")
    print(f"📱 Phone ID Set: {'YES' if PHONE_ID else 'NO'}")
    print(f"📲 WhatsApp Token Set: {'YES' if META_TOKEN else 'NO'}")
    print(f"🛡️ Admin Key Set: {'YES' if os.getenv('ADMIN_KEY') or os.getenv('PRICEBOT_ADMIN_KEY') else 'NO (Using Default)'}")
    print(f"⚙️ Workers: 5 | DB Path: {database.DB_FILE}")
    print("========================================")
    for _ in range(5): asyncio.create_task(webhook_worker())

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
