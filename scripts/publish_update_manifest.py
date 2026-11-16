"""Generate a validated update feed from published Releases; optionally push gh-pages.

The client never calls the GitHub API. This maintainer-only tool uses gh's login.
Run after uploading and verifying Release assets. No token is written to the feed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from valorant_toxic_tamer.config_manager import atomic_json
from valorant_toxic_tamer.update_manifest import validate_manifest
from valorant_toxic_tamer.update_protocol import version_tuple
from valorant_toxic_tamer.update_settings import REPOSITORY


def build_manifest(releases, digest_resolver=None):
    candidates = {"stable": [], "beta": []}
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+(?:-beta(?:\.[1-9]\d*)?)?", tag):
            continue
        version = version_tuple(tag)
        if type(release.get("prerelease")) is not bool or release["prerelease"] != (version[3] == 0):
            raise ValueError(f"Release 渠道标记与版本号不符：{tag}")
        candidates["stable" if version[3] else "beta"].append(release)
    if not candidates["stable"]:
        raise ValueError("没有已发布的正式版，不能生成更新清单。")
    channels = {}
    for channel, items in candidates.items():
        if not items:
            channels[channel] = None
            continue
        release = max(items, key=lambda item: version_tuple(item["tag_name"]))
        tag = release["tag_name"]
        name = f"ValorantToxicTamer-Setup-{tag}.exe"
        assets = [asset for asset in release.get("assets", [])
                  if asset.get("name") == name and asset.get("state") == "uploaded"]
        if len(assets) != 1:
            raise ValueError(f"最新 {channel} Release 缺少唯一的已上传安装包：{name}")
        asset = assets[0]
        digest = asset.get("digest")
        if digest is None and digest_resolver is not None:
            digest = digest_resolver(tag, asset)
        channels[channel] = {"version": tag, "url": asset.get("browser_download_url"),
                             "size": asset.get("size"), "digest": digest}
    payload = {"schema": 1, "channels": channels}
    validate_manifest(payload)
    return payload


def run(args, **kwargs):
    if kwargs.get("text"):
        kwargs.setdefault("encoding", "utf-8")
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, **kwargs).stdout


def publish(payload):
    """Commit with an isolated index, preserve other files, and never force-push."""
    remote = run(["git", "remote", "get-url", "origin"], text=True).strip()
    if remote.casefold().removesuffix(".git") != f"https://github.com/{REPOSITORY}".casefold():
        raise ValueError("origin 不是本项目的官方仓库，停止发布。")
    refs = run(["git", "ls-remote", "--heads", "origin", "refs/heads/gh-pages"], text=True).split()
    parent = refs[0] if refs else None
    if parent:
        run(["git", "fetch", "origin", "refs/heads/gh-pages"])
        if run(["git", "rev-parse", "FETCH_HEAD"], text=True).strip() != parent:
            raise ValueError("gh-pages 已发生并发变化，请重新生成并发布。")
        previous = validate_manifest(json.loads(run(["git", "show", f"{parent}:updates.json"], text=True)))
        current = validate_manifest(payload)
        for channel, release in previous.items():
            if channel not in current or version_tuple(current[channel].version) < version_tuple(release.version):
                raise ValueError("新清单落后于已发布清单，请重新读取 Release 后再发布。")
    with tempfile.TemporaryDirectory(prefix="vtt-feed-index-") as directory:
        environment = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        run(["git", "read-tree", parent] if parent else ["git", "read-tree", "--empty"], env=environment)
        content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        for name, data in (("updates.json", content), (".nojekyll", b"")):
            blob = run(["git", "hash-object", "-w", "--stdin"], input=data).decode().strip()
            run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}"], env=environment)
        tree = run(["git", "write-tree"], env=environment, text=True).strip()
        if parent and tree == run(["git", "rev-parse", f"{parent}^{{tree}}"], text=True).strip():
            return parent
        arguments = ["git", "commit-tree", tree, "-m", "chore:更新官方版本清单"]
        if parent:
            arguments.extend(["-p", parent])
        commit = run(arguments, text=True).strip()
    run(["git", "push", "origin", f"{commit}:refs/heads/gh-pages"])
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/updates/updates.json")
    parser.add_argument("--publish", action="store_true", help="Push the generated feed to gh-pages without changing the current branch")
    args = parser.parse_args()
    gh = shutil.which("gh") or str(ROOT / ".tools/gh.exe")
    try:
        pages = json.loads(run([gh, "api", "--paginate", "--slurp", f"repos/{REPOSITORY}/releases?per_page=100"], text=True))
        releases = [release for page in pages for release in page]

        def resolve_digest(tag, asset):
            with tempfile.TemporaryDirectory(prefix="vtt-feed-asset-") as directory:
                run([gh, "release", "download", tag, "--repo", REPOSITORY,
                     "--pattern", asset["name"], "--dir", directory])
                path = Path(directory) / asset["name"]
                if path.stat().st_size != asset["size"]:
                    raise ValueError("下载的安装包大小与 Release 不符，停止发布清单。")
                with path.open("rb") as stream:
                    return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()

        payload = build_manifest(releases, resolve_digest)
        atomic_json(args.output, payload)
        print(str(args.output.resolve()))
        if args.publish:
            print("gh-pages:", publish(payload))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
