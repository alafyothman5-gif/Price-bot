# PriceBot V19 Company-Level Ready — نشر سريع

## 1) مكان المشروع
ضع ملفات المشروع داخل:

```bash
/opt/pricebot
```

لا تلمس `/opt/medmcq` ولا أي خدمة Telegram.

## 2) إعداد الأسرار
انسخ الملف:

```bash
cp .env.example .env
nano .env
```

املأ القيم الحقيقية فقط داخل `.env`، ولا ترفع هذا الملف إلى GitHub.

الأهم:

- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`
- `META_VERIFY_TOKEN`
- `META_APP_SECRET`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `OPENROUTER_API_KEY`
- `PHARMACY_NAME`
- `BOT_WHATSAPP_NUMBER`

## 3) النشر بأمر واحد
من داخل `/opt/pricebot`:

```bash
chmod +x deploy_pricebot_v19.sh rollback_pricebot.sh backup_pricebot.sh smoke_test_pricebot.sh
./deploy_pricebot_v19.sh
```

السكريبت يحافظ على `.env` و `pricebot.db`، ويعمل backup قبل migration.

## 4) التحقق من الصحة

```bash
curl http://127.0.0.1:8000/health
```

المتوقع:

```json
{"ok": true, "service": "pricebot"}
```

## 5) logs

```bash
journalctl -u pricebot -n 100 --no-pager
```

## 6) rollback

```bash
./rollback_pricebot.sh
```

لا يستبدل `.env` أو `pricebot.db` إلا إذا اخترت ذلك صراحة.

## 7) رفع المنتجات

من لوحة الأدمن:

```text
/admin/products/import
```

أو جهّز الملف أولاً:

```bash
python tools/catalog_intelligence_v5.py PriceList.xlsx --out-dir out_catalog
```

ارفع `products_ready_for_upload.xlsx` فقط، وراجع `products_needs_review.xlsx`.

## 8) إغلاق debug endpoints
في الإنتاج اترك:

```env
PRICEBOT_DEBUG_ENDPOINTS=false
```

## 9) لوحات V19

- `/admin/dashboard`
- `/admin/products/import`
- `/admin/products/review`
- `/admin/products/duplicates`
- `/admin/quality-dashboard`
- `/admin/learning-center`
- `/admin/ai-usage`
- `/merchant/login`
- `/merchant/dashboard`

V19 نسخة Production Pilot احترافية. اختبرها على كتالوج وصور حقيقية قبل البيع العام الواسع.

## V19.1 merchant safety settings

Before enabling the Merchant Portal in production, set these in `.env`:

```env
MERCHANT_PORTAL_ENABLED=true
MERCHANT_LOGIN_CODE=replace_with_private_code
MERCHANT_SESSION_SECRET=replace_with_long_random_secret
```

Do not use `merchant` as a login code. If `MERCHANT_LOGIN_CODE` is missing, `/merchant/*` stays disabled in production and returns 503.

For V19.1 deployment use:

```bash
chmod +x deploy_pricebot_v19_1.sh rollback_pricebot.sh backup_pricebot.sh smoke_test_pricebot.sh
./deploy_pricebot_v19_1.sh
```
