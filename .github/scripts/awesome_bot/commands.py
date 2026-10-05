"""Workflow entry points: triage issue submissions, review PRs, keep bot PRs fresh, validate locally."""

import os
from pathlib import Path

from . import ai, forms, readme
from .config import REPO_ROOT
from .gh import GitHub, GitHubError
from .links import check_url, is_shortener, is_valid_url, normalize_url

TRIAGE_MARKER = "<!-- awesome-bot:triage -->"
REVIEW_MARKER = "<!-- awesome-bot:review -->"
MAX_AI_ENTRIES_PER_PR = 10
AUTOMATION_PATHS = (".github/",)

STATUS_LABELS = ("needs_changes", "ai_approved", "ai_needs_review", "ai_rejected")
LABEL_STYLE = {
    "submission": ("0e8a16", "New resource suggested through the issue form"),
    "approved": ("1d76db", "Maintainer approved: the bot will open a PR adding it"),
    "ai_approved": ("c2e0c6", "Automated review: looks like a good fit"),
    "ai_needs_review": ("fbca04", "Automated review: a maintainer should take a look"),
    "ai_rejected": ("e99695", "Automated review: doesn't look like a fit"),
    "needs_changes": ("d93f0b", "Something needs fixing before this can be added"),
    "duplicate": ("cfd3d7", "Already on the list"),
    "update": ("5319e7", "Request to fix or remove an existing entry"),
}


def github():
    return GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])


def ensure_labels(cfg, gh):
    gh.ensure_labels({cfg.label(key): style for key, style in LABEL_STYLE.items()})


def set_status_label(cfg, gh, number, current_labels, status_key):
    wanted = cfg.label(status_key) if status_key else None
    for key in STATUS_LABELS:
        name = cfg.label(key)
        if name in current_labels and name != wanted:
            gh.remove_label(number, name)
    if wanted and wanted not in current_labels:
        gh.add_labels(number, [wanted])


def match_category(value, categories):
    return next((c for c in categories if c.casefold() == (value or "").strip().casefold()), None)


# --------------------------------------------------------------------------- issues

def process_issue(cfg, gh, number, force=False):
    """Check a submission issue, post the result, and open a PR when it's approved."""
    issue = gh.get_issue(number)
    labels = {l["name"] for l in issue["labels"]}
    is_update = cfg.label("update") in labels
    if "pull_request" in issue or issue["state"] != "open" or not (is_update or cfg.label("submission") in labels):
        print(f"#{number} is not an open submission or update request; nothing to do.")
        return
    force = force or cfg.label("approved") in labels
    ensure_labels(cfg, gh)
    if is_update:
        return process_update(cfg, gh, issue, labels, force)

    sub = forms.parse_submission(issue.get("body"))
    base = gh.default_branch()
    readme_text, _ = gh.get_file(cfg.readme, base)
    doc = readme.Readme(readme_text, cfg.meta_sections)
    categories = doc.category_titles

    problems, notes = [], []
    name = readme.sanitize_name(sub.name)
    url = sub.url.strip().strip("<>")
    section = match_category(sub.category, categories)
    duplicate = None
    if not name:
        problems.append("**Name** is missing.")
    if not is_valid_url(url):
        problems.append("**Link** must be a full URL starting with `https://`.")
    elif is_shortener(url):
        problems.append("Please use the direct link instead of a shortened one.")
    elif duplicate := doc.find_url(url):
        problems.append(f"Already listed under **{duplicate.section}** as [{duplicate.name}]({duplicate.url}).")
    if not section and sub.category != forms.NOT_SURE:
        problems.append(f"Unknown **Category** \"{ai.clean_note(sub.category, 80)}\". Pick one from the dropdown.")

    link = None
    if not problems:
        link = check_url(url)
        if link.ok is False:
            (notes if force else problems).append(f"The link looks broken ({link.error}).")
        elif link.ok is None:
            notes.append(f"Couldn't verify the link automatically ({link.error}), so a maintainer will check it.")

    assessment = None
    if not problems:
        existing = [e.name for e in doc.section(section).entries] if section else [e.name for e in doc.entries()]
        assessment = ai.assess(cfg, sub, categories, existing, link)
        if assessment.error:
            notes.append(f"Automated review was unavailable: {ai.clean_note(assessment.error)}")
        if not section:
            section = assessment.category or None
            if not section:
                problems.append("Please choose a **Category**.")
        elif assessment.category and assessment.category != section:
            notes.append(f"Automated review suggests **{assessment.category}** instead of **{section}**. "
                         "Edit the issue to change it.")

    proposal = None
    if not problems:
        description = (assessment and assessment.description) or readme.normalize_description(
            sub.description, cfg.max_description_length)
        entry_problems = readme.check_entry(name, url, description, cfg.max_description_length)
        problems += [p.message for p in entry_problems if p.level == "error"]
        notes += [p.message for p in entry_problems if p.level == "warning"]
        proposal = readme.Entry(name, url, description, -1, section)

    if problems:
        status = "needs_changes"
    elif force:
        status = "approved"
    elif (assessment.verdict == "approve" and not assessment.error and link and link.ok
          and assessment.confidence >= cfg.auto_approve_min_confidence):
        status = "ai_approved"
    elif assessment.verdict == "reject":
        status = "ai_rejected"
    else:
        status = "ai_needs_review"

    pr, merged = None, False
    if status in ("approved", "ai_approved") and (force or cfg.auto_open_pr):
        try:
            title = f"Add {proposal.name}"
            body = render_pr_body(proposal, issue, assessment, link)
            pr, merged = open_bot_pr(cfg, gh, number, base, [], [proposal], title, f"{title} to {proposal.section}", body)
        except (ValueError, GitHubError) as e:
            notes.append(f"Couldn't open a pull request: {ai.clean_note(e, 400)}. Maintainers: see MAINTAINERS.md.")
    elif status not in ("approved", "ai_approved"):
        close_stale_pr(cfg, gh, number)

    set_status_label(cfg, gh, number, labels, None if status == "approved" else status)
    if duplicate:
        gh.add_labels(number, [cfg.label("duplicate")])
    gh.upsert_comment(number, TRIAGE_MARKER, render_triage(cfg, status, proposal, problems, notes, assessment, link, pr, merged))
    print(f"#{number}: {status}" + (f", PR #{pr['number']}" if pr else ""))


def close_stale_pr(cfg, gh, number):
    stale = gh.find_open_pr(f"{cfg.bot_branch_prefix}{number}")
    if stale:
        gh.comment(stale["number"], f"Closing: the request in #{number} no longer passes review.")
        gh.update_pr(stale["number"], state="closed")


def open_bot_pr(cfg, gh, number, base, removed, added, title, commit_title, body, allow_merge=True):
    """Apply removed/added entries to the latest default branch on the issue's bot branch and open (or update) its PR."""
    base_sha = gh.branch_sha(base)
    base_text, _ = gh.get_file(cfg.readme, base_sha)  # read at the exact commit the branch will start from
    new_text, missing = readme.apply_entry_diff(base_text, removed, added, cfg.meta_sections)
    if missing:
        raise ValueError(f"{missing[0].name} changed on the list in the meantime; edit the issue to re-check")
    if new_text == base_text:
        raise ValueError("the list already includes this change")
    errors = readme.new_errors(base_text, new_text, cfg.max_description_length, cfg.meta_sections)
    if errors:
        raise ValueError("the change would break README checks: " + "; ".join(p.message for p in errors))

    branch = f"{cfg.bot_branch_prefix}{number}"
    gh.point_branch(branch, base_sha)
    _, file_sha = gh.get_file(cfg.readme, branch)
    gh.put_file(cfg.readme, branch, new_text, file_sha, f"{commit_title}\n\nCloses #{number}")

    pr = gh.find_open_pr(branch)
    if pr:
        gh.update_pr(pr["number"], title=title, body=body)
    else:
        pr = gh.create_pr(title, branch, base, body)
    merged = False
    if cfg.auto_merge and allow_merge:
        try:
            gh.merge_pr(pr["number"], f"{title} (#{pr['number']})")
            merged = True
        except GitHubError as e:
            print(f"Auto-merge of PR #{pr['number']} failed: {e}")
    return pr, merged


def render_triage(cfg, status, entry, problems, notes, assessment, link, pr, merged):
    approved = cfg.label("approved")
    headline = {
        "approved": "✅ Approved by a maintainer.",
        "ai_approved": "✅ Looks like a great fit.",
        "ai_needs_review": "🔍 Plausible, but a maintainer needs to take a look.",
        "ai_rejected": "🚫 This doesn't look like a fit for the list.",
        "needs_changes": "✏️ A few things need fixing first.",
    }[status]
    if pr and merged:
        headline += f" Added in #{pr['number']}. Thank you!"
    elif pr:
        headline += f" Opened #{pr['number']} to add it."
    elif status == "ai_approved":
        headline += f" A maintainer will add the `{approved}` label to publish it."

    out = ["### Submission check", "", f"**{headline}**", ""]
    if entry:
        out += [f"Proposed entry for **{entry.section}**:", "", "```markdown", entry.render(), "```", ""]
    if problems:
        out += ["**Needs fixing**", ""] + [f"- {p}" for p in problems] + [""]
    checks = []
    if link:
        checks.append(f"{'✅' if link.ok else '⚠️' if link.ok is None else '❌'} Link {link.summary()}")
    if entry:
        checks.append("✅ Not already on the list")
    if notes:
        checks += [f"⚠️ {n}" for n in notes]
    if checks:
        out += ["**Checks**", ""] + [f"- {c}" for c in checks] + [""]
    if assessment and not assessment.error:
        verdict = assessment.verdict.replace("_", " ")
        out += [f"**Automated review** · `{assessment.model}` · verdict: *{verdict}* · confidence {assessment.confidence:.2f}", ""]
        out += [f"- {r}" for r in assessment.reasons]
        out += [f"- ⚠️ {c}" for c in assessment.concerns]
        out.append("")
    out += [
        "<details><summary>What happens next?</summary>",
        "",
        "- **Submitter:** edit the issue to fix anything above. The bot re-checks on every edit.",
        f"- **Maintainers:** add the `{approved}` label to accept it (the bot opens the PR), "
        "or close the issue to decline.",
        "- The automated review is advisory. Maintainers make the final call.",
        "",
        "</details>",
    ]
    return "\n".join(out)


def render_pr_body(entry, issue, assessment, link):
    out = [
        f"Adds **[{entry.name}]({entry.url})** to **{entry.section}**.",
        "",
        "```markdown",
        entry.render(),
        "```",
        "",
        f"Closes #{issue['number']}. Suggested by @{issue['user']['login']}.",
        "",
    ]
    if assessment and not assessment.error:
        out += [
            "<details><summary>Automated review</summary>",
            "",
            f"- Verdict: *{assessment.verdict.replace('_', ' ')}* (confidence {assessment.confidence:.2f}, `{assessment.model}`)",
            *[f"- {r}" for r in assessment.reasons],
            *[f"- ⚠️ {c}" for c in assessment.concerns],
            f"- Link: {link.summary() if link else 'not checked'}",
            "",
            "</details>",
            "",
        ]
    out.append("_Opened automatically by the awesome-bot workflow from an issue submission._")
    return "\n".join(out)


# --------------------------------------------------------------------------- update requests

def process_update(cfg, gh, issue, labels, force):
    """Check a "Fix or remove an entry" request, post the result, and open a PR when it's approved."""
    number = issue["number"]
    request = forms.parse_update(issue.get("body"))
    base = gh.default_branch()
    readme_text, _ = gh.get_file(cfg.readme, base)
    doc = readme.Readme(readme_text, cfg.meta_sections)
    categories = doc.category_titles
    problems, notes = [], []

    matches = readme.find_entries(doc, request.entry)
    old = matches[0] if len(matches) == 1 else None
    if not matches:
        problems.append("Couldn't find that entry. Paste its link exactly as it appears in the list, or its exact name.")
    elif len(matches) > 1:
        problems.append("More than one entry has that name. Paste the entry's link instead.")
    removing = request.removing
    if not removing and request.action.strip().casefold() != forms.ACTION_CHANGE.casefold():
        problems.append("Choose what should happen: change the entry or remove it.")

    new = None
    if old and not removing and not problems:
        url = request.new_url.strip().strip("<>") or old.url
        section = old.section
        if request.new_section:
            section = match_category(request.new_section, categories)
            if not section:
                problems.append(f"Unknown **New section** \"{ai.clean_note(request.new_section, 80)}\".")
        if url != old.url:
            if not is_valid_url(url):
                problems.append("**New link** must be a full URL starting with `https://`.")
            elif is_shortener(url):
                problems.append("Please use the direct link instead of a shortened one.")
            elif (other := doc.find_url(url)) and other.line != old.line:
                problems.append(f"That link is already on the list as [{other.name}]({other.url}).")
        description = (readme.normalize_description(request.new_description, cfg.max_description_length)
                       if request.new_description.strip() else old.description)
        new = readme.Entry(readme.sanitize_name(request.new_name) or old.name, url, description, -1, section or old.section)
        if new.render() == old.render() and new.section == old.section:
            problems.append("Nothing would change. Fill in at least one of the **New** fields.")

    old_link = new_link = None
    if old and not problems:
        old_link = check_url(old.url)
        if new and new.url != old.url:
            new_link = check_url(new.url)
            if new_link.ok is False:
                (notes if force else problems).append(f"The new link looks broken ({new_link.error}).")
            elif new_link.ok is None:
                notes.append(f"Couldn't verify the new link automatically ({new_link.error}).")
        if old_link.ok is False:
            notes.append(f"The current link is broken ({old_link.error}).")

    assessment = None
    if not problems:
        assessment = ai.assess_change(cfg, old, new, request, categories, old_link, new_link)
        if assessment.error:
            notes.append(f"Automated review was unavailable: {ai.clean_note(assessment.error)}")
        if new and request.new_description.strip() and assessment.description:
            new.description = assessment.description
        if new and assessment.category and assessment.category != new.section:
            notes.append(f"Automated review suggests **{assessment.category}** for this entry.")
        if new:
            entry_problems = readme.check_entry(new.name, new.url, new.description, cfg.max_description_length)
            problems += [p.message for p in entry_problems if p.level == "error"]
            notes += [p.message for p in entry_problems if p.level == "warning"]

    links_ok = new_link is None or new_link.ok
    if problems:
        status = "needs_changes"
    elif force:
        status = "approved"
    elif removing and old_link.ok is False and assessment.verdict != "reject":
        status = "ai_approved"  # the resource is verifiably gone
    elif (assessment.verdict == "approve" and not assessment.error and links_ok
          and assessment.confidence >= cfg.auto_approve_min_confidence):
        status = "ai_approved"
    elif assessment.verdict == "reject":
        status = "ai_rejected"
    else:
        status = "ai_needs_review"

    pr, merged = None, False
    if status in ("approved", "ai_approved") and (force or cfg.auto_open_pr):
        verb = "Remove" if removing else ("Move" if new.section != old.section and new.render() == old.render() else "Update")
        title = f"{verb} {old.name}" + (f" to {new.section}" if verb == "Move" else "")
        body = render_update_pr_body(old, new, issue, request, assessment, old_link, new_link)
        try:
            # Removals are never merged automatically, so a bad-faith request always reaches a human.
            pr, merged = open_bot_pr(cfg, gh, number, base, [old], [new] if new else [], title, title, body,
                                     allow_merge=not removing)
        except (ValueError, GitHubError) as e:
            notes.append(f"Couldn't open a pull request: {ai.clean_note(e, 400)}. Maintainers: see MAINTAINERS.md.")
    elif status not in ("approved", "ai_approved"):
        close_stale_pr(cfg, gh, number)

    set_status_label(cfg, gh, number, labels, None if status == "approved" else status)
    gh.upsert_comment(number, TRIAGE_MARKER, render_update(
        cfg, status, old, new, removing, problems, notes, assessment, old_link, new_link, pr, merged))
    print(f"#{number}: {status}" + (f", PR #{pr['number']}" if pr else ""))


def _change_block(old, new):
    lines = ["```diff", f"- {old.render()}"]
    if new:
        lines.append(f"+ {new.render()}")
    lines.append("```")
    if new and new.section != old.section:
        lines.append(f"Moves it from **{old.section}** to **{new.section}**.")
    return lines


def render_update(cfg, status, old, new, removing, problems, notes, assessment, old_link, new_link, pr, merged):
    approved = cfg.label("approved")
    headline = {
        "approved": "✅ Approved by a maintainer.",
        "ai_approved": "✅ This change looks right.",
        "ai_needs_review": "🔍 A maintainer needs to take a look.",
        "ai_rejected": "🚫 This change doesn't look justified.",
        "needs_changes": "✏️ A few things need fixing first.",
    }[status]
    if pr and merged:
        headline += f" Done in #{pr['number']}. Thank you!"
    elif pr:
        headline += f" Opened #{pr['number']} with the change."
    elif status == "ai_approved":
        headline += f" A maintainer will add the `{approved}` label to apply it."

    out = ["### Update check", "", f"**{headline}**", ""]
    if old and (new or removing) and not problems:
        out += [f"Proposed change in **{old.section}**:", ""] + _change_block(old, new) + [""]
    if problems:
        out += ["**Needs fixing**", ""] + [f"- {p}" for p in problems] + [""]
    checks = []
    if old_link:
        checks.append(f"{'✅' if old_link.ok else '⚠️' if old_link.ok is None else '❌'} Current link {old_link.summary()}")
    if new_link:
        checks.append(f"{'✅' if new_link.ok else '⚠️' if new_link.ok is None else '❌'} New link {new_link.summary()}")
    checks += [f"⚠️ {n}" for n in notes]
    if checks:
        out += ["**Checks**", ""] + [f"- {c}" for c in checks] + [""]
    if assessment and not assessment.error:
        verdict = assessment.verdict.replace("_", " ")
        out += [f"**Automated review** · `{assessment.model}` · verdict: *{verdict}* · confidence {assessment.confidence:.2f}", ""]
        out += [f"- {r}" for r in assessment.reasons] + [f"- ⚠️ {c}" for c in assessment.concerns] + [""]
    out += [
        "<details><summary>What happens next?</summary>",
        "",
        "- **Requester:** edit the issue to fix anything above. The bot re-checks on every edit.",
        f"- **Maintainers:** add the `{approved}` label to accept it (the bot opens the PR), or close the issue to decline.",
        "- Removals are never merged automatically. A maintainer always confirms them.",
        "",
        "</details>",
    ]
    return "\n".join(out)


def render_update_pr_body(old, new, issue, request, assessment, old_link, new_link):
    action = f"Removes **{old.name}** from" if new is None else f"Updates **{old.name}** in"
    out = [f"{action} **{old.section}**.", ""] + _change_block(old, new) + [
        "",
        f"Closes #{issue['number']}. Requested by @{issue['user']['login']}.",
        "",
        f"> **Reason given:** {ai.clean_note(request.reason, 500) or 'none'}",
        "",
    ]
    if assessment and not assessment.error:
        out += [
            "<details><summary>Automated review</summary>",
            "",
            f"- Verdict: *{assessment.verdict.replace('_', ' ')}* (confidence {assessment.confidence:.2f}, `{assessment.model}`)",
            *[f"- {r}" for r in assessment.reasons],
            *[f"- ⚠️ {c}" for c in assessment.concerns],
            f"- Current link: {old_link.summary() if old_link else 'not checked'}",
            *([f"- New link: {new_link.summary()}"] if new_link else []),
            "",
            "</details>",
            "",
        ]
    out.append("_Opened automatically by the awesome-bot workflow from an update request._")
    return "\n".join(out)


# --------------------------------------------------------------------------- pull requests

def review_pr(cfg, gh, number):
    """Advisory review of a human PR: README checks plus link and relevance review of each added entry."""
    pr = gh.get_pr(number)
    head_repo = (pr["head"].get("repo") or {}).get("full_name")
    if pr["state"] != "open":
        return
    if head_repo == gh.repo and pr["head"]["ref"].startswith(cfg.bot_branch_prefix):
        print("Bot-authored PR; already reviewed at submission time.")
        return
    ensure_labels(cfg, gh)
    labels = {l["name"] for l in pr["labels"]}
    files = [f["filename"] for f in gh.pr_files(number)]
    automation = [f for f in files if f.startswith(AUTOMATION_PATHS)]

    base_text, _ = gh.get_file(cfg.readme, pr["base"]["ref"])
    head_text = base_text
    if cfg.readme in files:
        try:
            head_text, _ = gh.get_file(cfg.readme, pr["head"]["sha"])
        except GitHubError:
            head_text, _ = gh.get_file(cfg.readme, pr["head"]["sha"], repo=head_repo)

    errors = readme.new_errors(base_text, head_text, cfg.max_description_length, cfg.meta_sections)
    warnings = [p for p in readme.validate(head_text, cfg.max_description_length, cfg.meta_sections) if p.level == "warning"]
    base_doc = readme.Readme(base_text, cfg.meta_sections)
    head_doc = readme.Readme(head_text, cfg.meta_sections)
    categories = head_doc.category_titles
    base_urls = {normalize_url(e.url): e for e in base_doc.entries()}
    head_urls = {normalize_url(e.url) for e in head_doc.entries()}
    added = [e for e in head_doc.entries() if normalize_url(e.url) not in base_urls]
    removed = [e for k, e in base_urls.items() if k not in head_urls]

    results = []
    for entry in added[:MAX_AI_ENTRIES_PER_PR]:
        link = check_url(entry.url)
        section = head_doc.section(entry.section)
        sub = forms.Submission(
            name=entry.name, url=entry.url, category=entry.section, description=entry.description,
            why=(pr.get("body") or "")[:1200], affiliation="unknown",
        )
        existing = [e.name for e in section.entries if e is not entry]
        results.append((entry, link, ai.assess(cfg, sub, categories, existing, link)))

    broken = any(link.ok is False for _, link, _ in results)
    rejected = any(a.verdict == "reject" for *_, a in results)
    all_good = results and all(
        a.verdict == "approve" and not a.error and link.ok and a.confidence >= cfg.auto_approve_min_confidence
        for _, link, a in results
    )
    if errors or broken:
        status = "needs_changes"
    elif rejected:
        status = "ai_rejected"
    elif all_good and not automation and not removed and len(added) <= MAX_AI_ENTRIES_PER_PR:
        status = "ai_approved"
    else:
        status = "ai_needs_review"

    set_status_label(cfg, gh, number, labels, status)
    gh.upsert_comment(number, REVIEW_MARKER, render_review(status, errors, warnings, results, added, removed, automation))
    print(f"PR #{number}: {status}")


def render_review(status, errors, warnings, results, added, removed, automation):
    headline = {
        "ai_approved": "✅ Every added entry passed the automated checks.",
        "ai_needs_review": "🔍 Needs a maintainer's eyes.",
        "ai_rejected": "🚫 At least one added entry doesn't look like a fit.",
        "needs_changes": "✏️ Some things need fixing.",
    }[status]
    out = ["### Automated list review", "", f"**{headline}**", ""]
    if errors:
        out += ["**README check failures introduced by this PR**", ""]
        out += [f"- Line {p.line}: {p.message}" if p.line else f"- {p.message}" for p in errors] + [""]
    if automation:
        out += ["⚠️ This PR changes automation files, so a maintainer must review it manually:", ""]
        out += [f"- `{f}`" for f in automation] + [""]
    if removed:
        out += ["**Removed entries**", ""] + [f"- [{e.name}]({e.url}) ({e.section})" for e in removed] + [""]
    if results:
        out += ["| Entry | Section | Link | Verdict | Notes |", "|---|---|---|---|---|"]
        for entry, link, a in results:
            icon = "✅" if link.ok else "⚠️" if link.ok is None else "❌"
            verdict = "unavailable" if a.error else f"{a.verdict.replace('_', ' ')} ({a.confidence:.2f})"
            notes = "; ".join([*a.reasons[:2], *[f"⚠️ {c}" for c in a.concerns[:2]]]).replace("|", "/")
            if a.category and a.category != entry.section:
                notes = f"Suggests **{a.category}**. " + notes
            out.append(f"| [{readme.sanitize_name(entry.name)}]({entry.url}) | {entry.section} | {icon} {link.summary()} | {verdict} | {notes} |")
        out.append("")
    if len(added) > len(results):
        out += [f"Only the first {len(results)} of {len(added)} added entries were reviewed automatically.", ""]
    if not added and not removed and not errors:
        out += ["No list entries were added or removed.", ""]
    if warnings:
        out += ["<details><summary>Style suggestions</summary>", ""]
        out += [f"- Line {p.line}: {p.message}" for p in warnings[:20]] + ["", "</details>", ""]
    out.append("_The automated review is advisory. A maintainer makes the final call._")
    return "\n".join(out)


def refresh_bot_prs(cfg, gh):
    """Rebuild open bot PRs on top of the latest default branch so they never conflict."""
    base = gh.default_branch()
    main_sha = gh.branch_sha(base)
    main_text, _ = gh.get_file(cfg.readme, main_sha)
    for pr in gh.open_prs():
        head_repo = (pr["head"].get("repo") or {}).get("full_name")
        branch = pr["head"]["ref"]
        if head_repo != gh.repo or not branch.startswith(cfg.bot_branch_prefix):
            continue
        head_sha = pr["head"]["sha"]
        before_text, _ = gh.get_file(cfg.readme, gh.merge_base(main_sha, head_sha))
        head_text, _ = gh.get_file(cfg.readme, head_sha)
        removed, added = readme.diff_entries(before_text, head_text, cfg.meta_sections)
        try:
            new_text, missing = readme.apply_entry_diff(main_text, removed, added, cfg.meta_sections)
        except ValueError as e:
            missing, problem = [], str(e)
        else:
            problem = f"{missing[0].name} changed on the list in the meantime" if missing else ""
        if not problem and new_text == main_text:
            gh.comment(pr["number"], "Closing: the list already includes this change.")
            gh.update_pr(pr["number"], state="closed")
            continue
        if not problem and (errors := readme.new_errors(main_text, new_text, cfg.max_description_length, cfg.meta_sections)):
            problem = "; ".join(p.message for p in errors)
        if problem:
            gh.comment(pr["number"], f"Couldn't rebase this change automatically ({problem}). "
                                     "Edit the original issue to re-run it, or a maintainer can fix the branch.")
            continue
        if new_text == head_text:
            continue
        gh.point_branch(branch, main_sha)
        _, file_sha = gh.get_file(cfg.readme, branch)
        gh.put_file(cfg.readme, branch, new_text, file_sha, f"{pr['title']} (rebased on {base})")
        print(f"Refreshed PR #{pr['number']}")


# --------------------------------------------------------------------------- local

def validate_local(cfg, apply_fix=False):
    readme_path = REPO_ROOT / cfg.readme
    text = readme_path.read_text(encoding="utf-8")
    if apply_fix:
        text = readme.fix(text, cfg.meta_sections)
        readme_path.write_text(text, encoding="utf-8")
    categories = readme.Readme(text, cfg.meta_sections).category_titles

    problems = readme.validate(text, cfg.max_description_length, cfg.meta_sections)
    for form_file, extra in ((cfg.issue_form, (forms.NOT_SURE,)), (cfg.update_form, ())):
        form_path = REPO_ROOT / form_file
        if not form_path.exists():
            continue
        form = form_path.read_text(encoding="utf-8")
        if apply_fix:
            form = forms.sync_form_categories(form, categories, extra)
            form_path.write_text(form, encoding="utf-8")
        if forms.form_categories(form) != [*categories, *extra]:
            problems.append(readme.Problem(
                f"Category dropdown in {form_file} doesn't match the README sections. "
                "Run `python3 -m awesome_bot validate --fix`."))

    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    for p in problems:
        if in_actions:
            location = f"file={cfg.readme},line={p.line}" if p.line else f"file={cfg.readme}"
            print(f"::{p.level} {location}::{p.message}")
        else:
            print(f"{cfg.readme}:{p.line or 1}: {p.level}: {p.message}")
    errors = sum(p.level == "error" for p in problems)
    print(f"{errors} error(s), {len(problems) - errors} warning(s).")
    return 1 if errors else 0
