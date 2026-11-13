"Nạp đúng zaic_tools đi kèm split của BTC."

import importlib
import hashlib
import sys
from pathlib import Path


_loaded_digests = {}


def sdk_digest(source):
    digest = hashlib.sha256()
    for path in sorted((source / "zaic_tools").rglob("*.py")):
        digest.update(str(path.relative_to(source / "zaic_tools")).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_sdk(root, split):
    source = (root / split).resolve()
    loaded = sys.modules.get("zaic_tools")
    if loaded is not None and Path(loaded.__file__).resolve().parent != source / "zaic_tools":
        raise RuntimeError("Chạy mỗi split/SDK root trong một process riêng.")
    digest = sdk_digest(source)
    if source in _loaded_digests and _loaded_digests[source] != digest:
        raise RuntimeError("SDK files changed after import; start a fresh process")
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    module = importlib.import_module("zaic_tools")
    _loaded_digests[source] = digest
    return module


def create_env(root, split, sample_id):
    return load_sdk(root, split).ToolEnv(split, sample_id, root=root)


def environment_ref(root, split, sample_id):
    root = Path(root).resolve()
    return {"root": str(root), "split": split, "sample_id": sample_id,
            "sdk_sha256": sdk_digest(root / split),
            "catalog_sha256": hashlib.sha256((root / split / f"{split}_tools_catalog.json").read_bytes()).hexdigest(),
            "fixture_file_sha256": hashlib.sha256((root / split / f"{split}_environment" / sample_id / "state.json").read_bytes()).hexdigest()}
