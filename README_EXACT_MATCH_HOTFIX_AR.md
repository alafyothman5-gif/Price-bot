# PriceBot Exact Match Hotfix

هذه النسخة تصلح الخطأ الخطير:

- إذا المنتج موجود في القاعدة لا يقول عنه غير متوفر.
- إذا المنتج موجود لا يظهر كبديل لنفسه.
- البحث النصي يبدأ بالتطابق exact name / alias قبل fuzzy matching.
- يحافظ على المنتجات وقاعدة البيانات ومفتاح OpenRouter.

اختبار مهم بعد النشر:

1. اكتب: Cerave moisturising lotion Baume
2. يجب أن يرد بتوفر المنتج وسعره، لا يقول غير متوفر.
3. جرّب صورة CeraVe Lotion.
4. جرّب CeraVe Hydrating Cleanser إذا غير موجود، يجب أن يقول غير متوفر ويعرض بدائل cleanser فقط إن وجدت.
