# Contributing

Thanks for helping make this list better! Please note that this project has a [Code of Conduct](code-of-conduct.md). By participating, you agree to follow it.

## The easy way: open an issue

**[Suggest a resource →](https://github.com/blackveilprecision/awesome-makera/issues/new?template=add-resource.yml)**

Fill in the form: name, link, category and a one-line description. You don't need Git or Markdown. Then a bot:

1. checks the link works and that it isn't already on the list,
2. runs an automated relevance review using GitHub Copilot,
3. posts the result as a comment on your issue and labels it,
4. opens the pull request that adds the entry when it's approved, either by the automated review (high confidence) or by a maintainer adding the `approved` label.

If the bot asks for changes, just **edit your issue**. It re-checks on every edit. The automated review is only advisory: a maintainer always makes the final call.

To fix or remove an existing entry, use the **[Fix or remove an entry](https://github.com/blackveilprecision/awesome-makera/issues/new?template=update-entry.yml)** form.

## What belongs here

- Things that are genuinely useful to people who own, run, upgrade or are thinking about buying a Makera machine (Carvera, Carvera Air, Z1 and newer models).
- It should be Makera-specific. General CNC resources belong in [Awesome CNC](https://github.com/blackveilprecision/awesome-cnc) instead.
- Open-source projects, notable commercial products, guides, reference material, channels and communities.
- Projects should be usable and maintained. A brand-new project with no documentation or releases is usually better added later.
- Link to the resource itself: the official site, documentation or repository. No affiliate links, marketplace listings, URL shorteners or SEO articles.
- Self-promotion is welcome when the resource is useful, but please disclose your affiliation in the form.

## Entry style

```markdown
- [Name](https://link) - Description.
```

- One sentence. Start with a capital letter and end with a period.
- Don't start with "A", "An" or the name of the resource, and skip marketing words like "best" or "ultimate".
- Mention "Open-source" or "Commercial" when it's relevant.
- Keep it under 160 characters.
- Entries are sorted alphabetically within each section.

## Sending a pull request instead

You're welcome to edit `README.md` directly:

1. Add your entry in alphabetical order within the right section.
2. Run the checks locally (Python 3, no dependencies):

   ```sh
   PYTHONPATH=.github/scripts python3 -m awesome_bot validate        # report problems
   PYTHONPATH=.github/scripts python3 -m awesome_bot validate --fix  # sort entries and rebuild the table of contents
   ```

3. Open the pull request. A bot posts an automated review of each added entry, and CI runs [awesome-lint](https://github.com/sindresorhus/awesome-lint).

Suggesting a new section? Add the `## Heading` to the README and run `validate --fix`. That updates the table of contents and the category dropdown in the issue form.
