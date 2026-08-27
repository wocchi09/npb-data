import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NpbChatPageTest(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
            return handle.read()

    def test_chat_assets_are_loaded(self):
        html = self.read("index.html")
        self.assertIn('href="npb_chat.css"', html)
        self.assertIn('src="npb_chat.js"', html)

    def test_chat_has_grounded_ai_and_fallback(self):
        js = self.read("npb_chat.js")
        self.assertIn("puter.ai.chat", js)
        self.assertIn("result.facts", js)
        self.assertIn("return result.text", js)
        self.assertIn("収集済み公開データ", js)

    def test_chat_learning_is_local_and_resettable(self):
        js = self.read("npb_chat.js")
        self.assertIn("localStorage.setItem", js)
        self.assertIn("npb-chat-v1", js)
        self.assertIn("学習メモリを消す", js)


if __name__ == "__main__":
    unittest.main()
