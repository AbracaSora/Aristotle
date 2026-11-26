import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "tools/quality/review_bundle.py"
spec = importlib.util.spec_from_file_location("review_bundle", SOURCE)
review_bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review_bundle)


@pytest.fixture
def small_release(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path)

    git("init", "-q")
    git(
        "-c",
        "user.email=test@localhost",
        "-c",
        "user.name=Test",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--allow-empty",
        "-qm",
        "base",
    )
    base = git("rev-parse", "HEAD").decode().strip()
    path = tmp_path / "src/item.py"
    path.parent.mkdir()
    path.write_text("value = 1\n")
    git("add", "src/item.py")
    patch = git("diff", "--cached")
    entry = dict(
        patch="1.patch",
        file="src/item.py",
        added=1,
        deleted=0,
        guard_lines=1,
        sha256=hashlib.sha256(patch).hexdigest(),
        tree=git("write-tree").decode().strip(),
    )
    manifest = dict(
        base=base,
        sources=["src"],
        batches=[entry],
        files={"src/item.py": hashlib.sha256(path.read_bytes()).hexdigest()},
    )
    archive = tmp_path / "review.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("1.patch", patch)
    return tmp_path, archive, base, ["src"]


def test_review_replays_against_exact_base_and_actual_files(small_release):
    root, archive, base, sources = small_release
    assert review_bundle.check_archive(root, archive, base, sources, 1)["max_lines"] == 1
    with pytest.raises(ValueError):
        review_bundle.check_archive(root, archive, base, sources, 0)
    with pytest.raises(ValueError):
        review_bundle.check_archive(root, archive, "other", sources, 1)
    (root / "src/item.py").write_text("value = 2\n")
    with pytest.raises(ValueError):
        review_bundle.check_archive(root, archive, base, sources, 1)
