#!/usr/bin/env python3
"""Rebuild the writing and commits sections in the profile README."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
WRITING = ROOT / "writing.yml"
TZ = ZoneInfo("Asia/Shanghai")
USER = "lyinet"
SKIP_REPOS = {f"{USER}/{USER}"}
MAX_POSTS = 8
MAX_COMMITS = 5
MAX_COMMITS_PER_REPO = 2


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_posts(path: Path) -> list[dict]:
    if not path.exists():
        return []
    posts: list[dict] = []
    current: dict | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip() or line.strip() in {"posts:", "posts: []"}:
            continue
        title = re.match(r"\s*-\s+title:\s*(.+)$", line)
        if title:
            if current:
                posts.append(current)
            current = {"title": unquote(title.group(1))}
            continue
        field = re.match(r"\s+(date|url):\s*(.+)$", line)
        if field and current is not None:
            current[field.group(1)] = unquote(field.group(2))
    if current:
        posts.append(current)
    return [p for p in posts if p.get("title")]


def api(url: str):
    token = os.environ.get("GITHUB_TOKEN", "")
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}" if token else "",
            "Accept": "application/vnd.github+json",
            "User-Agent": "lyinet-profile-readme",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def clean_message(message: str) -> str:
    first = message.splitlines()[0].strip()
    first = re.sub(
        r"^(feat|fix|chore|docs|refactor|style|test|perf)(\([^)]+\))?:\s*",
        "",
        first,
        flags=re.I,
    )
    if len(first) > 80:
        first = first[:77] + "…"
    return first


def format_date(iso: str) -> str:
    stamp = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    return stamp.strftime("%Y-%m-%d")


def recent_commits() -> list[dict]:
    repos = api(f"https://api.github.com/users/{USER}/repos?per_page=100&sort=updated")
    collected: list[dict] = []
    for repo in repos:
        full_name = repo.get("full_name", "")
        name = repo.get("name", "")
        if repo.get("fork") or repo.get("private") or full_name in SKIP_REPOS:
            continue
        try:
            commits = api(
                f"https://api.github.com/repos/{full_name}/commits?per_page=5"
            )
        except urllib.error.HTTPError:
            continue
        taken = 0
        for commit in commits:
            if taken >= MAX_COMMITS_PER_REPO:
                break
            message = (commit.get("commit") or {}).get("message") or ""
            # Skip the profile repo's own housekeeping, already excluded.
            date = (
                (commit.get("commit") or {}).get("author") or {}
            ).get("date")
            if not date:
                continue
            collected.append(
                {
                    "repo": name,
                    "message": clean_message(message),
                    "date": format_date(date),
                    "sort": date,
                    "sha": commit.get("sha"),
                }
            )
            taken += 1
    collected.sort(key=lambda item: item["sort"], reverse=True)
    seen: set[str] = set()
    unique: list[dict] = []
    for item in collected:
        if item["sha"] in seen:
            continue
        seen.add(item["sha"])
        unique.append(item)
        if len(unique) >= MAX_COMMITS:
            break
    return unique


def render_writing(posts: list[dict]) -> str:
    if not posts:
        return "发稿之后，标题会出现在这里。"
    lines = []
    for post in posts[:MAX_POSTS]:
        title = post["title"]
        date = post.get("date", "")
        url = post.get("url")
        prefix = f"{date}  " if date else ""
        if url:
            lines.append(f"- {prefix}[{title}]({url})")
        else:
            lines.append(f"- {prefix}{title}")
    return "\n".join(lines)


def render_commits(items: list[dict]) -> str:
    if not items:
        return "最近没有新的公开提交。"
    lines = []
    for item in items:
        repo = item["repo"]
        lines.append(
            f"- [{repo}](https://github.com/{USER}/{repo})：{item['message']}（{item['date']}）"
        )
    return "\n".join(lines)


def replace_section(text: str, name: str, body: str) -> str:
    start = f"<!-- {name} starts -->"
    end = f"<!-- {name} ends -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"missing markers for {name}")
    return pattern.sub(f"{start}\n{body}\n{end}", text)


def main() -> None:
    text = README.read_text(encoding="utf-8")
    text = replace_section(text, "writing", render_writing(load_posts(WRITING)))
    text = replace_section(text, "commits", render_commits(recent_commits()))
    README.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
