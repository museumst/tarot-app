import unittest
from unittest import mock

import app


class FakeStream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    @property
    def text_stream(self):
        async def chunks():
            yield "reading"
        return chunks()


class FakeMessages:
    def stream(self, **kwargs):
        self.prompt = kwargs
        return FakeStream()


class DeepSpreadTest(unittest.TestCase):
    def test_korean_spread_has_six_fixed_positions_in_draw_order(self):
        spread = app.build_deep_choice_spread("ko", mock.Mock(side_effect=AssertionError("no AI call for ko")))
        self.assertEqual(spread["card_count"], 6)
        self.assertEqual(spread["layout"], "choice-deep")
        self.assertEqual(spread["name"], app.DEEP_CHOICE_NAME)
        self.assertEqual([p["label"] for p in spread["positions"]],
                         ["현재 상황", "선택지 A의 과정", "선택지 B의 과정", "선택지 A의 결과", "선택지 B의 결과", "결정의 열쇠"])
        self.assertTrue(all(p["meanings"] for p in spread["positions"]))

    def test_other_languages_get_translated_name_and_reason(self):
        reply = mock.Mock(content=[mock.Mock(text='{"name": "Two-Option Spread (6 cards)", "reason": "Because."}')])
        client = mock.Mock(messages=mock.Mock(create=mock.Mock(return_value=reply)))
        spread = app.build_deep_choice_spread("en", client)
        self.assertEqual(spread["name_translated"], "Two-Option Spread (6 cards)")
        self.assertEqual(spread["name"], app.DEEP_CHOICE_NAME)       # 서버가 구분하는 이름은 한국어 그대로

    def test_translation_failure_falls_back_instead_of_breaking(self):
        client = mock.Mock(messages=mock.Mock(create=mock.Mock(side_effect=RuntimeError("down"))))
        spread = app.build_deep_choice_spread("ja", client)
        self.assertEqual(spread["name_translated"], app.DEEP_CHOICE_NAME)

    def test_positions_are_copied_not_shared(self):
        a = app.build_deep_choice_spread("ko", None)
        a["positions"][0]["meanings"].append("x")
        b = app.build_deep_choice_spread("ko", None)
        self.assertEqual(len(b["positions"][0]["meanings"]), 1)


class SelectSpreadEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def call(self, **kw):
        req = app.SpreadSelectRequest(question="선택지 A: 가 vs 선택지 B: 나", language="ko", mode="choice", **kw)
        with mock.patch.object(app.anthropic, "Anthropic", return_value=mock.Mock()):
            return await app.select_spread(req, user={"sub": "u1"})

    async def test_deep_depth_returns_six_card_spread(self):
        spread = await self.call(depth="deep")
        self.assertEqual((spread["card_count"], spread["layout"]), (6, "choice-deep"))

    async def test_default_and_simple_depth_keep_three_cards(self):
        self.assertEqual((await self.call())["card_count"], 3)
        self.assertEqual((await self.call(depth="simple"))["card_count"], 3)

    async def test_depth_is_ignored_outside_choice_mode(self):
        self.assertIn("depth", app.SpreadSelectRequest.model_fields)
        req = app.SpreadSelectRequest(question="q", depth="deep")
        self.assertEqual(req.mode, "reading")


class ReadingPromptTest(unittest.IsolatedAsyncioTestCase):
    async def system_prompt(self, spread_name, question):
        messages = FakeMessages()
        client = type("Client", (), {"messages": messages})()
        request = app.ReadingRequest(
            question=question, spread_name=spread_name, language="ko",
            cards=[app.DrawnCard(name_ko="바보", name_en="THE FOOL", meaning="m", reversed=False)])
        store = type("Store", (), {"consume_reading": lambda self, *a: {"kind": "free", "free_used": 1, "credits": 0}})()
        with mock.patch.object(app.anthropic, "AsyncAnthropic", return_value=client), \
                mock.patch.object(app, "get_credit_store", return_value=store):
            response = await app.tarot_reading(request, user={"sub": "u1", "email": "a@example.com"})
            [_ async for _ in response.body_iterator]
        return messages.prompt["system"]

    async def test_deep_spread_uses_its_own_instructions_only(self):
        prompt = await self.system_prompt(app.DEEP_CHOICE_NAME, "선택지 A: 가 vs 선택지 B: 나")
        self.assertIn("fixed 6-card layout", prompt)
        self.assertIn("Do not add a seventh card", prompt)
        self.assertIn("key to the decision", prompt)
        self.assertNotIn("Treat EACH card except the last one", prompt)       # 일반 비교 지침과 섞이지 않는다

    async def test_three_card_comparison_keeps_the_original_instructions(self):
        prompt = await self.system_prompt("양자택일 비교 스프레드", "선택지 A: 가 vs 선택지 B: 나")
        self.assertIn("Treat EACH card except the last one", prompt)
        self.assertNotIn("fixed 6-card layout", prompt)


if __name__ == "__main__":
    unittest.main()
