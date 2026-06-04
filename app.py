import os
import asyncio
import httpx
import base64
import json
import re
import io
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from dotenv import load_dotenv
from PIL import Image

import database
import matcher
import admin

load_dotenv()

# ==========================================
# (النقطة 2 و 4) قراءة المتغيرات بمرونة
# ==========================================
def get_env_var(possible_names: list, default: str = "") -> str:
    for name in possible_names:
        val = os.getenv(name)
        if val: 
            return str(val).split(",")[0].strip() # أخذ أول مفتاح صالح لو كان هناك عدة مفاتيح
    return default

META_TOKEN = get_env_var(["WHATSAPP_TOKEN", "WHATSAPP_API_TOKEN", "META_TOKEN", "META_ACCESS_TOKEN", "WHATSAPP_PERMANENT_TOKEN"])
PHONE_ID = get_env_var(["PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID_1"])
VERIFY_TOKEN = get_env_var(["VERIFY_TOKEN", "WEBHOOK_VERIFY_TOKEN", "META_VERIFY_TOKEN"], "pricebot_verify_2026")
AI_KEYS = get_env_var(["OPENROUTER_API_KEY", "OPENROUTER_KEYS", "OPENROUTER_KEY", "AI_OPENROUTER_KEYS", "AI_OPENROUTER_KEY"])
AI_MODEL = get_env_var(["OPENROUTER_MODEL"], "google/gemini-2.5-flash-lite")
ADMIN_NOTIFY_PHONE = get_env_var(["ADMIN_NOTIFY_PHONE"])

def mask_token(token: str):
    return f"{token[:4]}...HIDDEN" if token and len(token) > 8 else "NONE"

app = FastAPI(title="PriceBot Pro", version="clean-v1")
app.include_router(admin.router)

http_client = httpx.AsyncClient(timeout=30.0)
queue = asyncio.Queue()

# ==========================================
# Endpoint /health
# ==========================================
@app.get("/health")
async def health_check():
    try: pc = len(database.load_products())
    except: pc = 0
    return JSONResponse({
        "ok": True, "products_count": pc,
        "ai_enabled": bool(AI_KEYS), "whatsapp_configured": bool(META_TOKEN and PHONE_ID),
        "version": "clean-v1"
    })

# ==========================================
# (النقطة 22) إرسال الرسائل مع Logs دقيقة
# ==========================================
async def send_whatsapp_message(to_number: str, text: str):
    print(f"SEND_ATTEMPT to {to_number}")
    if not META_TOKEN or not PHONE_ID:
        print("SEND_ERROR: Missing Meta Tokens")
        return False
        
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_number, "type": "text", "text": {"body": text}}
    
    try:
        res = await http_client.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            print("SEND_OK")
            return True
        else:
            print(f"SEND_ERROR: {res.status_code} - {res.text[:500]}")
            return False
    except Exception as e:
        print(f"SEND_ERROR (Exception): {e}")
        return False

async def notify_admin(message: str):
    if ADMIN_NOTIFY_PHONE:
        await send_whatsapp_message(ADMIN_NOTIFY_PHONE, f"🔔 إشعار للأدمن:\n{message}")

# ==========================================
# معالجة الصور (النقطة 16 و 19 و 21)
# ==========================================
def resize_image_b64(b64_img: str) -> str:
    """تصغير الصورة لتقليل التكلفة وتسريع المعالجة بـ Pillow"""
    try:
        img_data = base64.b64decode(b64_img)
        img = Image.open(io.BytesIO(img_data)).convert("RGB")
        img.thumbnail((1024, 1024))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80)
        return base64.b64encode(out.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"Image Resize Error: {e}")
        return b64_img

def extract_robust_json(text: str) -> dict:
    """استخراج الـ JSON حتى لو أضاف الـ AI نصوصاً قبله أو بعده"""
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match: return json.loads(match.group(0))
        return json.loads(text)
    except:
        return {}

async def download_whatsapp_media(media_id: str):
    print("MEDIA_DOWNLOAD_START")
    url = f"https://graph.facebook.com/v20.0/{media_id}"
    headers = {"Authorization": f"Bearer {META_TOKEN}"}
    try:
        # Timeouts موزونة (6s للرابط + 8s للتحميل)
        res_info = await asyncio.wait_for(http_client.get(url, headers=headers), timeout=6.0)
        media_url = res_info.json().get("url")
        if not media_url: return None
        
        img_res = await asyncio.wait_for(http_client.get(media_url, headers=headers), timeout=8.0)
        print("MEDIA_DOWNLOAD_OK")
        b64 = base64.b64encode(img_res.content).decode("utf-8")
        return resize_image_b64(b64)
    except Exception as e:
        print(f"MEDIA_DOWNLOAD_ERROR: {e}")
        return None

async def analyze_image_with_ai(base64_img: str):
    print("AI_START")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {AI_KEYS}", "Content-Type": "application/json"}
    
    # (النقطة 17) الـ Prompt الدقيق
    prompt_msg = (
        "Analyze this image. Return ONLY JSON format:\n"
        "{\n"
        "\"image_type\": \"product_packaging|prescription|unclear|other\",\n"
        "\"brand\": \"\", \"product_name\": \"\", \"product_names\": [], \"visible_text\": \"\",\n"
        "\"product_type\": \"\", \"target_area\": \"face|body|baby|hair|mouth|unknown\", \"size\": \"\",\n"
        "\"confidence\": 0.0 to 1.0, \"clarity\": \"good|medium|bad\", \"requires_admin_review\": false\n"
        "}"
    )
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_msg}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}]}]
    }
    try:
        # AI Timeout (15s)
        res = await asyncio.wait_for(http_client.post(url, json=payload, headers=headers), timeout=15.0)
        ai_text = res.json()["choices"][0]["message"]["content"]
        ai_data = extract_robust_json(ai_text)
        print(f"AI_PARSED_JSON: {ai_data}")
        return ai_data
    except Exception as e:
        print(f"AI_ERROR: {e}")
        return None

# ==========================================
# معالجة الرسائل الرئيسية (النقطة 31)
# ==========================================
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
                
                # (النقطة 23) منع التكرار 
                if database.is_message_processed(msg_id):
                    print(f"Duplicate message ignored: {msg_id}")
                    continue
                
                print(f"\n--- LOG START ---\nMESSAGE_ID: {msg_id}\nSOURCE: WhatsApp")
                user_state = database.get_user_state(phone)
                final_reply = ""
                
                try:
                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")
                        print(f"RAW_QUERY: {text}")
                        q_norm = matcher.normalize_text(text)
                        print(f"NORMALIZED_QUERY: {q_norm}")
                        
                        final_reply = matcher.handle_text_query(phone, text, user_state)
                        
                    elif msg_type == "image":
                        image_id = msg.get("image", {}).get("id", "")
                        print("RAW_QUERY: [IMAGE]")
                        await send_whatsapp_message(phone, "جاري فحص الصورة، انتظر لحظات...")
                        
                        async def handle_image():
                            b64 = await download_whatsapp_media(image_id)
                            if not b64: return "فشل تحميل الصورة من الواتساب. الرجاء كتابة اسم المنتج."
                            
                            ai_data = await analyze_image_with_ai(b64)
                            if not ai_data: return "حدث خطأ أثناء فحص الصورة بالذكاء الاصطناعي. الرجاء كتابة الاسم."
                            
                            # (النقطة 30) التعامل مع الروشتة
                            if ai_data.get("image_type") == "prescription":
                                await notify_admin(f"روشتة جديدة من الرقم: {phone}")
                                return "الصورة تبدو كوصفة طبية (روشتة). تم تحويلها للصيدلي للمراجعة وسيتم الرد عليك قريباً."
                            
                            # (النقطة 18) فحص الثقة
                            conf = float(ai_data.get("confidence", 0.0))
                            if conf < 0.65 or ai_data.get("clarity") == "bad":
                                return matcher.build_unclear_image_reply()
                                
                            # (النقطة 20) بناء استعلام داخلي شامل
                            p_name = ai_data.get("product_name") or ai_data.get("visible_text", "")
                            parts = [ai_data.get("brand", ""), p_name, ai_data.get("product_type", ""), ai_data.get("target_area", ""), ai_data.get("size", "")]
                            internal_query = " ".join([p for p in parts if p]).strip()
                            print(f"INTERNAL_IMAGE_QUERY: {internal_query}")
                            
                            if not internal_query or len(internal_query) < 3: 
                                return "لم أتمكن من استخراج اسم واضح للمنتج. الرجاء كتابة اسمه."
                                
                            return matcher.handle_text_query(phone, internal_query, user_state)
                            
                        # Total Image Timeout (25s)
                        final_reply = await asyncio.wait_for(handle_image(), timeout=25.0)
                    else:
                        final_reply = "عذراً، أنا أدعم الرسائل النصية والصور فقط."
                        
                except asyncio.TimeoutError:
                    print("TIMEOUT_FALLBACK")
                    final_reply = "عذراً، استغرق البحث وقتاً أطول من المتوقع. الرجاء المحاولة مرة أخرى لاحقاً."
                except Exception as e:
                    print(f"ERROR_FALLBACK: {e}")
                    final_reply = "حدث خطأ غير متوقع. الرجاء المحاولة لاحقاً."

                # إرسال الرد النهائي وإشعار الأدمن إذا كان هناك حجز
                print("FINAL_DECISION: Ready to send reply")
                await send_whatsapp_message(phone, final_reply)
                
                # إشعار الأدمن عند تسجيل حجز جديد
                if "تم تسجيل طلب الحجز" in final_reply:
                    await notify_admin(f"حجز جديد من الرقم: {phone}")
                    
                print("--- LOG END ---\n")

async def webhook_worker():
    while True:
        payload = await queue.get()
        try: await process_message(payload)
        except Exception as e: print(f"Worker Error: {e}")
        finally: queue.task_done()

@app.on_event("startup")
async def startup_event():
    print(f"Starting PriceBot Pro... META_TOKEN masked: {mask_token(META_TOKEN)}")
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
