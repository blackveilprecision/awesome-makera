# Copilot instructions for this repository

This repository is a curated "awesome list" about Makera desktop CNC machines (Carvera, Carvera Air, Z1 and newer models). The product is `README.md`. Everything under `.github/` is automation that maintains it.

## When reviewing pull requests that change README.md

Check every added or changed entry and flag:

- **Format:** each entry must be exactly `- [Name](https://link) - Description.` with a plain ` - ` separator (not an en or em dash).
- **Description style:** one sentence, starts with a capital letter, ends with a period, under 160 characters. It must not start with "A", "An" or the entry's own name, and must not use marketing superlatives ("best", "ultimate", "powerful").
- **Order:** entries are alphabetical (case-insensitive) within each `##` section.
- **Relevance:** the resource must be specific to Makera machines: software, controllers, firmware, CAM workflows and post-processors, upgrades, printable mods, tooling, guides, videos or communities. Flag generic CNC content with no Makera angle (it belongs in Awesome CNC), general 3D printing, reseller and off-topic links.
- **Link quality:** link to the official site, docs or repository. Flag affiliate parameters, marketplace listings (Amazon, AliExpress, eBay), URL shorteners, tracking parameters (`utm_*`) and plain `http://` when `https://` works.
- **Duplicates:** the same project already listed elsewhere in the README, even under a different URL.
- **Placement:** an entry in the wrong section.
- **Table of contents:** a new `##` section also needs a `## Contents` link and a matching option in `.github/ISSUE_TEMPLATE/add-resource.yml` (`python3 -m awesome_bot validate --fix` does both).

Do not comment on the wording of the license, code of conduct or contributing guide unless the PR changes them.

## When a pull request changes files under .github/

Treat it as a security-sensitive change and review it closely:

- workflows triggered by `pull_request_target` must never check out or execute code from the PR head;
- workflow permissions should stay minimal;
- the AI step in `.github/scripts/awesome_bot/ai.py` must keep running the Copilot CLI with `--available-tools=none` and `--disable-builtin-mcps`.

## When working on the automation code

- Python 3 standard library only (no third-party dependencies), so workflows need no install step.
- Run `PYTHONPATH=.github/scripts python3 -m unittest discover -s .github/scripts/tests` and `PYTHONPATH=.github/scripts python3 -m awesome_bot validate` before finishing.
