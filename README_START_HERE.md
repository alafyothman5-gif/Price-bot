# PriceBot GitHub Ready

هذه النسخة تحتوي على آخر تعديلات:

- Pagination + Search للمنتجات.
- رفع Excel متعدد الصفحات بأمان.
- منع مشكلة استيراد 30 منتج بدل 4991.
- Safe Image/Text Match: لا يعطي منتج غلط عند الشك.
- تجهيز OpenRouter فقط للـ AI.
- تنظيف مفاتيح Gemini/Groq/OpenAI/OpenRouter القديمة أثناء النشر.
- سكربت منفصل يطلب OpenRouter key من السيرفر بدون طباعته.

بعد رفع الملفات إلى GitHub، شغل أمر النشر من السيرفر، ثم:

```bash
sudo /opt/pricebot/SET_OPENROUTER_KEY.sh
```
