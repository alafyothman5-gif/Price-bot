# PriceBot Safe Excel Upload

هذا الإصدار يضيف حماية رفع ملفات المنتجات:

- قراءة Excel متعدد الصفحات xlsx/xls.
- تجاهل صفحات Summary و Converter_Rules.
- دعم صفحة Products_Bot_Ready و Needs_Review.
- دعم أعمدة الملف المنظم مثل canonical_name و form_or_type و final_price و image_ocr_keywords.
- منع استبدال قاعدة منتجات كبيرة بملف صغير بالخطأ، مثل مشكلة 4991 -> 30.
- دعم خيار تأكيد إجباري عند الحاجة.

لا يحتوي هذا الملف على قاعدة البيانات أو المنتجات أو التوكنات.
