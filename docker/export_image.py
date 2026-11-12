"""Export docker save as gzip and calculate the organizer's MD5 checksum."""

import argparse
import gzip
import hashlib
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    with partial.open("xb") as destination:
        with gzip.GzipFile(fileobj=destination, mode="wb", filename="", mtime=0, compresslevel=1) as archive:
            process = subprocess.Popen(["docker", "image", "save", args.image], stdout=subprocess.PIPE)
            try:
                with process.stdout:
                    shutil.copyfileobj(process.stdout, archive)
            finally:
                code = process.wait()
            if code:
                raise RuntimeError(f"docker image save exited with {code}; retained {partial}")
    partial.rename(args.output)
    with args.output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "md5").hexdigest()
    args.output.with_suffix(args.output.suffix + ".md5").write_text(f"{digest}  {args.output.name}\n", encoding="utf-8")
    print(f"{digest}  {args.output}")


if __name__ == "__main__":
    main()
