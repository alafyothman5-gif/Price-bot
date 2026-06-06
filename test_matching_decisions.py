import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matcher_v4
from matcher_v2 import DecisionType


def catalog():
    return [
        {"product_id":"P1","name":"CeraVe Hydrating Cleanser 236ml","brand":"CeraVe","product_family":"Hydrating Cleanser","category":"cosmetic","form":"cleanser","size":"236ml","aliases":"cerave hydrating cleanser|cera ve hydrating cleanser|سيرافي غسول","ocr_keywords":"cerave|hydrating|cleanser|236ml","use_case":"hydration","price":"35","available":"true"},
        {"product_id":"P2","name":"CeraVe Hydrating Cleanser 473ml","brand":"CeraVe","product_family":"Hydrating Cleanser","category":"cosmetic","form":"cleanser","size":"473ml","aliases":"cerave hydrating cleanser","ocr_keywords":"cerave|hydrating|cleanser|473ml","use_case":"hydration","price":"55","available":"true"},
        {"product_id":"P3","name":"CeraVe Moisturizing Lotion 236ml","brand":"CeraVe","product_family":"Moisturizing","category":"cosmetic","form":"lotion","size":"236ml","aliases":"cerave moisturizing lotion","ocr_keywords":"cerave|moisturizing|lotion|236ml","use_case":"moisturizing","price":"50","available":"true"},
        {"product_id":"P4","name":"Flagyl Syrup 125mg/5ml","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"125mg/5ml","aliases":"flagyl syrup|فلاجيل شراب","ocr_keywords":"flagyl|syrup|125mg|metronidazole","price":"7.5","available":"true"},
        {"product_id":"P5","name":"Flagyl Syrup 200mg/5ml","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"200mg/5ml","aliases":"flagyl syrup","ocr_keywords":"flagyl|syrup|200mg|metronidazole","price":"8","available":"true"},
        {"product_id":"P6","name":"Flagyl 500mg Tablets","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"tablet","strength":"500mg","aliases":"flagyl tablet|فلاجيل اقراص","ocr_keywords":"flagyl|tablet|500mg|metronidazole","price":"9","available":"true"},
        {"product_id":"P7","name":"Rilastil Aqua Cleanser 200ml","brand":"Rilastil","product_family":"Aqua Cleanser","category":"cosmetic","form":"cleanser","size":"200ml","aliases":"rilastil aqua cleanser","ocr_keywords":"rilastil|aqua|cleanser|200ml","price":"40","available":"true"},
    ]


class MatchingDecisionTests(unittest.TestCase):
    def resolve(self, query):
        return matcher_v4.resolve_product_query(query, catalog())

    def test_brand_only_does_not_return_price(self):
        decision = self.resolve("Cerave")
        self.assertEqual(decision.decision_type, DecisionType.ASK_CLARIFICATION)
        self.assertIsNone(decision.product)

    def test_form_only_does_not_choose_random_product(self):
        decision = self.resolve("غسول")
        self.assertIn(decision.decision_type, {DecisionType.ASK_CLARIFICATION, DecisionType.LOW_CONFIDENCE})
        self.assertIsNone(decision.product)

    def test_cosmetic_multiple_sizes_asks_for_size(self):
        decision = self.resolve("CeraVe Hydrating Cleanser")
        self.assertEqual(decision.decision_type, DecisionType.ASK_CLARIFICATION)
        self.assertIsNone(decision.product)

    def test_medicine_family_asks_for_form(self):
        decision = self.resolve("Flagyl")
        self.assertEqual(decision.decision_type, DecisionType.ASK_CLARIFICATION)
        self.assertIsNone(decision.product)

    def test_medicine_form_asks_for_strength_when_multiple(self):
        decision = self.resolve("Flagyl syrup")
        self.assertEqual(decision.decision_type, DecisionType.ASK_CLARIFICATION)
        self.assertIsNone(decision.product)

    def test_specific_missing_product_is_not_random_alternative(self):
        decision = self.resolve("Rilastil Xerolact PB")
        self.assertEqual(decision.decision_type, DecisionType.NOT_AVAILABLE)
        self.assertFalse(decision.alternatives)


if __name__ == "__main__":
    unittest.main()
