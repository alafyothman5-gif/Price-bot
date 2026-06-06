# PriceBot V18 Launch Ready — تشغيل سريع

هذه النسخة مخصصة لتجربة إنتاجية تجارية محدودة. لا تلمس MedMCQ أو `/opt/medmcq` أو أي خدمة Telegram أثناء النشر.

## 1) مكان المشروع
ضع ملفات المشروع داخل:

```bash
/opt/pricebot
```

## 2) تجهيز `.env`
انسخ المثال:

```bash
cp .env.example .env
nano .env
```

املأ القيم المهمة:

- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`
- `META_VERIFY_TOKEN`
- `META_APP_SECRET`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `OPENROUTER_API_KEY`

لا ترفع `.env` إلى GitHub.

## 3) تشغيل النشر بأمر واحد
من داخل `/opt/pricebot`:

```bash
chmod +x deploy_pricebot_v18.sh rollback_pricebot.sh backup_pricebot.sh smoke_test_pricebot.sh
./deploy_pricebot_v18.sh
```

السكربت يعمل backup، يثبت المتطلبات، يشغل الاختبارات، يعمل migration آمن، ثم يعيد تشغيل `pricebot.service`.

## 4) فحص الصحة

```bash
curl http://127.0.0.1:8000/health
```

المتوقع:

```json
{"ok": true, "service": "pricebot"}
```

## 5) رؤية logs

```bash
journalctl -u pricebot -n 100 --no-pager
```

## 6) الرجوع لنسخة سابقة

```bash
./rollback_pricebot.sh 1
```

يرجع ملفات الكود فقط. لا يرجع `.env` أو `pricebot.db` إلا إذا شغلت:

```bash
RESTORE_ENV=true RESTORE_DB=true ./rollback_pricebot.sh 1
```

## 7) رفع المنتجات
افتح لوحة الأدمن، ثم صفحة المنتجات، وارفع ملف CSV أو XLSX. إذا كان الملف XLS قديماً ولم يعمل، حوّله إلى XLSX ثم ارفعه.

## 8) إغلاق debug endpoints
في الإنتاج اترك:

```env
PRICEBOT_DEBUG_ENDPOINTS=false
```

لا تستخدم `true` إلا للاختبار المحلي.

## 9) تحذير مهم
لا تلمس MedMCQ. لا تعدل `/opt/medmcq`. لا تعيد تشغيل خدمة Telegram أثناء نشر PriceBot.
