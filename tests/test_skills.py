"""The bundled agent skill must survive the trip into a wheel and an sdist.

Reading a hatchling include pattern is not evidence: `mergeset` already shipped
four releases whose wheels contained no skill at all, and the config looked fine
every time. These tests only believe a built artifact.
"""

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

from mergeset import bundled_skills, install_skills, skills_dir


def test_skill_is_inside_the_importable_package():
    """A wheel can only carry what lives under the package directory."""
    assert skills_dir() == Path(mergeset_dir()) / "data" / "skills"
    assert (skills_dir() / "mergeset" / "SKILL.md").is_file()
    assert [p.name for p in bundled_skills()] == ["mergeset"]


def mergeset_dir() -> str:
    import mergeset

    return str(Path(mergeset.__file__).resolve().parent)


def test_install_is_idempotent_and_does_not_clobber():
    target = Path(tempfile.mkdtemp())
    assert [Path(p).name for p in install_skills(str(target))] == ["mergeset"]
    assert (target / "mergeset" / "SKILL.md").is_file()
    assert install_skills(str(target)) == []  # second run leaves it alone

    (target / "mergeset").unlink()
    (target / "mergeset").mkdir()
    (target / "mergeset" / "SKILL.md").write_text("edited by hand")
    assert install_skills(str(target)) == []
    assert (target / "mergeset" / "SKILL.md").read_text() == "edited by hand"
    assert install_skills(str(target), overwrite=True, link=False)
    assert (target / "mergeset" / "SKILL.md").read_text().startswith("---")


@pytest.mark.parametrize("target", ["wheel", "sdist"])
def test_skill_md_is_physically_present_in_the_built_artifact(target):
    """Build for real and look inside. The config is not the artifact."""
    pytest.importorskip("build")
    pytest.importorskip("hatchling")
    repo = Path(__file__).resolve().parent.parent
    if not (repo / "pyproject.toml").is_file():
        pytest.skip("not running from a source checkout")
    outdir = Path(tempfile.mkdtemp())
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            f"--{target}",
            "--no-isolation",
            "--outdir",
            str(outdir),
            str(repo),
        ],
        check=True,
        capture_output=True,
    )
    (artifact,) = outdir.glob("*.whl" if target == "wheel" else "*.tar.gz")
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
