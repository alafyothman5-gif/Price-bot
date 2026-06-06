# PriceBot V17.3 Maintenance Fixes

هذه نسخة صيانة محافظة مبنية على V17.2 بدون تغيير سلوك المطابقة الأساسي.

الإصلاحات:

1. `invalidate_product_cache()` الآن يمسح `matcher_v3.get_catalog_index` و `matcher_v4.invalidate_cache()` بدل استدعاء refresh خاطئ.
2. `safe_match()` أصبحت deprecated وتفشل صراحة إذا استدعاها أي كود جديد حتى لا يرجع legacy fuzzy.
3. حذف `pricebot.db` من الحزمة وإضافة `.gitignore` يحمي قاعدة الإنتاج من الاستبدال.
4. توحيد تحميل dynamic synonyms عبر `database.load_dynamic_synonyms_clean()`.
5. حذف تعريف `refresh_synonym_rules()` القديم المكرر في `matcher_v3.py`.
6. حذف `fast_matcher.py` من الحزمة لأنه غير مستخدم في الإنتاج.
7. جعل `acceptance_tests.py` و `acceptance_tests_v2.py` يطبعان تحذير deprecated بدل تمرير وهمي.
8. تحويل `acceptance_tests_v3.py` إلى matcher_v4.
9. نقل fallback الخاص بـ rapidfuzz إلى `_fuzzy_compat.py` بدل تكراره في 3 ملفات.
10. تثبيت rapidfuzz على `<4.0.0`.

ملاحظة: لم يتم تغيير قاعدة المطابقة أو الردود في V17.2؛ هذه صيانة لمنع الكاش القديم ومخاطر النشر والالتباس.
