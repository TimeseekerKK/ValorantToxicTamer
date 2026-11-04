#!/usr/bin/env python3
"""Read-only release planner. Writes no versions, tags, commits or releases."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

NUMBER = r"(0|[1-9][0-9]*)"
VERSION_RE = re.compile(rf"v?{NUMBER}\.{NUMBER}\.{NUMBER}(?:-beta\.([1-9][0-9]*))?")
LEGACY_RE = re.compile(rf"v{NUMBER}\.{NUMBER}\.{NUMBER}-beta")
REPOSITORY = "TimeseekerKK/ValorantToxicTamer"


def version(value, *, legacy=False):
    match = VERSION_RE.fullmatch(value)
    if match:
        return tuple(map(int, match.groups()[:3])), int(match[4]) if match[4] else None
    if legacy and (match := LEGACY_RE.fullmatch(value)):
        return tuple(map(int, match.groups())), 0
    raise ValueError(f"Invalid version: {value!r}")


def tag_version(value):
    if not isinstance(value, str) or not value.startswith("v"):
        return None
    try:
        return version(value, legacy=True)
    except ValueError:
        return None


def base_text(base):
    return ".".join(map(str, base))


def tag_text(base, beta=None):
    text = "v" + base_text(base)
    return text if beta is None else text + ("-beta" if beta == 0 else f"-beta.{beta}")


def bump(base, level):
    index = {"major": 0, "minor": 1, "patch": 2}[level]
    parts = list(base)
    parts[index] += 1
    parts[index + 1:] = [0] * (2 - index)
    return tuple(parts)


def command(args, *, empty_tags=False):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=60)
    except FileNotFoundError as error:
        raise ValueError(f"Required executable not found: {args[0]}; prepare it before release planning.") from error
    if result.returncode and not (empty_tags and result.returncode == 1 and not result.stdout):
        raise ValueError(f"{args[0]} {args[1]} failed; remote state was not verified. Check connectivity/authentication.")
    return result.stdout.strip()


def tag_refs(output):
    refs = {}
    peeled = {}
    for line in output.splitlines():
        sha, ref = line.split(None, 1)
        if not ref.startswith("refs/tags/"):
            continue
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name[:-3]] = sha
        else:
            refs[name] = sha
    refs.update(peeled)
    return refs


def collect_snapshot(remote, repository, branch):
    actual = command(["git", "branch", "--show-current"])
    if actual != branch:
        raise ValueError(f"Actual branch {actual!r} does not match {branch!r}.")
    url = command(["git", "remote", "get-url", remote])
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?", url)
    if not match or match[1].casefold() != repository.casefold():
        raise ValueError("Publishing remote does not match the expected GitHub repository.")
    local = tag_refs(command(["git", "show-ref", "--tags", "--dereference"], empty_tags=True))
    published = tag_refs(command(["git", "ls-remote", "--tags", remote]))
    pages = json.loads(command([
        "gh", "api", "--hostname", "github.com", "--method", "GET",
        f"repos/{repository}/releases?per_page=100", "--paginate", "--slurp",
    ]))
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ValueError("Invalid paginated GitHub releases response.")
    return {
        "branch": branch, "repository": repository,
        "local_tags": local, "remote_tags": published,
        "releases": [release for page in pages for release in page],
    }


def history(snapshot):
    local, remote = snapshot["local_tags"], snapshot["remote_tags"]
    if not isinstance(local, dict) or not isinstance(remote, dict):
        raise ValueError("Invalid tag inventory.")
    for tag in local.keys() & remote.keys():
        if tag_version(tag) and local[tag] != remote[tag]:
            raise ValueError(f"Local and remote tag disagree: {tag}")
    releases = {}
    published = {}
    for release in snapshot["releases"]:
        tag = release["tag_name"]
        if tag in releases or type(release["draft"]) is not bool or type(release["prerelease"]) is not bool:
            raise ValueError("Invalid or duplicate release record.")
        releases[tag] = release
        parsed = tag_version(tag)
        if parsed and not release["draft"]:
            if tag not in remote:
                raise ValueError(f"Published release has no remote tag: {tag}")
            if release["prerelease"] != (parsed[1] is not None):
                raise ValueError(f"Release channel conflicts with its tag: {tag}")
            published[tag] = parsed
    stable = [base for base, beta in published.values() if beta is None]
    if not stable:
        raise ValueError("No published stable Release; establish an explicit initial release first.")
    reserved = set(local) | set(remote) | set(releases)
    return local, remote, releases, published, max(stable), reserved


def plan(snapshot, current, *, level=None, promote=None, resume=None, expected_commit=None):
    if sum(value is not None for value in (level, promote, resume)) != 1:
        raise ValueError("Select exactly one of bump, promote or resume.")
    branch = snapshot["branch"]
    if branch not in ("main", "Beta"):
        raise ValueError("Only main and Beta are release branches.")
    current_base, current_beta = version(current)
    local, remote, releases, published, stable, reserved = history(snapshot)
    state = "planned"
    source = None

    if resume:
        parsed = tag_version(resume)
        if parsed is None or parsed[1] == 0 or (parsed[1] is not None) != (branch == "Beta"):
            raise ValueError("Resume tag is invalid or belongs to another channel.")
        target, beta = parsed
        tag = tag_text(target, beta)
        if resume != tag:
            raise ValueError("Resume requires the exact canonical tag.")
        if tag in local or tag in remote:
            if not expected_commit or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected_commit):
                raise ValueError("Resuming a reserved tag requires --expected-commit with its full SHA.")
            if any(refs[tag] != expected_commit for refs in (local, remote) if tag in refs):
                raise ValueError("Resume tag points to a different commit.")
            state = "tagged"
        release = releases.get(tag)
        if release:
            if release["name"] != tag or release["prerelease"] != (branch == "Beta"):
                raise ValueError("Existing release title/channel does not match the plan.")
            state = "draft" if release["draft"] else "published"
        if target <= stable and not (state == "published" and (branch == "Beta" or target == stable)):
            raise ValueError("This version line is closed by a stable release.")
        reason = "resume-existing-plan"
    elif promote:
        if branch != "main":
            raise ValueError("Beta promotion must publish from main.")
        parsed = tag_version(promote)
        if parsed is None or parsed[1] is None or promote not in published:
            raise ValueError("Promotion requires an already published Beta release.")
        target, _ = parsed
        if target <= stable:
            raise ValueError("This Beta version line is already closed.")
        beta = None
        source = {"tag": promote, "commit": remote[promote]}
        reason = "promote-without-another-bump"
    else:
        if current_beta is not None and tag_text(current_base, current_beta) not in published:
            raise ValueError("Current Beta is not published; use --resume for an unfinished batch.")
        if branch == "main":
            if current_beta is not None:
                raise ValueError("Use --promote for Beta-to-main promotion.")
            if current_base != stable:
                raise ValueError("Current stable baseline differs from published stable; synchronize or resume first.")
            target, beta = bump(stable, level), None
            reason = "new-stable-version"
        else:
            active = [(base, number) for base, number in published.values()
                      if number is not None and base > stable]
            latest_beta = max(active) if active else None
            expected_current = (current_base, current_beta)
            # Older releases used a numeric VERSION with a bare -beta Git tag.
            legacy_current = latest_beta == (current_base, 0) and current_beta is None
            if latest_beta and expected_current != latest_beta and not legacy_current:
                raise ValueError("Beta baseline differs from the active remote line; synchronize first.")
            if not latest_beta and current_base != stable and not (current_beta is not None and current_base <= stable):
                raise ValueError("Beta baseline differs from stable; synchronize or resume first.")
            target = max(bump(stable, level), latest_beta[0]) if latest_beta else bump(stable, level)
            numbers = [parsed[1] for tag in reserved if (parsed := tag_version(tag))
                       and parsed[0] == target and parsed[1] is not None]
            beta = max(numbers, default=0) + 1
            reason = "continue-beta-line" if latest_beta and target == latest_beta[0] else "open-beta-line"

    tag = tag_text(target, beta)
    if not resume and tag in reserved:
        raise ValueError(f"Target tag/release already reserved: {tag}; inspect it and use --resume, never overwrite.")
    return {
        "branch": branch, "repository": snapshot["repository"],
        "baseline": "v" + base_text(stable), "current_version": current,
        "version": tag.removeprefix("v"), "base_version": base_text(target),
        "tag": tag, "title": tag,
        "prerelease": branch == "Beta", "latest": branch == "main",
        "status": state, "reason": reason, "promotion_source": source,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True, choices=("main", "Beta"))
    parser.add_argument("--current", required=True, help="Version at the start of this task, before editing VERSION")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--bump", choices=("major", "minor", "patch"))
    modes.add_argument("--promote", help="Exact published Beta tag; caller must verify no added software changes")
    modes.add_argument("--resume", help="Exact target tag recorded for this same batch")
    parser.add_argument("--expected-commit")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--repo", default=REPOSITORY)
    parser.add_argument("--snapshot", type=Path, help="Offline test fixture only; never authorizes publication")
    args = parser.parse_args(argv)
    try:
        snapshot = (json.loads(args.snapshot.read_text(encoding="utf-8")) if args.snapshot
                    else collect_snapshot(args.remote, args.repo, args.branch))
        if snapshot["branch"] != args.branch or snapshot["repository"].casefold() != args.repo.casefold():
            raise ValueError("Snapshot repository/branch does not match the requested release.")
        result = plan(snapshot, args.current, level=args.bump, promote=args.promote,
                      resume=args.resume, expected_commit=args.expected_commit)
        result.update(remote=args.remote, offline=bool(args.snapshot))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
