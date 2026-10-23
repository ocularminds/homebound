"""Create a reproducible source bundle from public repository files only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOTS = {"app", "agentsafe", "apps", "docs", "friction-log", "infra", "media", "policies", "scripts", "tests", ".github"}
PUBLIC_FILES = {
    "AGENTS.md", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "Makefile",
    "MANIFEST.in", "Dockerfile", "compose.yaml", "pyproject.toml",
    "requirements.lock", "requirements-dev.lock", ".gitignore", ".dockerignore",
    ".node-version", ".env.example",
}
PRIVATE_PARTS = {"node_modules", "__pycache__", ".homebound", ".git", ".venv", "build", "dist", ".cache"}
PUBLIC_CONFIGS = {"apps/firetv/.eslintrc", "apps/firetv/.prettierrc"}
PRIVATE_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db", ".pem", ".key", ".p12", ".pfx"}
REQUIRED_FILES = {
    "README.md", "LICENSE", "pyproject.toml", "requirements.lock",
    "agentsafe/package.json", "agentsafe/package-lock.json", "agentsafe/run-local.sh",
    "docs/submission/README.md", "docs/submission/project-description.md",
    "docs/submission/product-feedback.md", "docs/submission/narration.md",
    "app/web/static/tv.html", "app/web/static/media/park-chase.mp4",
    "app/web/static/media/movie-night-ad.mp4", "app/web/static/media/popcorn-ad.mp4",
}


def is_public_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
        return False
    if path.name == "buildinfo.json":
        return False
    if name not in PUBLIC_FILES and path.parts[0] not in PUBLIC_ROOTS:
        return False
    if any(part in PRIVATE_PARTS for part in path.parts) or path.suffix in PRIVATE_SUFFIXES:
        return False
    if any(part.startswith(".") and part not in {".github", ".env.example"} for part in path.parts):
        return name in PUBLIC_FILES or name in PUBLIC_CONFIGS
    return True


def public_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, check=True, stdout=subprocess.PIPE,
    )
    return sorted({name for name in result.stdout.decode().split("\0") if is_public_path(name)})


def build_archive(
    root: Path, names: list[str], output: Path, *, revision: str, dirty: bool,
    required: set[str] | None = None,
) -> dict:
    """Write one stable ZIP; refuse symlinks, private paths, and missing assets."""
    names = sorted(set(names))
    missing = (REQUIRED_FILES if required is None else required) - set(names)
    if missing:
        raise ValueError("Submission is missing required public files: " + ", ".join(sorted(missing)))
    root = root.resolve()
    entries = []
    for name in names:
        if not is_public_path(name):
            raise ValueError("A non-public path was selected for packaging.")
        source = root / name
        if source.is_symlink() or not source.resolve().is_relative_to(root):
            raise ValueError("Submission bundles cannot contain symlinks or outside files.")
        if not source.is_file():
            raise ValueError("A selected public source file is missing.")
        data = source.read_bytes()
        if name in REQUIRED_FILES and not data:
            raise ValueError("A required submission asset is empty.")
        entries.append((name, data, 0o755 if source.stat().st_mode & 0o111 else 0o644))
    records = [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mode": oct(mode)}
        for name, data, mode in entries
    ]
    manifest = {
        "format_version": 1, "project": "HomeBound", "primary_track": "Fire TV",
        "source_commit": revision, "working_tree_dirty": dirty,
        "source_sha256": hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest(),
        "entrypoint": "docs/submission/README.md", "files": records,
    }
    entries.append(("SUBMISSION_MANIFEST.json", (json.dumps(manifest, indent=2) + "\n").encode(), 0o644))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data, mode in entries:
                info = zipfile.ZipInfo("homebound/" + name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o100000 | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{checksum}  {output.name}\n")
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"artifact": str(output), "bytes": output.stat().st_size, "files": len(records), "sha256": checksum}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/homebound-submission.zip")
    args = parser.parse_args()
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
        report = build_archive(ROOT, public_paths(ROOT), args.output.resolve(), revision=revision, dirty=dirty)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Submission build failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
