"""Parse, edit and validate the awesome-list README.

The README is a flat list of `## Section` headings, each holding entries of the form
`- [Name](https://link) - Description.` kept in alphabetical order.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .links import is_valid_url, normalize_url

ENTRY_RE = re.compile(
    r"^- \[(?P<name>[^\[\]]+)\]\((?P<url>(?:[^()\s]|\([^()\s]*\))+)\) - (?P<desc>\S.*)$"
)
H2_RE = re.compile(r"^## (?P<title>.+?)\s*$")
# Mirrors awesome-lint's ToC rule: these sections never appear in the table of contents.
TOC_EXCLUDED = {"Contents", "Contributing", "Footnotes", "Related Lists"}
ENDING_PUNCTUATION = (".", "!", "?", "…")
ENTRY_FORMAT = "`- [Name](https://link) - Description.`"


@dataclass
class Entry:
    name: str
    url: str
    description: str
    line: int  # 0-based index into Readme.lines
    section: str

    def render(self):
        return format_entry(self.name, self.url, self.description)


@dataclass
class Section:
    title: str
    heading_line: int
    end_line: int  # exclusive
    entries: list = field(default_factory=list)
    bad_lines: list = field(default_factory=list)  # [(line, text)] bullets that are not valid entries
    subheadings: list = field(default_factory=list)


@dataclass
class Problem:
    message: str
    line: object = None  # 1-based, or None for file-level problems
    level: str = "error"


class Readme:
    def __init__(self, text, meta_sections=("Contents", "Contributing", "Footnotes")):
        self.text = text
        self.lines = text.split("\n")
        self.meta = set(meta_sections)
        self.sections = self._parse()

    def _parse(self):
        headings, in_code = [], False
        for i, line in enumerate(self.lines):
            if line.lstrip().startswith("```"):
                in_code = not in_code
            elif not in_code and (m := H2_RE.match(line)):
                headings.append((i, m["title"]))
        sections = []
        for n, (start, title) in enumerate(headings):
            end = headings[n + 1][0] if n + 1 < len(headings) else len(self.lines)
            section = Section(title, start, end)
            for i in range(start + 1, end):
                line = self.lines[i]
                if line.startswith("### "):
                    section.subheadings.append(i)
                elif line.startswith("- ") or line.startswith("* "):
                    if m := ENTRY_RE.match(line):
                        section.entries.append(Entry(m["name"], m["url"], m["desc"], i, title))
                    else:
                        section.bad_lines.append((i, line))
            sections.append(section)
        return sections

    @property
    def categories(self):
        return [s for s in self.sections if s.title not in self.meta]

    @property
    def category_titles(self):
        return [s.title for s in self.categories]

    def section(self, title):
        for s in self.sections:
            if s.title.casefold() == (title or "").strip().casefold():
                return s
        return None

    def entries(self):
        return [e for s in self.categories for e in s.entries]

    def find_url(self, url):
        key = normalize_url(url)
        return next((e for e in self.entries() if normalize_url(e.url) == key), None)


def format_entry(name, url, description):
    return f"- [{name}]({url}) - {description}"


def sort_key(name):
    text = unicodedata.normalize("NFKD", name).casefold()
    text = re.sub(r"^the\s+", "", text)
    return re.sub(r"[^0-9a-z]+", "", text) or text


def github_slug(title):
    slug = re.sub(r"[^\w\- ]", "", title.strip().lower())
    return slug.replace(" ", "-")


def sanitize_name(name):
    name = re.sub(r"[\[\]()<>|`*_\\]", "", name or "")
    return re.sub(r"\s+", " ", name).strip()[:100]


def normalize_description(text, max_length):
    """Best-effort cleanup of free-form text into awesome-list description style."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text or "")  # markdown links -> text
    text = re.sub(r"[`*_<>|\[\]\\]", "", text)
    text = re.sub(r"\s+", " ", text).strip().lstrip("-–— ").strip()
    text = re.sub(r"^(an?|the)\s+(?=\w)", "", text, flags=re.I)
    if not text:
        return ""
    first = re.split(r"[- ;./']", text, maxsplit=1)[0]
    if first.isalpha() and first.islower():
        text = text[0].upper() + text[1:]
    if len(text) > max_length:
        cut = text[: max_length - 1]
        text = cut[: cut.rfind(" ")] if " " in cut else cut
        text = text.rstrip(",;:-–— ")
    if not text.endswith(ENDING_PUNCTUATION):
        text = text.rstrip(",;:") + "."
    return text


def check_entry(name, url, description, max_length):
    """Problems with a single entry, independent of its position in the README."""
    problems = []
    if not name.strip():
        problems.append(Problem("Entry name is empty."))
    if not is_valid_url(url):
        problems.append(Problem(f"Link `{url}` is not an absolute http(s) URL."))
    elif url.startswith("http://"):
        problems.append(Problem(f"Prefer an `https://` link for `{url}` if the site supports it.", level="warning"))
    if not description:
        problems.append(Problem(f"`{name}` needs a description."))
        return problems
    first = re.split(r"[- ;./']", description, maxsplit=1)[0]
    cleaned = re.sub(r"\W+", "", first)
    if cleaned.isalpha() and cleaned.islower():
        problems.append(Problem(f"Description of `{name}` must start with a capital letter."))
    if not description.endswith(ENDING_PUNCTUATION):
        problems.append(Problem(f"Description of `{name}` must end with a period."))
    if len(description) > max_length:
        problems.append(Problem(f"Description of `{name}` is {len(description)} characters; keep it under {max_length}."))
    if description.casefold().startswith(name.casefold()):
        problems.append(Problem(f"Description of `{name}` shouldn't start by repeating the name."))
    if re.match(r"^(an?)\s", description, re.I):
        problems.append(Problem(f"Description of `{name}` shouldn't start with \"A\" or \"An\".", level="warning"))
    return problems


def render_toc(readme):
    return [
        f"- [{s.title}](#{github_slug(s.title)})"
        for s in readme.categories if s.title not in TOC_EXCLUDED
    ]


def _toc_block(readme):
    """(start, end) line range of the bullet list under `## Contents`, or None."""
    toc = readme.section("Contents")
    if not toc:
        return None
    bullets = [i for i in range(toc.heading_line + 1, toc.end_line) if readme.lines[i].startswith("- ")]
    if not bullets:
        return toc.heading_line + 1, toc.heading_line + 1
    return bullets[0], bullets[-1] + 1


def validate(text, max_length, meta_sections):
    readme = Readme(text, meta_sections)
    problems = []
    toc = _toc_block(readme)
    if toc is None:
        problems.append(Problem("Missing `## Contents` section."))
    elif readme.lines[toc[0]:toc[1]] != render_toc(readme):
        problems.append(Problem(
            "Table of contents doesn't match the section headings. Run `python3 -m awesome_bot validate --fix`.",
            readme.section("Contents").heading_line + 1,
        ))

    seen = {}
    for section in readme.categories:
        if not section.entries and not section.bad_lines:
            problems.append(Problem(f"Section `{section.title}` has no entries.", section.heading_line + 1, "warning"))
        for line in section.subheadings:
            problems.append(Problem("Sub-headings (`###`) aren't supported; use a `##` section instead.", line + 1))
        for line, text_ in section.bad_lines:
            problems.append(Problem(f"Entries must look like {ENTRY_FORMAT}", line + 1))
        names, previous = set(), None
        for entry in section.entries:
            for p in check_entry(entry.name, entry.url, entry.description, max_length):
                p.line = entry.line + 1
                problems.append(p)
            key = normalize_url(entry.url)
            if key in seen:
                problems.append(Problem(f"Duplicate link: `{entry.name}` points to the same page as `{seen[key]}`.", entry.line + 1))
            else:
                seen[key] = entry.name
            if entry.name.casefold() in names:
                problems.append(Problem(f"`{entry.name}` appears twice in `{section.title}`.", entry.line + 1))
            names.add(entry.name.casefold())
            if previous and sort_key(previous.name) > sort_key(entry.name):
                problems.append(Problem(
                    f"`{entry.name}` is out of alphabetical order (should come before `{previous.name}`). "
                    "Run `python3 -m awesome_bot validate --fix`.",
                    entry.line + 1,
                ))
            previous = entry
    return problems


def new_errors(before_text, after_text, max_length, meta_sections):
    """Errors present after an edit that weren't there before (pre-existing problems are ignored)."""
    before = Counter(p.message for p in validate(before_text, max_length, meta_sections) if p.level == "error")
    after = [p for p in validate(after_text, max_length, meta_sections) if p.level == "error"]
    fresh = []
    for p in after:
        if before[p.message]:
            before[p.message] -= 1
        else:
            fresh.append(p)
    return fresh


def insert_entry(text, section_title, name, url, description, meta_sections):
    readme = Readme(text, meta_sections)
    section = readme.section(section_title)
    if section is None or section.title in readme.meta:
        raise ValueError(f"Unknown section: {section_title}")
    lines = list(readme.lines)
    new_line = format_entry(name, url, description)
    if section.entries:
        key = sort_key(name)
        after = next((e for e in section.entries if sort_key(e.name) > key), None)
        lines.insert(after.line if after else section.entries[-1].line + 1, new_line)
    else:
        last = max(i for i in range(section.heading_line, section.end_line) if i == section.heading_line or lines[i].strip())
        lines[last + 1:last + 1] = ["", new_line]
        if last + 3 < len(lines) and lines[last + 3].strip():
            lines.insert(last + 3, "")
    return "\n".join(lines)


def fix(text, meta_sections):
    """Sort entries inside each section and regenerate the table of contents."""
    readme = Readme(text, meta_sections)
    lines = list(readme.lines)
    for section in readme.categories:
        runs, run = [], []
        for entry in section.entries:
            if run and entry.line != run[-1].line + 1:
                runs.append(run)
                run = []
            run.append(entry)
        runs.append(run)
        for run in filter(None, runs):
            ordered = sorted(run, key=lambda e: sort_key(e.name))
            for slot, entry in zip(run, ordered):
                lines[slot.line] = readme.lines[entry.line]
    text = "\n".join(lines)
    readme = Readme(text, meta_sections)
    toc = _toc_block(readme)
    if toc is None:
        return text
    start, end = toc
    lines = list(readme.lines)
    block = render_toc(readme)
    if start == end:  # empty Contents section
        block = [""] + block
    lines[start:end] = block
    return "\n".join(lines)
