"""Command-line entry point: `PYTHONPATH=.github/scripts python3 -m awesome_bot <command>`."""

import argparse
import sys

from . import commands, config


def main(argv=None):
    parser = argparse.ArgumentParser(prog="awesome_bot")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="lint README.md and the issue form")
    validate.add_argument("--fix", action="store_true", help="sort entries, rebuild the ToC and sync the form")
    issue = sub.add_parser("process-issue", help="triage a submission issue and open a PR if approved")
    issue.add_argument("--issue", type=int, required=True)
    issue.add_argument("--force", action="store_true", help="treat as maintainer-approved")
    pr = sub.add_parser("review-pr", help="post an advisory review on a pull request")
    pr.add_argument("--pr", type=int, required=True)
    sub.add_parser("refresh-prs", help="rebuild open bot PRs on the latest default branch")
    args = parser.parse_args(argv)

    cfg = config.load()
    if args.command == "validate":
        return commands.validate_local(cfg, args.fix)
    gh = commands.github()
    if args.command == "process-issue":
        commands.process_issue(cfg, gh, args.issue, args.force)
    elif args.command == "review-pr":
        commands.review_pr(cfg, gh, args.pr)
    elif args.command == "refresh-prs":
        commands.refresh_bot_prs(cfg, gh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
