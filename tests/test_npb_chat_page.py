import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NpbChatPageTest(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
            return handle.read()

    def test_chat_assets_are_loaded(self):
        html = self.read("index.html")
        self.assertRegex(html, r'href="npb_chat\.css\?v=[^"]+"')
        self.assertRegex(html, r'src="npb_chat\.js\?v=[^"]+"')

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

    def test_chat_footer_stays_visible_in_short_viewports(self):
        css = self.read("npb_chat.css")
        js = self.read("npb_chat.js")
        self.assertIn("grid-template-rows:auto auto minmax(0,1fr) auto", css)
        self.assertIn(".npc-log{min-height:0", css)
        self.assertIn(".npc-footer{box-sizing:border-box;min-width:0;width:100%", css)
        self.assertIn('class="npc-footer"', js)
        self.assertIn("window.visualViewport", js)
        self.assertIn("vv.offsetTop+vv.height-height-pad", js)


if __name__ == "__main__":
    unittest.main()
