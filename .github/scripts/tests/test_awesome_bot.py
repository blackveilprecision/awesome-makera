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

    def test_find_entries(self):
        doc = readme.Readme(SAMPLE, META)
        for query in ("https://www.alpha.example.com/", "alpha", "- [Alpha](https://alpha.example.com) - First tool."):
            self.assertEqual([e.name for e in readme.find_entries(doc, query)], ["Alpha"], query)
        self.assertEqual(readme.find_entries(doc, "nope"), [])

    def test_apply_entry_diff_update_remove_and_idempotence(self):
        doc = readme.Readme(SAMPLE, META)
        alpha, gamma = doc.section("Software").entries
        moved = readme.Entry("Alpha", alpha.url, "First tool.", -1, "Firmware & Controllers")
        text, missing = readme.apply_entry_diff(SAMPLE, [alpha], [moved], META)
        self.assertEqual(missing, [])
        self.assertEqual([e.name for e in readme.Readme(text, META).section("Firmware & Controllers").entries], ["Alpha"])
        self.assertEqual(readme.apply_entry_diff(text, [alpha], [moved], META)[0], text)
        removed, added = readme.diff_entries(SAMPLE, text, META)
        self.assertEqual(([e.section for e in removed], [e.section for e in added]), (["Software"], ["Firmware & Controllers"]))
        # removing every entry of a section leaves tidy blank lines and still validates
        text, _ = readme.apply_entry_diff(SAMPLE, [alpha, gamma], [], META)
        self.assertNotIn("\n\n\n", text)
        self.assertEqual([p for p in readme.validate(text, 160, META) if p.level == "error"], [])
        # removing an entry that's already gone is reported
        self.assertEqual(readme.apply_entry_diff(text, [alpha], [], META)[1], [alpha])

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
        for path, labels in ((cfg.issue_form, forms.FIELD_LABELS), (cfg.update_form, forms.UPDATE_LABELS)):
            template = (config.REPO_ROOT / path).read_text()
            for label in labels.values():
                self.assertIn(f"label: {label}", template)
        update = (config.REPO_ROOT / cfg.update_form).read_text()
        self.assertIn(f"- {forms.ACTION_CHANGE}", update)
        self.assertIn(f"- {forms.ACTION_REMOVE}", update)

    def test_parse_update(self):
        body = ("### Entry\n\nhttps://alpha.example.com\n\n### What should happen?\n\nRemove it from the list\n\n"
                "### New link\n\n_No response_\n\n### New section\n\nNone\n\n### Why?\n\nArchived.\n")
        req = forms.parse_update(body)
        self.assertTrue(req.removing)
        self.assertEqual((req.entry, req.new_url, req.new_section, req.reason), ("https://alpha.example.com", "", "", "Archived."))


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
    def merge_pr(self, n, title): self.merged = getattr(self, "merged", []) + [n]
    def merge_base(self, base, head): return "merge-base"
    def open_prs(self): return getattr(self, "pr_list", [])
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


def update_body(entry="https://alpha.example.com", action="Change it", new_url="", new_name="",
                new_description="", new_section="", reason="Moved."):
    fields = [("Entry", entry), ("What should happen?", action), ("New link", new_url), ("New name", new_name),
              ("New description", new_description), ("New section", new_section), ("Why?", reason)]
    return "\n\n".join(f"### {k}\n\n{v or '_No response_'}" for k, v in fields)


class ProcessUpdateTests(unittest.TestCase):
    def run_update(self, body, verdict="approve", confidence=0.95, old_ok=True, new_ok=True, auto_merge=False,
                   labels=("entry update",), description=""):
        issue = {"number": 8, "state": "open", "body": body, "user": {"login": "fixer"},
                 "labels": [{"name": l} for l in labels]}
        gh = FakeGitHub(issue, SAMPLE)
        cfg = config.load()
        cfg.meta_sections, cfg.auto_merge = list(META), auto_merge

        def fake_check(url):
            ok = old_ok if "alpha" in url else new_ok
            link = mock.Mock(ok=ok, error="" if ok else "HTTP 404", status=200, final_url=url, title="", description="")
            link.summary.return_value = "reachable" if ok else "HTTP 404"
            return link

        assessment = ai.Assessment(verdict=verdict, confidence=confidence, description=description, model="m")
        with mock.patch.object(commands, "check_url", side_effect=fake_check), \
             mock.patch.object(commands.ai, "assess_change", return_value=assessment) as judged:
            commands.process_issue(cfg, gh, 8)
        return gh, cfg, judged

    def branch_text(self, gh, cfg):
        return gh.files.get(cfg.bot_branch_prefix + "8", "")

    def test_change_link_and_description(self):
        gh, cfg, _ = self.run_update(update_body(new_url="https://alpha.example.org", new_description="first tool, moved"),
                                     description="First tool, now on a new site.")
        self.assertEqual(gh.prs[0][0], "Update Alpha")
        text = self.branch_text(gh, cfg)
        self.assertIn("- [Alpha](https://alpha.example.org) - First tool, now on a new site.", text)
        self.assertNotIn("https://alpha.example.com)", text)
        self.assertIn("```diff", gh.comments[-1])

    def test_move_section(self):
        gh, cfg, _ = self.run_update(update_body(new_section="Firmware & Controllers"))
        self.assertEqual(gh.prs[0][0], "Move Alpha to Firmware & Controllers")
        doc = readme.Readme(self.branch_text(gh, cfg), META)
        self.assertEqual([e.name for e in doc.section("Firmware & Controllers").entries], ["Alpha"])

    def test_problems_block_without_ai(self):
        cases = [
            (update_body(entry="nope"), "Couldn't find that entry"),
            (update_body(), "Nothing would change"),
            (update_body(new_url="https://gamma.example.com"), "already on the list"),
            (update_body(new_section="Nope"), "Unknown **New section**"),
        ]
        for body, message in cases:
            gh, cfg, judged = self.run_update(body)
            self.assertEqual(gh.prs, [], message)
            self.assertIn(message, gh.comments[-1])
            self.assertIn(cfg.label("needs_changes"), gh.labels_added)
            judged.assert_not_called()

    def test_removal_of_dead_link_opens_pr_but_never_auto_merges(self):
        gh, cfg, _ = self.run_update(update_body(action="Remove it from the list", reason="Gone."),
                                     verdict="needs_review", old_ok=False, auto_merge=True)
        self.assertEqual(gh.prs[0][0], "Remove Alpha")
        self.assertNotIn("alpha.example.com", self.branch_text(gh, cfg))
        self.assertFalse(getattr(gh, "merged", []))

    def test_removal_of_working_link_needs_review(self):
        gh, cfg, _ = self.run_update(update_body(action="Remove it from the list", reason="Competitor."),
                                     verdict="needs_review", confidence=0.6)
        self.assertEqual(gh.prs, [])
        self.assertIn(cfg.label("ai_needs_review"), gh.labels_added)

    def test_change_auto_merges_when_enabled(self):
        gh, cfg, _ = self.run_update(update_body(new_name="Alpha Pro"), auto_merge=True)
        self.assertEqual(gh.merged, [99])


class RefreshTests(unittest.TestCase):
    def test_rebases_update_onto_new_main(self):
        cfg = config.load()
        cfg.meta_sections = list(META)
        alpha = readme.Readme(SAMPLE, META).section("Software").entries[0]
        updated = readme.Entry("Alpha", alpha.url, "Better description.", -1, "Software")
        head_text, _ = readme.apply_entry_diff(SAMPLE, [alpha], [updated], META)
        main_text = readme.insert_entry(SAMPLE, "Software", "Beta", "https://beta.example.com", "Second tool.", META)
        gh = FakeGitHub({}, main_text)
        gh.files = {"merge-base": SAMPLE, "head-sha": head_text}
        branch = cfg.bot_branch_prefix + "8"
        gh.pr_list = [{"number": 5, "title": "Update Alpha", "head": {"ref": branch, "sha": "head-sha", "repo": {"full_name": gh.repo}}}]
        commands.refresh_bot_prs(cfg, gh)
        rebased = readme.Readme(gh.files[branch], META)
        self.assertEqual([e.render() for e in rebased.section("Software").entries], [
            "- [Alpha](https://alpha.example.com) - Better description.",
            "- [Beta](https://beta.example.com) - Second tool.",
            "- [Gamma](https://gamma.example.com/) - Third tool.",
        ])


if __name__ == "__main__":
    unittest.main()
