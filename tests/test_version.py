"""The package reports the version from pyproject.toml, not a second hand-kept copy (#95)."""

import tomllib

import event_ops_engine
from tests.conftest import REPO


def test_version_matches_pyproject() -> None:
    with (REPO / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert event_ops_engine.__version__ == project["version"]
