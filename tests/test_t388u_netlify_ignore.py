"""Nuevo test t388u: Netlify no publica commits de solo datos (como Mesa)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DtsNetlifyIgnore(unittest.TestCase):
    def test_ignore_skips_data_only_commits(self):
        text = (ROOT / "netlify.toml").read_text(encoding="utf-8")
        match = re.search(r'^  ignore\s*=\s*"(.*)"\s*$', text, re.M)
        self.assertIsNotNone(match, "falta [build].ignore en netlify.toml")
        cmd = match.group(1)
        self.assertIn("git diff --quiet $CACHED_COMMIT_REF $COMMIT_REF", cmd)
        self.assertIn("index.html", cmd)
        self.assertIn("assets/**", cmd)
        self.assertIn("netlify.toml", cmd)
        self.assertNotIn("data/", cmd)


if __name__ == "__main__":
    unittest.main()
