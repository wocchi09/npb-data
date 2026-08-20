import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SocialImageCardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "social_cards.js").read_text(encoding="utf-8")

    def test_card_types_and_canvas_preview_exist(self):
        self.assertIn("SNS画像カード", self.html)
        self.assertIn('id="socialCardCanvas"', self.html)
        self.assertIn("本日の本塁打", self.html)
        self.assertIn("日刊MVP", self.html)
        self.assertIn('src="social_cards.js"', self.html)

    def test_png_download_and_clipboard_copy_exist(self):
        self.assertIn("downloadSocialCard", self.script)
        self.assertIn('canvas.toBlob(resolve,"image/png",1)', self.script)
        self.assertIn("navigator.clipboard.write", self.script)
        self.assertIn("PNGで保存", self.html)
        self.assertIn("画像をコピー", self.html)

    def test_card_is_api_free_and_mobile_responsive(self):
        self.assertNotIn("apiKey", self.script)
        self.assertIn(".social-card-controls{grid-template-columns:1fr;}", self.html)
        self.assertIn("1200 × 675 PNG", self.html)


if __name__ == "__main__":
    unittest.main()
