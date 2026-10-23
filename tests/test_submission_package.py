"""A release must never silently include private state or lose executable scripts."""

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.build_submission import build_archive, is_public_path


@pytest.mark.parametrize("name", [
    ".env", "agentsafe/.env", "app/.env.production", "audit/actions.jsonl",
    ".homebound/policy-binding.json", "agentsafe/node_modules/package/index.js",
    "docs/private.key", "app/state.sqlite3", "../outside.py", "app/../../outside.py",
])
def test_private_paths_are_never_packaged(name: str) -> None:
    assert not is_public_path(name)


@pytest.mark.parametrize("name", ["app/audit/__init__.py", "app/audit/logger.py", "apps/firetv/.eslintrc"])
def test_public_runtime_and_build_sources_are_packaged(name: str) -> None:
    assert is_public_path(name)


def test_archive_is_reproducible_and_manifest_covers_exact_bytes(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts/run-demo.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    (tmp_path / ".env.example").write_text("EXAMPLE=\n")
    names = ["scripts/run-demo.sh", ".env.example"]
    first = build_archive(tmp_path, names, tmp_path / "one.zip", revision="a" * 40, dirty=True, required=set())
    second = build_archive(tmp_path, names, tmp_path / "two.zip", revision="a" * 40, dirty=True, required=set())
    assert first["sha256"] == second["sha256"]
    with zipfile.ZipFile(tmp_path / "one.zip") as archive:
        manifest = json.loads(archive.read("homebound/SUBMISSION_MANIFEST.json"))
        assert manifest["working_tree_dirty"] is True
        for entry in manifest["files"]:
            data = archive.read("homebound/" + entry["path"])
            assert len(data) == entry["bytes"]
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert archive.getinfo("homebound/scripts/run-demo.sh").external_attr >> 16 & 0o111


def test_symlink_cannot_smuggle_private_file(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    private = tmp_path / ".env"
    private.write_text("secret fixture")
    (tmp_path / "docs/public.md").symlink_to(private)
    with pytest.raises(ValueError, match="symlinks"):
        build_archive(tmp_path, ["docs/public.md"], tmp_path / "out.zip", revision="test", dirty=True, required=set())


def test_missing_required_assets_abort_before_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="required public files"):
        build_archive(tmp_path, [], tmp_path / "out.zip", revision="test", dirty=True)
    assert not (tmp_path / "out.zip").exists()
