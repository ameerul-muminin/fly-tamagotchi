"""Phase 1 behavior tests on the full brain (slow: runs every experiment once).

Each check runs across all validation seeds; see brain/validate.py and
ValidationConfig for conditions and thresholds.
"""

import json

import pytest

from brain.config import VALIDATION_RESULTS_PATH
from brain.validate import format_report, run_validation


@pytest.fixture(scope="module")
def report(connectome):
    rep = run_validation()
    VALIDATION_RESULTS_PATH.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("\n" + format_report(rep))
    return rep


def test_uses_at_least_five_seeds(report):
    assert len(report["config"]["seeds"]) >= 5
    for r in report["conditions"].values():
        assert len(r["mn9_rates_hz"]) >= 5


def test_sugar_drives_mn9(report):
    assert report["checks"]["sugar_drives_mn9"], report["conditions"]["real/sugar"]


def test_bitter_reduces_sugar_driven_mn9(report):
    c = report["conditions"]
    assert report["checks"]["bitter_reduces_mn9"], (c["real/sugar"], c["real/sugar+bitter"])


def test_shuffled_brain_does_not_feed_on_sugar(report):
    assert report["checks"]["shuffled_no_sugar_effect"], report["conditions"]["shuffled/sugar"]


def test_shuffled_brain_shows_no_bitter_suppression(report):
    c = report["conditions"]
    assert report["checks"]["shuffled_no_bitter_effect"], (c["shuffled/sugar"], c["shuffled/sugar+bitter"])


def test_matches_reference_implementation(report):
    assert report["checks"]["matches_reference"], report["reference"]


def test_speed_is_reported(report):
    assert report["speed_ms_per_50ms_chunk"]["n_chunks"] > 0
