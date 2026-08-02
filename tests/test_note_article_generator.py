import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NoteArticleGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_personal_posting_page_exposes_note_generator(self):
        self.assertIn("SNS・note作成", self.html)
        self.assertIn("note記事作成", self.html)
        self.assertIn('id="noteArticleTitle"', self.html)
        self.assertIn('id="noteArticleText"', self.html)

    def test_article_uses_collected_game_data(self):
        self.assertIn("function noteArticleBuild()", self.html)
        self.assertIn("function noteArticleGameSection(game)", self.html)
        self.assertIn("socialState.games", self.html)
        self.assertIn("result.homeruns||[]", self.html)
        self.assertIn("noteArticleHighlights(game)", self.html)
        self.assertIn("取得できていない情報は推測していません", self.html)

    def test_article_is_generated_after_date_data_loads(self):
        self.assertIn("socialRenderPosts(true);noteArticleRender();", self.html)
        self.assertIn("この日の試合データがないため記事を生成できません", self.html)

    def test_copy_download_and_note_handoff_exist(self):
        self.assertIn("function noteArticleMarkdown()", self.html)
        self.assertIn("navigator.clipboard.writeText(noteArticleMarkdown())", self.html)
        self.assertIn('type:"text/markdown;charset=utf-8"', self.html)
        self.assertIn('link.download="npb-note-"+socialState.date+".md"', self.html)
        self.assertIn('window.open("https://note.com/notes/new"', self.html)
        self.assertIn("コピーしてnoteを開く", self.html)

    def test_note_is_not_posted_automatically(self):
        self.assertNotIn("note.com/api", self.html)
        self.assertNotIn("noteToken", self.html)


if __name__ == "__main__":
    unittest.main()
