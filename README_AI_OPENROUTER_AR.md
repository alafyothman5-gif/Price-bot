# إعداد OpenRouter في PriceBot

هذه النسخة تنظف كل مفاتيح AI القديمة أثناء النشر، ثم تستخدم OpenRouter فقط.

## بعد رفع الملفات إلى GitHub وتشغيل النشر

شغل من السيرفر:

```bash
sudo /opt/pricebot/SET_OPENROUTER_KEY.sh
```

سيطلب منك المفتاح بشكل مخفي. الصق مفتاح OpenRouter الذي يبدأ بـ:

```text
sk-or-v1-
```

ثم سيقوم السكربت تلقائياً بـ:

- حفظ المفتاح في `/opt/pricebot/.env`
- ضبط `AI_PROVIDER_ORDER=openrouter`
- ضبط الموديل `google/gemini-2.0-flash-001`
- حذف Gemini/Groq/OpenAI keys القديمة
- إعادة تشغيل البوت
- اختبار OpenRouter من السيرفر

## فحص لاحق

```bash
sudo /opt/pricebot/CHECK_OPENROUTER_KEY.sh
```

النتيجة المطلوبة:

```text
RESULT: OPENROUTER_WORKING
```
