"""Loads `.github/awesome-bot.json`, the only file that differs between lists."""

import json
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / ".github" / "awesome-bot.json"


@dataclass
class Config:
    list_name: str
    scope: str
    readme: str = "README.md"
    issue_form: str = ".github/ISSUE_TEMPLATE/add-resource.yml"
    meta_sections: list = field(default_factory=lambda: ["Contents", "Contributing", "Footnotes"])
    model: str = ""  # Copilot CLI model name; empty = "auto"
    max_description_length: int = 160
    auto_open_pr: bool = True
    auto_merge: bool = False
    auto_approve_min_confidence: float = 0.8
    bot_branch_prefix: str = "awesome-bot/issue-"
    labels: dict = field(default_factory=dict)

    def label(self, key):
        return self.labels.get(key, key.replace("_", " "))


def load(path=CONFIG_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Config(**data)
