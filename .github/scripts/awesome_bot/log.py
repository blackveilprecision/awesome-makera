"""Readable GitHub Actions logs and run summaries.

Values often contain text from submitters or the model, so workflow-command processing is switched off
while they're printed (otherwise a line like `::error::` in a description would be interpreted by Actions).
"""

import os
import secrets

LABEL_WIDTH = 14


def _rows(rows):
    for row in rows:
        if isinstance(row, tuple):
            label, value = row
            if isinstance(value, (list, tuple)):
                value = "\n".join(f"- {v}" for v in value) if value else "(none)"
            lines = str(value).splitlines() if value not in (None, "") else ["(none)"]
            print(f"{label + ':':<{LABEL_WIDTH}}{lines[0]}")
            for extra in lines[1:]:
                print(" " * LABEL_WIDTH + extra)
        else:
            print(row)


def section(title, rows, collapsed=True):
    """Print rows of (label, value) pairs or plain strings, as a collapsible group in the Actions log."""
    token = secrets.token_hex(8)
    if collapsed:
        print(f"::group::{title.replace(chr(10), ' ')}")
    else:
        print(f"── {title}")
    print(f"::stop-commands::{token}")
    _rows(rows)
    print(f"::{token}::")
    if collapsed:
        print("::endgroup::")


def link_rows(prefix, link, url):
    if link is None:
        return [(prefix, "not checked")]
    rows = [(prefix, link.summary())]
    if link.final_url and link.final_url.rstrip("/") != url.rstrip("/"):
        rows.append(("Redirects to", link.final_url))
    if link.title:
        rows.append(("Page title", link.title))
    return rows


def assessment_section(title, assessment):
    if assessment is None:
        section(title, ["Skipped: the request already had blocking problems, so Copilot wasn't asked."])
        return
    if assessment.error:
        section(f"{title} · unavailable", [("Model", assessment.model), ("Attempts", assessment.attempts),
                                           ("Error", assessment.error)], collapsed=False)
        return
    section(f"{title} · {assessment.verdict.replace('_', ' ')} ({assessment.confidence:.2f})", [
        ("Model", assessment.model),
        ("Time", f"{assessment.seconds:.1f}s over {assessment.attempts} attempt(s)"),
        ("Verdict", f"{assessment.verdict.replace('_', ' ')} (confidence {assessment.confidence:.2f})"),
        ("Category", assessment.category),
        ("Description", assessment.description),
        ("Reasons", assessment.reasons),
        ("Concerns", assessment.concerns),
    ])


def summary(markdown):
    """Append markdown to the run's summary page (shown on the workflow run in the Actions tab)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown.rstrip() + "\n\n")
