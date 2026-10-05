# Maintainer guide

This list runs itself as much as possible. Contributors fill in an issue form to suggest a resource or to fix or remove an entry. A bot checks it and asks GitHub Copilot whether it belongs, and approved changes arrive as ready-to-merge pull requests. You mostly just click **Merge**, or let the bot merge for you.

## How it works

```
Issue forms: "Suggest a resource"            Pull request from a contributor
             "Fix or remove an entry"
        │                                              │
        ▼                                              ▼
 submissions.yml                                pr-review.yml
  • finds the entry (updates), checks links,     • README checks (format, order, duplicates, ToC)
    duplicates and the section                   • link check + Copilot review of each added entry
  • Copilot review → JSON verdict                • one summary comment + a label (never merges)
  • builds the entry from the fixed template
  • comment (with a diff for updates) + label
        │
        ├─ approved (high confidence) ─▶ bot opens PR "Add/Update/Move/Remove <name>" (Closes #issue)
        ├─ needs review ─▶ you add the `approved` label ─▶ bot opens the PR
        └─ needs changes / rejected ─▶ submitter edits the issue ─▶ re-checked automatically

 lint.yml             every PR and push: bot validator, unit tests, awesome-lint
 refresh-bot-prs.yml  after README changes: rebuilds open bot PRs on the latest main (no conflicts)
 link-check.yml       weekly: lychee dead-link scan, opens/updates a "Broken links" issue
```

All the logic lives in `.github/scripts/awesome_bot/`: plain Python 3 with no dependencies, plus unit tests. List-specific settings are in `.github/awesome-bot.json`.

## One-time setup

1. **Let Actions open pull requests.** Settings → Actions → General → Workflow permissions: choose **Read and write permissions** and tick **Allow GitHub Actions to create and approve pull requests**. Without this, the bot can comment and label but can't open PRs. Its comment will tell you so.
2. **Copilot for the AI review.** The workflows run the [Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli-in-actions) with the built-in `GITHUB_TOKEN` (`copilot-requests: write`). In a personal repository, usage is billed to the **repository owner's Copilot plan**. Copilot Free works (Auto model, monthly allowance). A paid plan lets you pin a model with the `COPILOT_MODEL` repository variable. No secrets are needed. Alternatives:
   - Bill another seat: add a fine-grained PAT with the **Copilot Requests** permission as the `COPILOT_GITHUB_TOKEN` secret.
   - Use your own model provider: set the variables `COPILOT_PROVIDER_BASE_URL` (for example `https://api.openai.com/v1` or `https://api.anthropic.com`), `COPILOT_PROVIDER_TYPE` (`openai`, `anthropic` or `azure`) and `COPILOT_MODEL`, plus the `COPILOT_PROVIDER_API_KEY` secret.
   - If none of these work, the bot still runs every other check. Submissions are just labelled `ai: needs review` for you to decide.
3. **Repository details** (awesome-lint checks them): a description, the topics `awesome` and `awesome-list`, and the CC0 license (already in `LICENSE`).
4. *Optional:* **Copilot code review** on every PR: Settings → Rules → Rulesets → New branch ruleset → target `main` → tick **Automatically request Copilot code review**. It reads `.github/copilot-instructions.md`. Note that it only reviews PRs whose *authors* have Copilot code review access, so most outside contributors are skipped. `pr-review.yml` is what covers everyone.
5. *Optional:* **Hands-off merging.** Set `"auto_merge": true` in `.github/awesome-bot.json` and the bot squash-merges its own PRs as soon as a submission is approved. The bot validates the README itself before merging. If you add branch protection with required status checks, keep `auto_merge` off: PRs opened with `GITHUB_TOKEN` wait for a maintainer to click **Approve and run workflows** before CI runs.

## Day to day

| You see | Do this |
|---|---|
| A bot PR "Add …" | Read the entry in the PR body and merge. (Approve the CI run first if GitHub asks.) |
| Issue labelled `ai: needs review` | Decide. Add `approved` to accept (the bot opens the PR) or close the issue to decline. |
| A bot PR "Remove …" | Check the reason in the PR body. Removals are never merged automatically, even with `auto_merge` on. |
| Issue labelled `ai: rejected` | Usually close it. Add `approved` if the bot got it wrong. |
| Issue labelled `needs changes` | Nothing. The submitter edits the issue and it's re-checked. |
| Wrong category or wording on an issue | Edit the issue form fields yourself. The bot re-checks and updates its PR. |
| Contributor PR labelled `ai: approved` | Skim and merge. |
| "Broken links" issue | Fix or remove the entries, then close it. |

You can also run any check locally:

```sh
export PYTHONPATH=.github/scripts
python3 -m awesome_bot validate          # lint README.md and the issue form
python3 -m awesome_bot validate --fix    # sort entries, rebuild the ToC, sync the form's category dropdown
python3 -m unittest discover -s .github/scripts/tests
```

**Adding a section:** add a `## Heading` to the README with at least one entry, then run `validate --fix`. Sub-headings (`###`) aren't supported, so keep sections flat.

## Labels

The bot creates these automatically on first run.

| Label | Meaning |
|---|---|
| `submission` | Added by the "Suggest a resource" form. |
| `entry update` | Added by the "Fix or remove an entry" form. Only issues with one of these two labels are processed. |
| `approved` | **Maintainers only.** Forces the bot to open the PR whatever the automated verdict. |
| `ai: approved` / `ai: needs review` / `ai: rejected` | Automated verdict (issues and PRs). |
| `needs changes` | A blocking problem: broken link, duplicate, bad format. |
| `duplicate` | Already on the list. |

## Settings (`.github/awesome-bot.json`)

| Key | Default | Meaning |
|---|---|---|
| `list_name`, `scope` | | Name and scope of the list. `scope` is the main instruction the AI judges relevance against, so be specific about what's out of scope. |
| `model` | `""` | Copilot CLI model name. Empty means Auto (required on Copilot Free). The `COPILOT_MODEL` variable overrides it. |
| `auto_open_pr` | `true` | Open a PR automatically when the automated review approves with high confidence. If `false`, only the `approved` label opens PRs. |
| `auto_merge` | `false` | Squash-merge bot PRs immediately. |
| `auto_approve_min_confidence` | `0.8` | Minimum AI confidence for automatic approval. |
| `max_description_length` | `160` | Longest allowed entry description. |
| `meta_sections` | Contents, Contributing, Footnotes | `##` sections that aren't categories. |

## Security model

- Submissions and PR contents are untrusted. They reach the model only as data, and the model runs with **no tools, no MCP servers and an empty working directory** (`--available-tools=none --disable-builtin-mcps`). The worst a prompt injection can do is skew the JSON verdict. That verdict is validated, its text is sanitised before it's posted, and it can't trigger a merge unless you turn on `auto_merge`.
- `pr-review.yml` uses `pull_request_target` but only checks out the base branch. The PR's README is fetched through the API and parsed as text, never executed.
- Contributor PRs are never merged automatically, and PRs that touch `.github/` are always flagged for manual review.
- Only people with Triage access or higher can add labels, so only maintainers can apply `approved`. If the author edits an approved issue afterwards, the bot removes `approved` and a maintainer has to approve the new version.
- The bot only edits `README.md`, on `awesome-bot/issue-*` branches.
- Removal requests are never merged automatically. A removal PR is opened without a maintainer only when the entry's current link is verifiably dead.

## Costs

Each submission or update request (and each edit of one) uses one Copilot request, and each contributor PR push uses one request per added entry (at most 10). Everything else is ordinary Actions minutes, which are free for public repositories.

## Troubleshooting

- **The bot never comments:** check the Actions tab and make sure workflows are enabled. The bot recognises issues made with either form even if their label is missing. To re-check any issue by hand, open Actions → **Submissions** → **Run workflow** and enter the issue number.
- **"Automated review was unavailable":** Copilot isn't reachable with the current token or plan. The comment includes the CLI's error. See setup step 2.
- **"Couldn't open a pull request":** see setup step 1.
- **awesome-lint fails on "github" rules:** add the repository description and topics (setup step 3).
