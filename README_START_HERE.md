# PriceBot Final Enterprise Single File

هذه نسخة ملف واحد: الكود كله داخل `app.py`.

المميزات الأساسية:
- Webhook سريع عبر BackgroundTasks.
- HTTP async عبر httpx.
- حالة المحادثة محفوظة في SQLite.
- الإعدادات في SQLite بدل تعديل `.env`.
- دخول الأدمن/التاجر بجلسات Cookies.
- حماية CSRF للنماذج.
- بحث SQL مباشر في المنتجات والمادة الفعالة.
- لا يوجد تعديل رمز التاجر من الواجهة.

ارفع هذه الملفات فقط إلى GitHub:
- app.py
- DEPLOY_ON_SERVER.sh
- requirements.txt
- runtime.txt
- README_START_HERE.md
- .gitignore

لا ترفع `.env` أو `pricebot.db` أو `venv`.
