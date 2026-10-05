"""Read issue-form submissions and keep the form's category dropdown in sync with the README."""

import re
from dataclasses import dataclass

# Labels of the fields in .github/ISSUE_TEMPLATE/add-resource.yml (issue bodies only carry labels).
FIELD_LABELS = {
    "name": "Name",
    "url": "Link",
    "category": "Category",
    "description": "Description",
    "pricing": "Pricing",
    "why": "Why does it belong on the list?",
    "affiliation": "Affiliation",
}
NOT_SURE = "Not sure (let the bot suggest one)"
NO_RESPONSE = "_No response_"
CATEGORIES_START = "# categories:start"
CATEGORIES_END = "# categories:end"


@dataclass
class Submission:
    name: str = ""
    url: str = ""
    category: str = ""
    description: str = ""
    pricing: str = ""
    why: str = ""
    affiliation: str = ""


def parse_issue_form(body):
    """Split a rendered issue form into {label: value}."""
    fields, label, buffer = {}, None, []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        match = re.match(r"^###\s+(.+?)\s*$", line)
        if match:
            if label is not None:
                fields[label] = "\n".join(buffer).strip()
            label, buffer = match.group(1), []
        elif label is not None:
            buffer.append(line)
    if label is not None:
        fields[label] = "\n".join(buffer).strip()
    return {k: ("" if v == NO_RESPONSE else v) for k, v in fields.items()}


def parse_submission(body):
    raw = {k.casefold(): v for k, v in parse_issue_form(body).items()}
    return Submission(**{key: raw.get(label.casefold(), "") for key, label in FIELD_LABELS.items()})


def _quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _marker_lines(form_text):
    lines = form_text.split("\n")
    starts = [i for i, l in enumerate(lines) if l.strip() == CATEGORIES_START]
    ends = [i for i, l in enumerate(lines) if l.strip() == CATEGORIES_END]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise ValueError(f"Issue form needs exactly one `{CATEGORIES_START}` / `{CATEGORIES_END}` block")
    return lines, starts[0], ends[0]


def form_categories(form_text):
    lines, start, end = _marker_lines(form_text)
    values = []
    for line in lines[start + 1:end]:
        value = line.strip()
        if value.startswith("- "):
            value = value[2:].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            values.append(value)
    return values


def sync_form_categories(form_text, categories):
    lines, start, end = _marker_lines(form_text)
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    options = [f"{indent}- {_quote(c)}" for c in [*categories, NOT_SURE]]
    return "\n".join(lines[: start + 1] + options + lines[end:])
