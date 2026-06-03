# PriceBot — نسخة GitHub جاهزة: Pagination + Search

هذه النسخة مخصصة للرفع إلى GitHub أولاً، ثم التفعيل من السيرفر.

## ماذا تم إصلاحه؟

- لوحة الأدمن لا تحمل كل المنتجات دفعة واحدة.
- صفحة المنتجات تعرض 25 / 50 / 100 منتج فقط في الصفحة.
- إضافة خانة بحث للمنتجات في لوحة الأدمن.
- إضافة خانة بحث للمنتجات في لوحة التاجر.
- بعد تعديل أو حذف منتج، ترجع لنفس صفحة البحث.

## مهم جداً

هذه النسخة لا تحتوي على بيانات الصيدلية الحقيقية:

- لا يوجد `products.csv`
- لا يوجد `pricebot.db`
- لا يوجد `.env`
- لا توجد توكنات
- لا توجد ملفات `venv`

عند تشغيل `DEPLOY_FROM_GITHUB.sh` على السيرفر، السكربت يبدل الكود فقط ويحافظ على المنتجات وقاعدة البيانات الموجودة في `/opt/pricebot`.

## طريقة الرفع إلى GitHub

ارفع محتويات هذا المجلد إلى ريبو GitHub عادي.

## طريقة التفعيل على السيرفر بعد الرفع

استبدل `YOUR_GITHUB_REPO_URL` برابط الريبو:

```bash
sudo bash -lc '
set -e
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y git >/dev/null
rm -rf /root/pricebot-github
cd /root
git clone YOUR_GITHUB_REPO_URL pricebot-github
cd /root/pricebot-github
bash DEPLOY_FROM_GITHUB.sh
'
```

## ماذا يفعل سكربت النشر؟

- يعمل نسخة احتياطية كاملة من `/opt/pricebot` قبل التعديل.
- ينسخ `app.py` و`requirements.txt` و`start_pricebot.sh` فقط.
- لا يحذف `products.csv`.
- لا يحذف `pricebot.db`.
- لا يلمس `.env` أو التوكنات.
- يشغل فحص `py_compile`.
- يعيد تشغيل خدمة `pricebot`.
- يفحص `/health`.
- إذا نجح الفحص، يحفظ نسخة مستقرة جديدة في:

```text
/root/pricebot_STABLE_LOCKED_LATEST.tar.gz
```

## بعد النشر اختبر

- Health:

```text
https://46.101.148.246.sslip.io/health
```

- لوحة الأدمن:

```text
https://46.101.148.246.sslip.io/admin?key=PriceBotAdmin2026
```

- واتساب: أرسل اسم منتج بسيط مثل `بنادول`.
