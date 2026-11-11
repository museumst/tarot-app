import unittest

from fastapi import HTTPException

import app


class DailyCardsTest(unittest.IsolatedAsyncioTestCase):
    def test_every_supported_language_has_all_cards(self):
        slugs = [card["slug"] for card in app.load_deck()]
        for lang in app.LANG_NAMES:
            with self.subTest(lang=lang):
                data = app.load_daily_cards(lang)
                self.assertIsNotNone(data)
                self.assertEqual(list(data["cards"]), slugs)
                self.assertTrue(data["title"])
                self.assertEqual(set(data["labels"]), {"headline", "message", "action", "watch"})
                for card in data["cards"].values():
                    self.assertTrue(all(card[key].strip() for key in data["labels"]))

    async def test_endpoint_returns_json_for_known_language(self):
        response = await app.get_daily_cards(lang="en")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"the-fool"', response.body)

    async def test_unknown_language_is_not_available(self):
        self.assertIsNone(app.load_daily_cards("xx"))
        with self.assertRaises(HTTPException) as caught:
            await app.get_daily_cards(lang="xx")
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
