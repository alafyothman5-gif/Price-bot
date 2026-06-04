import os
import asyncio
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from dotenv import load_dotenv

# استدعاء ملف قاعدة البيانات (سنقوم ببرمجته في الخطوة القادمة)
import database 

# تحميل المتغيرات من ملف .env الحالي بدون تغييره
load_dotenv()

# 4) دالة ذكية لقراءة المتغيرات أياً كان اسمها في .env
def get_env_var(possible_names: list, default: str = "") -> str:
    for name in possible_names:
        val = os.getenv(name)
        if val:
            return val
    return default

# سحب التوكنات بجميع مسمياتها المحتملة
META_TOKEN = get_env_var(["WHATSAPP_TOKEN", "WHATSAPP_API_TOKEN", "META_TOKEN", "META_ACCESS_TOKEN", "WHATSAPP_PERMANENT_TOKEN"])
PHONE_ID = get_env_var(["PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID", "META_PHONE_NUMBER_ID_1"])
VERIFY_TOKEN = get_env_var(["VERIFY_TOKEN", "WEBHOOK_VERIFY_TOKEN", "META_VERIFY_TOKEN"], "pricebot_verify_2026")

# 1) توحيد ملف التشغيل (هذا الملف اسمه app.py)
app = FastAPI(title="PriceBot Pro", version="clean-v1")

# 2) إضافة endpoint /health لفحص حالة السيرفر
@app.get("/health")
async def health_check():
    try:
        products = database.load_products()
        products_count = len(products)
    except Exception:
        products_count = 0
        
    ai_keys = get_env_var(["OPENROUTER_API_KEY", "OPENROUTER_KEYS"])
    
    return JSONResponse({
        "ok": True,
        "products_count": products_count,
        "ai_enabled": bool(ai_keys),
        "whatsapp_configured": bool(META_TOKEN and PHONE_ID),
        "version": "clean-v1"
    })

# 3) الحفاظ على نفس webhook (GET للتوثيق)
@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)

# 3) الحفاظ على نفس webhook (POST لاستقبال الرسائل)
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    payload = await request.json()
    
    # هنا سنضيف لاحقاً نظام الطوابير (Queue) لمعالجة الرسائل
    # سنقوم ببرمجته عندما نصل لخطوة (الرد النهائي و timeout)
    
    return JSONResponse({"ok": True})
