"""Checksums and a deterministic archive for a trained model directory.

Writes into the model directory:
  files.sha256     sha256 of every model file (sha256sum format)
  model.sha256     sha256 of the release archive out/release/model-<version>.tar.gz (sha256sum format)
The archive is byte-for-byte reproducible (sorted entries, zero mtimes, no gzip timestamp), so the GitHub
Release asset has exactly the checksum recorded in models/<version>/model.sha256.

  python scripts/package_model.py out/models/v1 v1
"""
import gzip
import hashlib
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"files.sha256", "model.sha256"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def package(model_dir, version, release_dir=None):
    model_dir = Path(model_dir)
    release_dir = Path(release_dir or ROOT / "out" / "release")
    release_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in model_dir.iterdir() if p.is_file() and p.name not in SKIP)
    (model_dir / "files.sha256").write_text("".join(f"{sha256_file(p)}  {p.name}\n" for p in files), encoding="utf-8")

    archive = release_dir / f"model-{version}.tar.gz"
    with open(archive, "wb") as f:
        with gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
                for p in sorted(p for p in model_dir.iterdir() if p.is_file() and p.name != "model.sha256"):
                    info = tarfile.TarInfo(name=f"{version}/{p.name}")
                    info.size = p.stat().st_size
                    info.mtime = 0
                    info.mode = 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with open(p, "rb") as src:
                        tar.addfile(info, src)
    digest = sha256_file(archive)
    line = f"{digest}  {archive.name}\n"
    (model_dir / "model.sha256").write_text(line, encoding="utf-8")
    (release_dir / f"model-{version}.sha256").write_text(line, encoding="utf-8")
    return archive, digest


if __name__ == "__main__":
    arch, dig = package(sys.argv[1], sys.argv[2])
    print(dig, arch)
