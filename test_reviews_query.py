"""Review search with query across pages: what the header says and which rows come back.
No requests to shops.  Run: uv run --with 'websockets>=13' python -B -m unittest -v test_reviews_query"""
import json
import unittest
from unittest.mock import MagicMock, patch

import ali
import ozon


def ali_review(text):
    return {"root": {"text": text, "grade": 5, "date": "1 июня 2026"}, "reviewer": {"name": "A."}}


def ozon_page(texts, next_page=None):
    lr = {"reviews": [{"content": {"comment": t, "score": 5}, "itemId": 1} for t in texts], "paging": {"total": 20}}
    page = {"widgetStates": {"webListReviews-1": json.dumps(lr), "webReviewProductScore-1": json.dumps({"totalScore": 5})}}
    if next_page:
        page["nextPage"] = next_page
    return page


class AliQueryTests(unittest.TestCase):
    def run_reviews(self, pages, query="спасибо"):
        answers = [{"data": {"reviews": [ali_review(t) for t in p]}} for p in pages]
        with patch.object(ali, "_tab", return_value=MagicMock()), patch.object(ali, "_fetch", side_effect=answers) as fetch, \
                patch.object(ali, "_product_data", return_value={"data": {"reviews": 20}}), patch.object(ali.time, "sleep"):
            out = ali.reviews("1005008483608723", query=query)
        return out, fetch.call_count

    def test_empty_last_page_is_not_counted(self):
        out, calls = self.run_reviews([["спасибо"] + ["ok"] * 9, ["ok"] * 10, []])
        self.assertIn("страницы 1–2: «спасибо» нашлось в 1 из 20", out)
        self.assertEqual(calls, 3)

    def test_single_page_says_page(self):
        out, _ = self.run_reviews([["спасибо", "ok"]])
        self.assertIn("страница 1: «спасибо» нашлось в 1 из 2", out)

    def test_no_reviews_at_all(self):
        out, _ = self.run_reviews([[]])
        self.assertIn("страница 1: «спасибо» нашлось в 0 из 0", out)
        self.assertTrue(out.endswith("(отзывов нет)"))


class OzonQueryTests(unittest.TestCase):
    def test_empty_last_page_is_not_counted(self):
        pages = [ozon_page(["шумный"] + ["тихий"] * 9, "/p2"), ozon_page(["тихий"] * 10, "/p3"), ozon_page([])]
        with patch.object(ozon, "_tab", return_value=MagicMock()), patch.object(ozon, "_page", side_effect=pages):
            out = ozon.reviews("4843889081", query="шум")
        self.assertIn("страницы 1–2: «шум» нашлось в 1 из 20", out)
        self.assertEqual(out.count("шумный"), 1)


if __name__ == "__main__":
    unittest.main()
