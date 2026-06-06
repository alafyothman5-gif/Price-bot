PriceBot Product Catalog Enrichment

الغرض:
تحويل ملف Excel/CSV خام من الصيدلية إلى كتالوج آمن لمحرك المطابقة:
- products_enriched_ready.xlsx: منتجات جاهزة نسبياً للاستيراد.
- products_needs_review.xlsx: منتجات تحتاج مراجعة بشرية/صيدلي.
- suggested_substitution_groups.xlsx: اقتراحات بدائل دوائية للمراجعة فقط، ولا تعتمد تلقائياً.
- catalog_quality_report.json: تقرير جودة مختصر.

طريقة التشغيل:
python tools/enrich_products_catalog.py --input PriceList.xlsx --out-ready products_enriched_ready.xlsx --out-review products_needs_review.xlsx --out-report catalog_quality_report.json

لو الصيدلية تؤكد أن الملف يحتوي المنتجات المتوفرة فقط:
python tools/enrich_products_catalog.py --input PriceList.xlsx --default-available true

قواعد الأمان:
- السكربت لا يستخدم AI.
- لا يخترع barcode أو active_ingredient أو substitution_group_id.
- active_ingredient يأتي فقط من data/active_ingredients_dictionary.json أو من عمود واضح في الملف.
- أي نقص أو شك ينتقل إلى review_notes ويدخل products_needs_review.xlsx.
- لا تضف brand-only alias مثل cerave فقط؛ السكربت يمنع aliases العامة قدر الإمكان.

مهم للاستيراد:
ارفع products_enriched_ready.xlsx من لوحة الأدمن. تم توسيع مستورد المنتجات ليقرأ:
product_id, category, product_family, size, use_case, skin_type, substitution_group_id, review_status, review_notes, ocr_keywords.
