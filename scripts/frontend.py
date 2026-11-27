#!/usr/bin/env python3
"""Pinned frontend commands shared by Make, Docker, Paseo and verification."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def pnpm():
    return ["corepack", "pnpm"] if shutil.which("corepack") else ["pnpm"]


def check_toolchain():
    expected_node = (WEB / ".node-version").read_text().strip()
    expected_pnpm = json.loads((WEB / "package.json").read_text())["packageManager"].split("@", 1)[1]
    for label, command, expected in (
        ("Node", ["node", "--version"], "v" + expected_node),
        ("pnpm", pnpm() + ["--version"], expected_pnpm),
    ):
        actual = subprocess.check_output(command, cwd=WEB, text=True).strip()
        if actual != expected:
            raise RuntimeError(f"{label}: expected {expected}, found {actual}; see web/.node-version and package.json")


def run(*args, embedded=False):
    environment = os.environ.copy()
    if embedded:
        environment.update(VITE_BASE_API="/api", VITE_FILE_API="/api")
    subprocess.run(pnpm() + list(args), cwd=WEB, check=True, env=environment)


def stage_embed():
    if not (WEB / "dist/index.html").is_file() or not (WEB / "dist/index.html").stat().st_size:
        raise RuntimeError("frontend build did not produce a non-empty dist/index.html")
    destination = ROOT / "server/internal/webui/dist"
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(WEB / "dist", destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "build", "verify", "embed"])
    action = parser.parse_args().action
    check_toolchain()
    run("install", "--frozen-lockfile", "--prod=false")
    if action == "verify":
        run("test")
    if action != "install":
        run("run", "build", embedded=action in ("verify", "embed"))
    if action in ("verify", "embed"):
        stage_embed()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Frontend failed: {error}", file=sys.stderr)
        sys.exit(1)
