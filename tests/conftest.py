"""Shared fixtures. Data-dependent fixtures load the connectome once per session."""

import pytest

from brain.config import DATA_FILES, NEURON_GROUPS_PATH


def _require_data() -> None:
    missing = [f.local_name for f in DATA_FILES.values() if not f.path.exists()]
    if missing:
        pytest.fail(f"missing data files {missing}; run `python -m brain.download_data`")
    if not NEURON_GROUPS_PATH.exists():
        pytest.fail("missing data/neuron_groups.json; run `python -m brain.neuron_groups`")


@pytest.fixture(scope="session")
def connectome():
    _require_data()
    from brain.connectome import load_connectome
    return load_connectome()


@pytest.fixture(scope="session")
def shuffled(connectome):
    from brain.config import VALIDATION
    from brain.connectome import shuffle_connectome
    return shuffle_connectome(connectome, VALIDATION.shuffle_seed)
