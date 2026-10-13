"""The bundled agent skill must survive the trip into a wheel and an sdist.

Reading a hatchling include pattern is not evidence: `mergeset` already shipped
four releases whose wheels contained no skill at all, and the config looked fine
every time. These tests only believe a built artifact.

The sdist case is the one that guards the symlink-pruning fix (see the comment
at the top of pyproject.toml); the wheel case guards the duller failure that
started all this — a skill sitting outside the importable package, which no
wheel can carry.
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from mergeset import bundled_skills, install_skills, skills_dir
from mergeset.base import MergesetError

REPO = Path(__file__).resolve().parent.parent


def test_skill_is_inside_the_importable_package():
    """A wheel can only carry what lives under the package directory."""
    import mergeset

    assert skills_dir() == Path(mergeset.__file__).resolve().parent / "data" / "skills"
    assert (skills_dir() / "mergeset" / "SKILL.md").is_file()
    assert [p.name for p in bundled_skills()] == ["mergeset"]


def test_install_is_idempotent_and_overwrite_replaces_the_link(tmp_path):
    target = tmp_path / "host"
    assert [Path(p).name for p in install_skills(str(target))] == ["mergeset"]
    assert (target / "mergeset" / "SKILL.md").is_file()
    assert install_skills(str(target)) == []  # second run leaves it alone
    # Replacing a symlink destination: on Windows that needs rmdir, not unlink.
    assert install_skills(str(target), overwrite=True)
    assert (target / "mergeset" / "SKILL.md").is_file()


def test_an_edited_skill_is_never_silently_replaced(tmp_path):
    target = tmp_path / "host"
    install_skills(str(target), link=False)
    (target / "mergeset" / "SKILL.md").write_text("edited by hand")
    assert install_skills(str(target)) == []
    assert (target / "mergeset" / "SKILL.md").read_text() == "edited by hand"
    assert install_skills(str(target), overwrite=True, link=False)
    assert (target / "mergeset" / "SKILL.md").read_text().startswith("---")


def test_something_else_in_the_way_is_reported_not_called_installed(tmp_path):
    """The old failure: a broken link or a stray file read as 'already done'."""
    target = tmp_path / "host"
    target.mkdir()
    (target / "mergeset").write_text("not a skill")
    with pytest.raises(MergesetError):
        install_skills(str(target))
    (installed,) = install_skills(str(target), overwrite=True)
    assert Path(installed, "SKILL.md").is_file()


def test_a_relative_skills_root_still_links_somewhere_that_resolves(
    tmp_path, monkeypatch
):
    source = tmp_path / "src" / "demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: demo\n---\n")
    monkeypatch.chdir(tmp_path)
    (installed,) = install_skills(str(tmp_path / "host"), skills_root="src")
    assert Path(installed, "SKILL.md").is_file()


def test_a_missing_skills_root_says_so(tmp_path):
    with pytest.raises(MergesetError):
        list(bundled_skills(str(tmp_path / "nowhere")))


@pytest.mark.parametrize("target", ["wheel", "sdist"])
def test_skill_md_is_physically_present_in_the_built_artifact(target, tmp_path):
    """Build for real and look inside. The config is not the artifact."""
    pytest.importorskip("build")
    pytest.importorskip("hatchling")
    if not (REPO / "pyproject.toml").is_file():
        pytest.skip("not running from a source checkout")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            f"--{target}",
            "--no-isolation",
            "--outdir",
            str(tmp_path),
            str(REPO),
        ],
        check=True,
        capture_output=True,
    )
    (artifact,) = tmp_path.glob("*.whl" if target == "wheel" else "*.tar.gz")
    names = _archive_names(artifact)
    assert any(n.endswith("mergeset/data/skills/mergeset/SKILL.md") for n in names), (
        f"SKILL.md missing from the {target}: {sorted(names)[:20]}"
    )


def _archive_names(artifact: Path):
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as z:
            return z.namelist()
    import tarfile

    with tarfile.open(artifact) as t:
        return t.getnames()
