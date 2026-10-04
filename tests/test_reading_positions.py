import json
import os
import unittest
from unittest.mock import patch

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


class ReadingPositionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_position_is_sent_for_every_language(self):
        with open(os.path.join(app.BASE_DIR, "output", "spreads.json"), encoding="utf-8") as file:
            spread = next(item for item in json.load(file) if item.get("id") == 42)

        for language in app.LANG_NAMES:
            with self.subTest(language=language):
                messages = FakeMessages()
                client = type("Client", (), {"messages": messages})()
                request = app.ReadingRequest(
                    question="Will this relationship last?",
                    spread_name=spread["name"],
                    language=language,
                    cards=[app.DrawnCard(
                        name_ko="여덟 개의 컵",
                        name_en="EIGHT OF CUPS",
                        meaning="Leaving something behind",
                        reversed=False,
                        position_meaning=spread["positions"][0]["meaning"],
                        position_label=spread["positions"][0]["label"],
                    )],
                )
                with patch.object(app.anthropic, "AsyncAnthropic", return_value=client):
                    response = await app.tarot_reading(request)
                    chunks = [chunk async for chunk in response.body_iterator]

                self.assertIn("[DONE]", "".join(chunks))
                self.assertIn("고정 자리 제목: 현재 상황", messages.prompt["messages"][0]["content"])
                self.assertIn("translate that label faithfully", messages.prompt["system"])


if __name__ == "__main__":
    unittest.main()
