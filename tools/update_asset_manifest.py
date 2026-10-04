"""Refresh checked-in checksums after intentionally updating bundled assets."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "asset-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for name in manifest["assets"]:
        asset = (ROOT / name).resolve()
        if not asset.is_relative_to(ROOT):
            raise ValueError("Asset must remain inside the repository")
        manifest["assets"][name] = {"bytes": asset.stat().st_size,
                                     "sha256": hashlib.sha256(asset.read_bytes()).hexdigest()}
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
