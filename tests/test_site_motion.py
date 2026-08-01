import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SiteMotionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_shared_view_and_stagger_animations_exist(self):
        self.assertIn(".motion-enter", self.html)
        self.assertIn(".motion-rise", self.html)
        self.assertIn("function motionRun", self.html)
        self.assertIn("MutationObserver", self.html)

    def test_data_visualizations_have_motion(self):
        self.assertIn(".saber-radar .shape", self.html)
        self.assertIn(".corr-svg .trend", self.html)
        self.assertIn(".bar-fill", self.html)
        self.assertIn("function motionCount", self.html)

    def test_awards_have_score_and_shine_motion(self):
        self.assertIn('class="motion-count"', self.html)
        self.assertIn("@keyframes mvpShine", self.html)
        self.assertIn(".mvpcard::after", self.html)

    def test_reduced_motion_is_respected(self):
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.html)
        self.assertIn("(prefers-reduced-motion: reduce)", self.html)


if __name__ == "__main__":
    unittest.main()
