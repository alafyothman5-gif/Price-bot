import os
import asyncio
import httpx
import base64
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from dotenv import load_dotenv

import database
import matcher
import admin

load_dotenv()

# --- قراءة المتغيرات بشكل مرن (النقطة 4) ---
def get_env_var(possible_names: list, default: str = "") -> str:
    for name in possible_names:
        val = os.getenv(name)
        if val: return val
    return default

META_TOKEN = get_env_var(["WHATSAPP_TOKEN", "WHATSAPP_API_TOKEN", "META_TOKEN", "META_ACCESS_TOKEN", "WHATSAPP_PERMANENT_TOKEN"])
PHONE_ID = get_env_var(["PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID_1"])
VERIFY_TOKEN = get_env_var(["VERIFY_TOKEN", "WEBHOOK_VERIFY_TOKEN", "META_VERIFY_TOKEN"], "pricebot_verify_2026")
AI_KEYS = get_env_var(["OPENROUTER_API_KEY", "OPENROUTER_KEYS"])
AI_MODEL = get_env_var(["OPENROUTER_MODEL"], "google/gemini-2.5-flash-lite")

# --- (النقطة 18) حماية الأسرار في الـ Logs ---
def mask_token(token: str):
    return f"{token[:4]}...HIDDEN" if token and len(token) > 8 else "NONE"

app = FastAPI(title="PriceBot Pro", version="clean-v1")
app.include_router(admin.router) # (النقطة 5) لوحة التحكم المحمية

http_client = httpx.AsyncClient(timeout=20.0)
queue = asyncio.Queue()

# --- (النقطة 2) Endpoint /health ---
@app.get("/health")
async def health_check():
    try:
        products = database.load_products()
        pc = len(products)
    except: pc = 0
    return JSONResponse({
        "ok": True, "products_count": pc,
        "ai_enabled": bool(AI_KEYS), "whatsapp_configured": bool(META_TOKEN and PHONE_ID),
        "version": "clean-v1"
    })

async def send_whatsapp_message(to_number: str, text: str):
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_number, "type": "text", "text": {"body": text}}
    try:
        res = await http_client.post(url, json=payload, headers=headers)
        return res.status_code == 200
    except: return False

# --- (النقطة 9) تحميل الصورة بأمان (Timeout 8s) ---
async def download_whatsapp_media(media_id: str):
    print("MEDIA_DOWNLOAD_START")
    url = f"https://graph.facebook.com/v20.0/{media_id}"
    headers = {"Authorization": f"Bearer {META_TOKEN}"}
    try:
        res = await asyncio.wait_for(http_client.get(url, headers=headers), timeout=8.0)
        media_url = res.json().get("url")
        if not media_url: return None
        
        img_res = await asyncio.wait_for(http_client.get(media_url, headers=headers), timeout=8.0)
        print("MEDIA_DOWNLOAD_OK")
        return base64.b64encode(img_res.content).decode("utf-8")
    except asyncio.TimeoutError:
        print("MEDIA_DOWNLOAD_TIMEOUT")
        return None
    except Exception as e:
        print(f"MEDIA_DOWNLOAD_ERROR: {e}")
        return None

# --- (النقطة 10) تحليل الصورة وإخراج JSON ---
async def analyze_image_with_ai(base64_img: str):
    print("AI_START")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {AI_KEYS}", "Content-Type": "application/json"}
    payload = {
        "model": AI_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Analyze this pharmacy product image. Return JSON ONLY with keys: brand, product_name, product_type (e.g. cleanser, lotion), target_area, size, confidence (High/Low), clarity (Clear/Unclear). Do NOT make up info."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
            ]
        }]
    }
    try:
        res = await asyncio.wait_for(http_client.post(url, json=payload, headers=headers), timeout=8.0)
        ai_text = res.json()["choices"][0]["message"]["content"]
        ai_data = json.loads(ai_text)
        print(f"AI_PARSED_JSON: {ai_data}")
        return ai_data
    except Exception as e:
        print(f"AI_ERROR: {e}")
        return None

# --- المعالجة الخلفية واللوج (النقاط 11, 12, 16) ---
async def process_message(payload: dict):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "statuses" in value: continue
            
            for msg in value.get("messages", []):
                phone = msg.get("from")
                msg_id = msg.get("id")
                msg_type = msg.get("type")
                if not phone: continue
                
                print(f"\n--- LOG START ---\nMESSAGE_ID: {msg_id}\nSOURCE: WhatsApp")
                user_state = database.get_user_state(phone)
                final_reply = ""
                
                try:
                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")
                        print(f"RAW_QUERY: {text}")
                        # Timeout للنص: 5 ثواني
                        final_reply = await asyncio.wait_for(
                            asyncio.to_thread(matcher.handle_text_query, phone, text, user_state), 
                            timeout=5.0
                        )
                        
                    elif msg_type == "image":
                        image_id = msg.get("image", {}).get("id", "")
                        print("RAW_QUERY: [IMAGE]")
                        
                        await send_whatsapp_message(phone, "جاري فحص الصورة، انتظر لحظات...")
                        
                        async def handle_image():
                            b64 = await download_whatsapp_media(image_id)
                            if not b64: return "فشل تحميل الصورة من الواتساب. الرجاء المحاولة لاحقاً أو كتابة الاسم."
                            
                            ai_data = await analyze_image_with_ai(b64)
                            if not ai_data: return "حدث خطأ أثناء فحص الصورة. الرجاء كتابة اسم المنتج."
                            
                            if ai_data.get("clarity", "").lower() == "unclear":
                                return matcher.build_unclear_image_reply()
                                
                            internal_query = f"{ai_data.get('brand', '')} {ai_data.get('product_name', '')} {ai_data.get('product_type', '')}".strip()
                            print(f"INTERNAL_IMAGE_QUERY: {internal_query}")
                            
                            if not internal_query: return "لم أتمكن من التعرف على المنتج بوضوح. الرجاء كتابة اسمه."
                            return matcher.handle_text_query(phone, internal_query, user_state)
                            
                        # Timeout للصورة: 20 ثانية كحد أقصى
                        final_reply = await asyncio.wait_for(handle_image(), timeout=20.0)
                    else:
                        final_reply = "عذراً، أنا أدعم الرسائل النصية والصور فقط."
                        
                except asyncio.TimeoutError:
                    print("TIMEOUT_FALLBACK")
                    final_reply = "عذراً، استغرق البحث وقتاً أطول من المتوقع. الرجاء المحاولة مرة أخرى."
                except Exception as e:
                    print(f"ERROR_FALLBACK: {e}")
                    final_reply = "حدث خطأ غير متوقع. الرجاء المحاولة لاحقاً."

                # ضمان إرسال الرد النهائي
                print(f"FINAL_DECISION: Ready to send reply")
                send_status = await send_whatsapp_message(phone, final_reply)
                print("SEND_OK" if send_status else "SEND_ERROR")
                print("--- LOG END ---\n")

async def webhook_worker():
    while True:
        payload = await queue.get()
        try: await process_message(payload)
        except Exception as e: print(f"Worker Error: {e}")
        finally: queue.task_done()

@app.on_event("startup")
async def startup_event():
    print(f"Starting... META_TOKEN masked: {mask_token(META_TOKEN)}")
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
