# RELEASE NOTES — PriceBot V19 Company-Level Ready

## ما الذي تغير من V18 إلى V19

V18 كانت Launch Ready للمحرك والسلوك المحافظ. V19 تضيف طبقة منصة احترافية حول المحرك بدون إعادة كتابة Matching/Vision.

## إضافات V19

- Catalog Quality Gate: `ACCEPT / ACCEPT_WITH_WARNINGS / REJECT`.
- Review Queue للمنتجات الناقصة.
- Duplicate Resolver للأسماء المتكررة.
- Merchant Portal مستقل.
- Super Admin / Multi-merchant foundation.
- اسم الصيدلية dynamic من `.env` أو settings.
- Quality Dashboard.
- Human Learning Center.
- Product Image Library foundation.
- AI usage/cost logs.
- Audit Logs.
- Import Wizard.
- Golden Text Test Runner.
- Real Vision Test Runner.
- Catalog Intelligence Engine V5.
- Deploy V19 بأمر واحد.

## ما لم يتغير

- Matching/Vision المحافظ من V18.
- القرارات الستة فقط:
  - EXACT_MATCH
  - ASK_CLARIFICATION
  - NOT_AVAILABLE
  - COSMETIC_ALTERNATIVES
  - LOW_CONFIDENCE
  - IMAGE_UNCLEAR
- لا سعر عند الغموض.
- لا بدائل دوائية.
- بدائل الكوزمتك فقط نفس النوع والاستخدام.
- invalid vision output يرفض.

## الاختبارات

يجب أن تنجح:

```bash
python -m compileall -q .
python -m pytest -q
python acceptance_tests_v3.py
python acceptance_tests_v4.py
python acceptance_tests_final_v17.py
python acceptance_tests_final_v17_1.py
python acceptance_tests_final_v17_2.py
python acceptance_tests_final_v17_4.py
python acceptance_tests_final_v17_5.py
python acceptance_tests_final_v18.py
python acceptance_tests_final_v19.py
```

## القيود

هذه نسخة Production Pilot احترافية وليست SaaS كامل متعدد الصيدليات. الـ multi-merchant foundation موجود، لكن ربط أرقام WhatsApp متعددة وخطط الاشتراك والفوترة يحتاج مرحلة لاحقة.

يجب اختبار الكتالوج والصور الحقيقية قبل البيع العام الواسع.

## V19.1 Safe Ready update

- Removed the hard-coded merchant pilot code and rejected `merchant` as a valid production login code.
- Merchant Portal now requires `MERCHANT_LOGIN_CODE` and `MERCHANT_PORTAL_ENABLED=true`; if not configured in production it returns 503.
- Added CSRF protection to `/merchant/login`, `/merchant/products/{id}/quick`, `/merchant/settings`, and logout.
- Added merchant login rate limiting and signed expiring merchant sessions.
- Merchant cookie is HttpOnly, SameSite=Lax, max-age 8 hours, and Secure in production/HTTPS.
- Import Wizard now shows total/ready/review/duplicates/reasons and imports ready rows only; review rows go to Review Queue.
- Product Image Library now supports safe image upload, not only manual `image_path` registration.
- Golden/Real Vision test pages are explicitly documented as manual tools, not direct UI API runners.
