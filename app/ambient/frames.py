"""Only repository-owned illustrative frames, never cross-app or protected video capture."""

from pathlib import Path

FRAME_DIRECTORY = Path(__file__).resolve().parents[1] / "web" / "static"


def sample_frame(scene: str) -> bytes | None:
    if scene not in {"cooking", "movie"}:
        return None
    path = FRAME_DIRECTORY / f"frame-{scene}.png"
    return path.read_bytes() if path.is_file() else None
