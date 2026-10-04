"""Fail early if a model, encoder or reference CSV was not included in a checkout."""
import hashlib
import json
from .service import ROOT


def verify_assets():
    manifest = json.loads((ROOT / "asset-manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["assets"].items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
            raise RuntimeError(f"必要なファイルがありません、またはチェックサムが不一致です: {name}")
    return len(manifest["assets"])
