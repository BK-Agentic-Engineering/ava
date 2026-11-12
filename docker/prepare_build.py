"""Cache the pinned official Linux binary; weights are supplied by a build context."""

import argparse
import hashlib
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    name = "llama-b12110-bin-ubuntu-cuda-12.8-x64.tar.gz"
    path = args.cache / name
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".partial")
        urllib.request.urlretrieve("https://github.com/ggml-org/llama.cpp/releases/download/b12110/" + name, temporary)
        temporary.rename(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != "4af1e1da23661db4a5b84b29aae16ebc053df689c5b8b1427c4670f2c6406d8c":
        raise ValueError(f"Official release checksum mismatch: {path}")
    print(f"Verified {path}: {digest}")


if __name__ == "__main__":
    main()
