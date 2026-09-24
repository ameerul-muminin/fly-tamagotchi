"""Download the pinned data files into data/ and verify their checksums.

Usage: python -m brain.download_data
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request

from brain.config import DATA_DIR, DATA_FILES, DataFile


def sha256_of(path) -> str:
    """Return the hex sha256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ensure_file(df: DataFile) -> None:
    """Download `df` unless a copy with the right checksum already exists."""
    if df.path.exists() and sha256_of(df.path) == df.sha256:
        print(f"  ok        {df.local_name}")
        return
    print(f"  download  {df.local_name}  <- {df.url}")
    tmp = df.path.with_suffix(df.path.suffix + ".part")
    urllib.request.urlretrieve(df.url, tmp)
    got = sha256_of(tmp)
    if got != df.sha256:
        tmp.unlink()
        raise RuntimeError(f"checksum mismatch for {df.local_name}: {got} != {df.sha256}")
    tmp.replace(df.path)


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    for df in DATA_FILES.values():
        ensure_file(df)
    print("All data files present and verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
