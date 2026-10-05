import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from awesome_bot import ai, commands, config, forms, readme  # noqa: E402
from awesome_bot.links import extract_meta, is_valid_url, normalize_url  # noqa: E402

META = ("Contents", "Contributing", "Footnotes")
SAMPLE = """# Awesome Test [![Awesome](https://awesome.re/badge.svg)](https://awesome.re)

> Intro.

## Contents

- [Software](#software)
- [Firmware & Controllers](#firmware--controllers)

## Software

Programs.

- [Alpha](https://alpha.example.com) - First tool.
- [Gamma](https://gamma.example.com/) - Third tool.

## Firmware & Controllers

## Related Lists

- [Awesome Other](https://github.com/x/awesome-other) - Another list.

## Contributing

- Not an entry, ignored.
"""


class ReadmeTests(unittest.TestCase):
    def test_parse_sections_and_entries(self):
        doc = readme.Readme(SAMPLE, META)
        self.assertEqual(doc.category_titles, ["Software", "Firmware & Controllers", "Related Lists"])
        self.assertEqual([e.name for e in doc.section("software").entries], ["Alpha", "Gamma"])

    def test_insert_sorted(self):
        text = readme.insert_entry(SAMPLE, "Software", "Beta", "https://beta.example.com", "Second tool.", META)
        names = [e.name for e in readme.Readme(text, META).section("Software").entries]
        self.assertEqual(names, ["Alpha", "Beta", "Gamma"])
        text = readme.insert_entry(text, "Software", "Zeta", "https://zeta.example.com", "Last tool.", META)
        self.assertEqual(readme.Readme(text, META).section("Software").entries[-1].name, "Zeta")

    def test_insert_into_empty_section_keeps_blank_lines(self):
        text = readme.insert_entry(SAMPLE, "Firmware & Controllers", "Grbl", "https://github.com/gnea/grbl", "Firmware.", META)
        self.assertIn("## Firmware & Controllers\n\n- [Grbl](https://github.com/gnea/grbl) - Firmware.\n\n## Related Lists", text)

    def test_insert_unknown_section_raises(self):
        with self.assertRaises(ValueError):
            readme.insert_entry(SAMPLE, "Contributing", "X", "https://x.example.com", "X.", META)

    def test_valid_sample_has_no_errors(self):
        problems = readme.validate(SAMPLE, 160, META)
        self.assertEqual([p.message for p in problems if p.level == "error"], [])

    def test_detects_problems(self):
        bad = SAMPLE.replace(
            "- [Gamma](https://gamma.example.com/) - Third tool.",
            "- [Gamma](https://gamma.example.com/) - Third tool.\n"
            "- [Beta](https://alpha.example.com/) - lowercase start\n"
            "- [Broken](no-scheme) - Bad link.\n"
            "- Just text",
        )
        messages = " ".join(p.message for p in readme.validate(bad, 160, META))
        for fragment in ("Duplicate link", "capital letter", "end with a period", "alphabetical", "not an absolute", "must look like"):
            self.assertIn(fragment, messages)

    def test_toc_mismatch_and_fix(self):
        bad = SAMPLE.replace("- [Firmware & Controllers](#firmware--controllers)\n", "")
        self.assertTrue(any("Table of contents" in p.message for p in readme.validate(bad, 160, META)))
        self.assertEqual(readme.fix(bad, META), SAMPLE)

    def test_fix_sorts_entries(self):
        swapped = SAMPLE.replace(
            "- [Alpha](https://alpha.example.com) - First tool.\n- [Gamma](https://gamma.example.com/) - Third tool.",
            "- [Gamma](https://gamma.example.com/) - Third tool.\n- [Alpha](https://alpha.example.com) - First tool.",
        )
        self.assertEqual(readme.fix(swapped, META), SAMPLE)

    def test_new_errors_ignores_existing(self):
        broken = SAMPLE.replace("First tool.", "First tool")
        after = readme.insert_entry(broken, "Software", "Beta", "https://beta.example.com", "Second tool.", META)
        self.assertEqual(readme.new_errors(broken, after, 160, META), [])
        worse = readme.insert_entry(broken, "Software", "Beta", "https://beta.example.com", "no period", META)
        self.assertEqual(len(readme.new_errors(broken, worse, 160, META)), 2)

    def test_existing_duplicate_does_not_block_insert(self):
        dup = SAMPLE.replace("- [Gamma](https://gamma.example.com/) - Third tool.",
                             "- [Gamma](https://gamma.example.com/) - Third tool.\n- [Zed](https://alpha.example.com) - Same page.")
        after = readme.insert_entry(dup, "Software", "Aardvark", "https://aardvark.example.com", "First.", META)
        self.assertEqual(readme.new_errors(dup, after, 160, META), [])

    def test_normalize_description(self):
        self.assertEqual(readme.normalize_description("a [cool](http://x) `tool` for cnc ", 160), "Cool tool for cnc.")
        long = readme.normalize_description("Word " * 60, 50)
        self.assertLessEqual(len(long), 50)
        self.assertTrue(long.endswith("."))
        self.assertEqual(readme.normalize_description("gSender is great", 160), "gSender is great.")

    def test_slug(self):
        self.assertEqual(readme.github_slug("Simulation & G-code Tools"), "simulation--g-code-tools")


class LinkTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_url("https://www.GitHub.com/Gnea/Grbl/"), normalize_url("http://github.com/gnea/grbl.git"))
        self.assertEqual(normalize_url("https://x.com/a?utm_source=y&b=1"), "x.com/a?b=1")
        self.assertNotEqual(normalize_url("https://x.com/A"), normalize_url("https://x.com/a"))

    def test_valid(self):
        self.assertTrue(is_valid_url("https://example.com/path"))
        for bad in ("example.com", "ftp://example.com", "https://localhost", "https://exa mple.com", "https://x.com/`a`"):
            self.assertFalse(is_valid_url(bad), bad)

    def test_extract_meta(self):
        page = '<html><head><title> Grbl &amp; more </title><meta content="Fast firmware" name="description"></head>'
        self.assertEqual(extract_meta(page), ("Grbl & more", "Fast firmware"))


class FormTests(unittest.TestCase):
    BODY = (
        "### Name\n\nCNCjs\n\n### Link\n\nhttps://cnc.js.org\n\n### Category\n\nSoftware\n\n"
        "### Description\n\nWeb-based interface.\n\n### Pricing\n\nOpen source\n\n"
        "### Why does it belong on the list?\n\n_No response_\n\n### Affiliation\n\nI'm not affiliated with it\n"
    )

    def test_parse_submission(self):
        sub = forms.parse_submission(self.BODY)
        self.assertEqual((sub.name, sub.url, sub.category, sub.why), ("CNCjs", "https://cnc.js.org", "Software", ""))

    def test_sync_round_trip(self):
        form = "      options:\n        # categories:start\n        - old\n        # categories:end\n"
        synced = forms.sync_form_categories(form, ["A & B", 'Say "hi"'])
        self.assertEqual(forms.form_categories(synced), ["A & B", 'Say "hi"', forms.NOT_SURE])

    def test_template_labels_match_parser(self):
        cfg = config.load()
        template = (config.REPO_ROOT / cfg.issue_form).read_text()
        for label in forms.FIELD_LABELS.values():
            self.assertIn(f"label: {label}", template)


class AITests(unittest.TestCase):
    def test_parse_json_object(self):
        self.assertEqual(ai.parse_json_object('```json\n{"verdict": "approve"}\n```'), {"verdict": "approve"})
        with self.assertRaises(ai.AIError):
            ai.parse_json_object("no json here")

    def test_assess_sanitises_model_output(self):
        cfg = config.load()
        reply = {
            "verdict": "APPROVE", "confidence": 7, "category": "software",
            "description": "the [best](http://spam) tool", "reasons": ["ping @someone <b>"], "concerns": "oops",
        }
        sub = forms.Submission(name="X", url="https://x.example.com", category="Software")
        with mock.patch.object(ai, "chat_json", return_value=reply):
            a = ai.assess(cfg, sub, ["Software", "CAM"], [], None)
        self.assertEqual((a.verdict, a.confidence, a.category), ("approve", 1.0, "Software"))
        self.assertEqual(a.description, "Best tool.")
        self.assertNotIn("@s", a.reasons[0])
        self.assertNotIn("<", a.reasons[0])
        self.assertEqual(a.concerns, [])

    def test_assess_failure_is_needs_review(self):
        cfg = config.load()
        with mock.patch.object(ai, "chat_json", side_effect=ai.AIError("rate limited")):
            a = ai.assess(cfg, forms.Submission(category="CAM"), ["CAM"], [], None)
        self.assertEqual((a.verdict, a.category, a.error), ("needs_review", "CAM", "rate limited"))


class FakeGitHub:
    """Just enough of gh.GitHub for process_issue."""

    repo = "owner/repo"

    def __init__(self, issue, readme_text):
        self.issue, self.readme_text = issue, readme_text
        self.labels_added, self.labels_removed, self.comments, self.prs, self.files = [], [], [], [], {}

    def get_issue(self, n): return self.issue
    def default_branch(self): return "main"
    def ensure_labels(self, defs): pass
    def get_file(self, path, ref, repo=None): return self.files.get(ref, self.readme_text), "sha-" + ref
    def comment(self, n, body): self.comments.append(body)
    def update_pr(self, n, **fields): pass
    def branch_sha(self, b): return "abc"
    def point_branch(self, b, sha): pass
    def put_file(self, path, branch, text, sha, message): self.files[branch] = text
    def find_open_pr(self, b): return None
    def create_pr(self, title, head, base, body):
        self.prs.append((title, head, body))
        return {"number": 99}
    def upsert_comment(self, n, marker, body): self.comments.append(body)
    def add_labels(self, n, labels): self.labels_added += labels
    def remove_label(self, n, label): self.labels_removed.append(label)


class ProcessIssueTests(unittest.TestCase):
    def make(self, body, labels=("submission",)):
        issue = {"number": 7, "state": "open", "body": body, "user": {"login": "maker"},
                 "labels": [{"name": l} for l in labels]}
        return FakeGitHub(issue, SAMPLE)

    def run_issue(self, gh, verdict="approve", confidence=0.95, link_ok=True):
        cfg = config.load()
        cfg.meta_sections = list(META)
        link = mock.Mock(ok=link_ok, error="", status=200, final_url="", title="", description="")
        link.summary.return_value = "reachable (HTTP 200)"
        assessment = ai.Assessment(verdict=verdict, confidence=confidence, category="Software",
                                   description="Second tool.", model="m")
        with mock.patch.object(commands, "check_url", return_value=link), \
             mock.patch.object(commands.ai, "assess", return_value=assessment), \
             mock.patch.dict("os.environ", {"GITHUB_TOKEN": "t"}):
            commands.process_issue(cfg, gh, 7)
        return cfg

    def body(self, url="https://beta.example.com", category="Software"):
        return FormTests.BODY.replace("CNCjs", "Beta").replace("https://cnc.js.org", url).replace("### Category\n\nSoftware", f"### Category\n\n{category}")

    def test_approved_submission_opens_pr(self):
        gh = self.make(self.body())
        cfg = self.run_issue(gh)
        self.assertEqual(len(gh.prs), 1)
        self.assertIn("- [Beta](https://beta.example.com) - Second tool.", gh.files[cfg.bot_branch_prefix + "7"])
        self.assertIn(cfg.label("ai_approved"), gh.labels_added)
        self.assertIn("Opened #99", gh.comments[-1])

    def test_duplicate_is_flagged_without_ai(self):
        gh = self.make(self.body(url="https://www.alpha.example.com/"))
        cfg = self.run_issue(gh)
        self.assertEqual(gh.prs, [])
        self.assertIn(cfg.label("duplicate"), gh.labels_added)
        self.assertIn("Already listed", gh.comments[-1])

    def test_low_confidence_needs_review(self):
        gh = self.make(self.body())
        cfg = self.run_issue(gh, confidence=0.5)
        self.assertEqual(gh.prs, [])
        self.assertIn(cfg.label("ai_needs_review"), gh.labels_added)

    def test_maintainer_approval_overrides_ai(self):
        gh = self.make(self.body(), labels=("submission", "approved"))
        self.run_issue(gh, verdict="reject", confidence=0.9, link_ok=None)
        self.assertEqual(len(gh.prs), 1)

    def test_unknown_category(self):
        gh = self.make(self.body(category="Nope"))
        cfg = self.run_issue(gh)
        self.assertIn(cfg.label("needs_changes"), gh.labels_added)


if __name__ == "__main__":
    unittest.main()
