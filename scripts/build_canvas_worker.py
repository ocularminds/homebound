"""Build a source-only Lambda artifact with pinned pure Python AWS dependencies."""

from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / ".homebound"
    output.mkdir(exist_ok=True)
    artifact = output / "canvas-worker.zip"
    with tempfile.TemporaryDirectory(prefix="canvas-worker-", dir=output) as scratch:
        stage = Path(scratch)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--only-binary=:all:",
                "--no-compile",
                "--target",
                str(stage),
                "-r",
                str(root / "infra/firetv/worker-requirements.txt"),
            ],
            check=True,
        )
        with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
            for source in sorted(stage.rglob("*")):
                if source.is_file() and "__pycache__" not in source.parts:
                    archive.write(source, source.relative_to(stage))
            # Worker imports only Python modules. Never package local env/config/audit files.
            for source in sorted((root / "app").rglob("*.py")):
                archive.write(source, source.relative_to(root))
    print(artifact)


if __name__ == "__main__":
    main()
