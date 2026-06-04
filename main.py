import os
import asyncio
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

# استدعاء ملفاتنا الجديدة
import database
import matcher
import admin

app = FastAPI(title="PriceBot Pro V5", version="5.0")

# 🔗 تفعيل لوحة التحكم (الدخول عبر الرابط /admin)
app.include_router(admin.router)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "pricebot_verify_2026")
META_TOKEN = os.getenv("WHATSAPP_TOKEN", os.getenv("WHATSAPP_ACCESS_TOKEN", ""))
PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

http_client = httpx.AsyncClient(timeout=20.0)
queue = asyncio.Queue()

async def send_whatsapp_message(to_number: str, text: str):
    """دالة إرسال الرسائل السريعة لميتا"""
    if not META_TOKEN or not PHONE_ID:
        print("تنبيه: التوكن أو رقم الهاتف غير موجود في إعدادات البيئة")
        return
        
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    try:
        await http_client.post(url, json=payload, headers=headers)
    except Exception as e:
        print(f"خطأ في الإرسال: {e}")

async def process_message(payload: dict):
    """المعالجة الخلفية الآمنة التي لا تعطل السيرفر"""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "statuses" in value:
                continue # تجاهل إشعارات (تم الاستلام/تمت القراءة)
                
            for msg in value.get("messages", []):
                phone = msg.get("from")
                if not phone:
                    continue
                
                # سحب ذاكرة المحادثة للزبون
                user_state = database.get_user_state(phone)
                
                if msg.get("type") == "text":
                    text = msg.get("text", {}).get("body", "")
                    
                    # 🧠 تمرير النص لملف matcher للبحث وتوليد الرد المناسب
                    reply_text = matcher.handle_text_query(phone, text, user_state)
                    
                    # إرسال النتيجة للواتساب
                    await send_whatsapp_message(phone, reply_text)

async def webhook_worker():
    """عامل الطابور الذي ينظم الزحام"""
    while True:
        payload = await queue.get()
        try:
            await process_message(payload)
        except Exception as e:
            print(f"خطأ في المعالجة: {e}")
        finally:
            queue.task_done()

@app.on_event("startup")
async def startup_event():
    # تشغيل 5 عمال لضمان عدم تأخر الردود مهما كان الضغط
    for _ in range(5):
        asyncio.create_task(webhook_worker())

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """استلام الرسالة ووضعها في الطابور بسرعة البرق"""
    payload = await request.json()
    await queue.put(payload)
    return JSONResponse({"ok": True})

@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    """توثيق الويب هوك مع منصة ميتا للمطورين"""
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("مرفوض", status_code=403)
