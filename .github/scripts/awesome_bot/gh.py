"""Minimal GitHub REST client (stdlib only, so workflows need no dependency install)."""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


class GitHubError(Exception):
    def __init__(self, status, message):
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status


class GitHub:
    def __init__(self, token, repo):
        self.token = token
        self.repo = repo
        self._default_branch = None

    def request(self, method, path, body=None, params=None):
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "awesome-bot",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise GitHubError(e.code, e.read().decode("utf-8", "replace")[:500]) from e

    def paginate(self, path, params=None):
        page, items = 1, []
        while True:
            batch = self.request("GET", path, params={**(params or {}), "per_page": 100, "page": page})
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1

    def r(self, suffix=""):
        return f"/repos/{self.repo}{suffix}"

    # Repository contents
    def default_branch(self):
        if self._default_branch is None:
            self._default_branch = self.request("GET", self.r())["default_branch"]
        return self._default_branch

    def get_file(self, path, ref, repo=None):
        data = self.request("GET", f"/repos/{repo or self.repo}/contents/{path}", params={"ref": ref})
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]

    def branch_sha(self, branch):
        try:
            return self.request("GET", self.r(f"/git/ref/heads/{branch}"))["object"]["sha"]
        except GitHubError as e:
            if e.status == 404:
                return None
            raise

    def point_branch(self, branch, sha):
        """Create `branch` at `sha`, or force-move it there if it exists."""
        if self.branch_sha(branch):
            self.request("PATCH", self.r(f"/git/refs/heads/{branch}"), {"sha": sha, "force": True})
        else:
            self.request("POST", self.r("/git/refs"), {"ref": f"refs/heads/{branch}", "sha": sha})

    def merge_base(self, base, head):
        return self.request("GET", self.r(f"/compare/{base}...{head}"))["merge_base_commit"]["sha"]

    def put_file(self, path, branch, text, sha, message):
        self.request("PUT", self.r(f"/contents/{path}"), {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode(),
            "sha": sha,
            "branch": branch,
        })

    # Issues and comments
    def get_issue(self, number):
        return self.request("GET", self.r(f"/issues/{number}"))

    def comments(self, number):
        return self.paginate(self.r(f"/issues/{number}/comments"))

    def comment(self, number, body):
        return self.request("POST", self.r(f"/issues/{number}/comments"), {"body": body})

    def upsert_comment(self, number, marker, body):
        """Keep a single bot-owned comment per issue/PR, identified by a hidden marker."""
        body = f"{marker}\n{body}"
        for c in self.comments(number):
            if marker in (c.get("body") or "") and c["user"]["type"] == "Bot":
                return self.request("PATCH", self.r(f"/issues/comments/{c['id']}"), {"body": body})
        return self.comment(number, body)

    def add_labels(self, number, labels):
        if labels:
            self.request("POST", self.r(f"/issues/{number}/labels"), {"labels": sorted(labels)})

    def remove_label(self, number, label):
        try:
            self.request("DELETE", self.r(f"/issues/{number}/labels/{urllib.parse.quote(label, safe='')}"))
        except GitHubError as e:
            if e.status != 404:
                raise

    def ensure_labels(self, definitions):
        existing = {l["name"].casefold() for l in self.paginate(self.r("/labels"))}
        for name, (color, description) in definitions.items():
            if name.casefold() not in existing:
                try:
                    self.request("POST", self.r("/labels"), {"name": name, "color": color, "description": description})
                except GitHubError as e:
                    if e.status != 422:  # created concurrently
                        raise

    # Pull requests
    def get_pr(self, number):
        return self.request("GET", self.r(f"/pulls/{number}"))

    def pr_files(self, number):
        return self.paginate(self.r(f"/pulls/{number}/files"))

    def open_prs(self):
        return self.paginate(self.r("/pulls"), {"state": "open"})

    def find_open_pr(self, branch):
        owner = self.repo.split("/")[0]
        prs = self.request("GET", self.r("/pulls"), params={"state": "open", "head": f"{owner}:{branch}"})
        return prs[0] if prs else None

    def create_pr(self, title, head, base, body):
        return self.request("POST", self.r("/pulls"), {"title": title, "head": head, "base": base, "body": body})

    def update_pr(self, number, **fields):
        return self.request("PATCH", self.r(f"/pulls/{number}"), fields)

    def merge_pr(self, number, title):
        return self.request("PUT", self.r(f"/pulls/{number}/merge"), {"merge_method": "squash", "commit_title": title})
