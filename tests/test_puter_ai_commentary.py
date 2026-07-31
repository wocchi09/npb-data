import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PuterAiCommentaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_site_loads_puter_and_keeps_local_fallback(self):
        self.assertIn('<script src="https://js.puter.com/v2/"></script>', self.html)
        self.assertIn("function saberGeneratePuterAI", self.html)
        self.assertIn("puter.ai.chat", self.html)
        self.assertIn("function saberGenerateLocalAI", self.html)
        self.assertIn("LanguageModel", self.html)

    def test_puter_runs_before_local_ai_fallback(self):
        generate = self.html.split("async function saberGenerateAI()", 1)[1]
        generate = generate.split("function saberProfile", 1)[0]
        self.assertLess(
            generate.index("saberGeneratePuterAI"),
            generate.index("saberGenerateLocalAI"),
        )

    def test_site_does_not_embed_provider_secrets_or_cloudflare_config(self):
        self.assertNotIn("GEMINI_API_KEY", self.html)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", self.html)
        self.assertNotIn("commentaryEndpoint", self.html)
        self.assertNotIn("ai-config.js", self.html)

    def test_privacy_and_fallback_copy_is_visible(self):
        self.assertIn("氏名・球団・表示指標以外の情報は送信しません", self.html)
        self.assertIn("端末内AIへ切り替えます", self.html)
        self.assertIn("上のデータ寸評は常に表示されます", self.html)


if __name__ == "__main__":
    unittest.main()
