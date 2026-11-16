#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Upload reviewed assets to a draft, download/verify them, then publish a preview."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

REPO = "liyaomeng202114981-ops/Felix-Proton"
TAG = "felix-proton-setup-v0.1.0-preview.1"
REQUIRED = {
    "felix-proton-setup-0.1.0-preview.1-linux.tar.gz", "SETUP_BUILDINFO.json",
    "felix-proton-uu-test-0.1.0-test.1.tar.zst", "shorin-proton-wrapper", "pasta-6aa4f88-linux-x86_64",
    "felix-proton-uu-test.1-modified-wine-source.tar.zst", "we-proton-4617d991-build-source.tar.zst",
    "we-proton-ge11-11-31-source.tar.xz", "felix-proton-test.1-dependency-sources.tar.zst",
    "SOURCE_INDEX.json", "NETWORK_SOURCES.json", "THIRD_PARTY_NOTICES.md", "NETWORK_NOTICES.md",
    "proton-wrapper-d8ca9e73-source.tar.gz", "passt-6aa4f88-source.tar.gz", "SETUP_TEST_RESULTS.md",
}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_assets(folder):
    manifest = folder / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("Missing regular checksum manifest")
    expected = {}
    for line in manifest.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not match or match[2] in expected or match[2] == "SHA256SUMS":
            raise ValueError("Invalid checksum manifest")
        expected[match[2]] = match[1]
    if not expected:
        raise ValueError("Empty release")
    if set(expected) != REQUIRED:
        raise ValueError("Release asset set differs from this version's reviewed allowlist")
    for name, digest in expected.items():
        path = folder / name
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise ValueError("Release asset mismatch: " + name)
    expected["SHA256SUMS"] = sha(manifest)
    if {p.name for p in folder.iterdir()} != set(expected):
        raise ValueError("Release directory contains unreviewed extra files")
    sources = json.loads((folder / "SOURCE_INDEX.json").read_text())
    for item in [sources["dependency_bundle"], *sources["fixed_assets"]]:
        if expected.get(item["file"]) != item["sha256"]:
            raise ValueError("Corresponding source index disagrees with release checksums")
    network = json.loads((folder / "NETWORK_SOURCES.json").read_text())
    for item in network["materials"]:
        if expected.get(item["file"]) != item["sha256"]:
            raise ValueError("Network dependency source index disagrees with release checksums")
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--gh", type=Path, required=True)
    parser.add_argument("--publish", action="store_true", help="Perform already authorized publication")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.target):
        raise ValueError("Target must be a complete source commit SHA")
    assets = args.assets.resolve(strict=True)
    expected = checked_assets(assets)
    if not args.notes.is_file() or args.notes.is_symlink():
        raise ValueError("Release notes must be a regular file")
    print(json.dumps({"repo": REPO, "tag": TAG, "target": args.target,
                      "files": expected, "publish": args.publish}), flush=True)
    if not args.publish:
        return

    def gh(*values, **kwargs):
        return subprocess.run([str(args.gh.resolve()), *values], check=True, **kwargs)

    def capture(*values):
        return gh(*values, capture_output=True, text=True).stdout

    def check_tag():
        # A collection read propagates all auth/network errors; only an absent
        # matching ref is treated as absence, never an arbitrary failed GET.
        pages = json.loads(capture("api", "repos/" + REPO + "/git/matching-refs/tags/" + TAG,
                                  "--paginate", "--slurp"))
        refs = [item for page in pages for item in page if item["ref"] == "refs/tags/" + TAG]
        if len(refs) > 1:
            raise ValueError("Ambiguous source tag")
        if refs and (refs[0]["object"]["type"] != "commit" or refs[0]["object"]["sha"] != args.target):
            raise ValueError("Existing tag points elsewhere; refuse release mutation")

    gh("auth", "status", "--hostname", "github.com")
    remote = json.loads(capture("api", "repos/" + REPO + "/commits/" + args.target))
    if remote["sha"] != args.target:
        raise ValueError("Source target is unavailable")
    check_tag()
    listing = json.loads(capture("api", "repos/" + REPO + "/releases", "--paginate", "--slurp"))
    matches = [item for page in listing for item in page if item["tag_name"] == TAG]
    if len(matches) > 1:
        raise ValueError("Ambiguous release tag")
    if matches:
        release = matches[0]
        if not release["draft"] or release["target_commitish"] != args.target:
            raise ValueError("Existing public release or a different target must not be overwritten")
    else:
        gh("release", "create", TAG, "--repo", REPO, "--target", args.target,
           "--title", "Felix-Proton 从零安装 0.1.0-preview.1", "--draft", "--prerelease",
           "--latest=false", "--notes-file", str(args.notes.resolve()))
    listing = json.loads(capture("api", "repos/" + REPO + "/releases", "--paginate", "--slurp"))
    matches = [item for page in listing for item in page if item["tag_name"] == TAG]
    if len(matches) != 1:
        raise ValueError("Expected one prepared draft")
    release = matches[0]
    if not release["draft"] or release["target_commitish"] != args.target:
        raise ValueError("Draft target differs")
    if release.get("body", "").replace("\r\n", "\n").rstrip() != args.notes.read_text().replace("\r\n", "\n").rstrip():
        raise ValueError("Existing draft notes differ from the reviewed release notes")
    uploaded = {item["name"]: item for item in release["assets"]}
    if set(uploaded) - set(expected):
        raise ValueError("Draft contains unexpected assets; retain it for review")
    for name, item in uploaded.items():
        if item.get("digest") != "sha256:" + expected[name]:
            raise ValueError("Existing draft asset differs; refuse overwrite: " + name)
    missing = [str(assets / name) for name in sorted(expected) if name not in uploaded]
    if missing:
        gh("release", "upload", TAG, *missing, "--repo", REPO)
    with tempfile.TemporaryDirectory(prefix="felix-release-download-") as directory:
        downloaded = Path(directory)
        gh("release", "download", TAG, "--repo", REPO, "--dir", directory)
        if checked_assets(downloaded) != expected:
            raise ValueError("Downloaded draft assets differ")
    check_tag()
    gh("release", "edit", TAG, "--repo", REPO, "--draft=false", "--prerelease", "--latest=false")
    tag = json.loads(capture("api", "repos/" + REPO + "/git/ref/tags/" + TAG))
    if tag["object"]["type"] != "commit" or tag["object"]["sha"] != args.target:
        raise ValueError("Published tag differs from the reviewed source commit")
    print("Published https://github.com/" + REPO + "/releases/tag/" + TAG, flush=True)


if __name__ == "__main__":
    main()
