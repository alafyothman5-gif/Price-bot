PriceBot stable-v1

هذه نسخة مستقرة مبنية على Price-bot-main (6) مع:
- إصلاحات توافق قاعدة البيانات القديمة: state_json, value_json, phone, processed_messages, orders.
- ملف تشغيل start_pricebot.sh حتى لا يتكرر خطأ 203/EXEC.
- تحسين المطابقة للنصوص العربية/الإنجليزية.
- دعم أسماء مثل بانادول/بنادول، CeraVe، لا روش، غسول وجه، وغيرها.
- منع اختيار منتج عشوائي عند CeraVe فقط أو cleanser فقط.
- تحسين بدائل الكوزمتك بحيث لا يعطي body wash / mouth wash / baby wash كبديل لغسول وجه.
- الحفاظ على .env وقاعدة البيانات ولا يحتاج تغيير Meta.
