"""Fetch the reviewed AWS Guard rule data; no validators are installed or executed."""

import hashlib
import json
from pathlib import Path
import re
import urllib.request


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "infra/firetv/aws-guard-rules.json").read_text())
    commit = manifest["commit"]
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("The rules must be pinned to a commit")
    destination = root / ".homebound/aws-guard-rules"
    destination.mkdir(parents=True, exist_ok=True)
    for item in manifest["rules"]:
        path = item["path"]
        if not re.fullmatch(r"rules/aws/[a-z_]+/[a-z_]+\.guard", path):
            raise ValueError("Invalid rule path")
        target = destination / Path(path).name
        content = target.read_bytes() if target.exists() else b""
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            url = f"https://raw.githubusercontent.com/aws-cloudformation/aws-guard-rules-registry/{commit}/{path}"
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read(1_000_001)
            if len(content) > 1_000_000 or hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("Rule checksum mismatch")
            target.write_bytes(content)
    print(f"Verified {len(manifest['rules'])} rules from AWS at {commit}")
    print(destination)


if __name__ == "__main__":
    main()
