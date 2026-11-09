import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.package_model import package, sha256_file  # noqa: E402


def test_archive_is_reproducible_and_checksum_matches(tmp_path):
    m = tmp_path / "v1"
    m.mkdir()
    (m / "model.safetensors").write_bytes(b"weights" * 100)
    (m / "version.json").write_text("{}")
    a1, d1 = package(m, "v1", tmp_path / "r1")
    a2, d2 = package(m, "v1", tmp_path / "r2")
    assert d1 == d2 == sha256_file(a1)
    assert (m / "model.sha256").read_text().split()[0] == d1
    with tarfile.open(a1) as t:
        assert "v1/model.safetensors" in t.getnames()
