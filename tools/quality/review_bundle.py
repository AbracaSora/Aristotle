"""Verify review units against the actual Git parent and resulting production sources."""

import difflib
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


def git(root, *args, data=None):
    return subprocess.run(
        ["git", *args], cwd=root, input=data, capture_output=True, check=True, timeout=45
    ).stdout


def changed_lines(before, after):
    return sum(
        line.startswith(("+ ", "- "))
        for line in difflib.ndiff(before.decode().splitlines(), after.decode().splitlines())
    )


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply_batch(checkout, entry, patch, sources, limit):
    stat = git(checkout, "apply", "--numstat", "-z", "-", data=patch)
    added, removed, path = stat.decode().rstrip("\0").split("\t")
    relative = PurePosixPath(path)
    counts = (int(added), int(removed))
    if (
        path != entry["file"]
        or not any(relative.is_relative_to(source) for source in sources)
        or ".." in relative.parts
        or relative.suffix != ".py"
        or sum(counts) > limit
        or counts != (entry["added"], entry["deleted"])
        or digest(patch) != entry["sha256"]
    ):
        raise ValueError("补丁路径、增删行数或摘要校验失败")
    target = checkout / path
    before = target.read_bytes() if target.exists() else b""
    git(checkout, "apply", "--index", "--whitespace=nowarn", "-", data=patch)
    if target.is_symlink():
        raise ValueError("源码须为普通文件")
    after = target.read_bytes() if target.exists() else b""
    compile(after, path, "exec")
    size = changed_lines(before, after)
    if (
        size > limit
        or size != entry["guard_lines"]
        or git(checkout, "write-tree").decode().strip() != entry["tree"]
    ):
        raise ValueError("补丁超出护栏行数或重放的 Git tree 不一致")
    return max(size, sum(counts))


def check_archive(root, archive, base, sources, limit):
    with ZipFile(archive) as z, tempfile.TemporaryDirectory() as tmp:
        members = z.infolist()
        if len(members) > 512 or sum(m.file_size for m in members) > 16_000_000:
            raise ValueError("评审包超出可验证范围")
        if len(set(z.namelist())) != len(members):
            raise ValueError("评审包含重名文件")
        manifest = json.loads(z.read("manifest.json"))
        if manifest["base"] != base or manifest["sources"] != sources or not manifest["batches"]:
            raise ValueError("评审包基线或源码范围不匹配")
        checkout = Path(tmp) / "checkout"
        git(root, "clone", "--local", "--no-hardlinks", "--quiet", "--no-checkout", ".", str(checkout))
        git(checkout, "checkout", "--quiet", "--detach", base)
        sizes = [
            apply_batch(checkout, entry, z.read(entry["patch"]), sources, limit)
            for entry in manifest["batches"]
        ]
        for tree in (checkout, root):
            hashes = {
                str(p.relative_to(tree)): digest(p.read_bytes())
                for folder in sources
                for p in (tree / folder).rglob("*.py")
            }
            if hashes != manifest["files"]:
                raise ValueError("重放终点与本次交付的完整源码不一致")
        return {"passed": True, "base": base, "batches": len(sizes), "max_lines": max(sizes)}


def review_size(root, size, config, base):
    limit = config["diff_limit"]
    if size <= limit:
        return {"passed": True, "mode": "single", "lines": size}
    archive = root / "quality/backend-review.zip"
    try:
        result = check_archive(root, archive, base, config["sources"], limit)
        return {**result, "mode": "bundle", "lines": size}
    except (
        OSError,
        BadZipFile,
        KeyError,
        ValueError,
        TypeError,
        SyntaxError,
        subprocess.SubprocessError,
    ) as exc:
        return {"passed": False, "mode": "bundle", "error": str(exc), "lines": size}
