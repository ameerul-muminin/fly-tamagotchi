"""All tunable values for the brain model live here.

LIF parameters are copied from the Shiu et al. 2024 reference implementation:
    github.com/philshiu/Drosophila_brain_model, model.py, `default_params`,
    at commit 91bdd1e7dcf193f3e7ca5a8933497fcef63b7960 (2024-09-14).
The per-parameter comments repeat the literature citations given in that file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
NEURON_GROUPS_PATH = DATA_DIR / "neuron_groups.json"
VALIDATION_RESULTS_PATH = DATA_DIR / "validation_results.json"

# ---------------------------------------------------------------------------
# Data sources (pinned commits, verified by sha256)
# ---------------------------------------------------------------------------
SHIU_REPO = "philshiu/Drosophila_brain_model"
SHIU_COMMIT = "91bdd1e7dcf193f3e7ca5a8933497fcef63b7960"

# FlyWire annotations (Schlegel et al. 2024), used only for photoreceptor lookup.
# Root IDs there are from FlyWire release 783.
ANNOTATIONS_REPO = "flyconnectome/flywire_annotations"
ANNOTATIONS_COMMIT = "8587524c1748ce5ef2080822a2fc890fc03bf597"

# FlyWire release used by the Shiu et al. paper and default code: 630.
FLYWIRE_VERSION = 630


@dataclass(frozen=True)
class DataFile:
    """One downloadable file with its pinned source and checksum."""

    local_name: str
    repo: str
    commit: str
    repo_path: str
    sha256: str

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo}/raw/{self.commit}/{self.repo_path}"

    @property
    def path(self) -> Path:
        return DATA_DIR / self.local_name


DATA_FILES: dict[str, DataFile] = {
    "completeness": DataFile(
        "completeness_630.csv", SHIU_REPO, SHIU_COMMIT,
        "2023_03_23_completeness_630_final.csv",
        "e6b71e17671a9bdb05f55e4bc6774640a1418cb7a05125e0fc994ad40f9bfdfb",
    ),
    "connectivity": DataFile(
        "connectivity_630.parquet", SHIU_REPO, SHIU_COMMIT,
        "2023_03_23_connectivity_630_final.parquet",
        "94db8c650533bc36ffa3223f2e62325d5648b8d6bd31c3a4e1c804628c7557b3",
    ),
    "figures_notebook": DataFile(
        "shiu_figures.ipynb", SHIU_REPO, SHIU_COMMIT,
        "figures.ipynb",
        "33cd73c0b4b4a291c51b7bab639c4fa28978e49e111ff0d6adbca5687addb84c",
    ),
    # Repo's own simulation outputs (example.ipynb): sugar GRNs, 30 trials x 1 s, v630.
    # sugarR_100Hz sets r_poi = 100 Hz explicitly in the notebook.
    "reference_sugar_100hz": DataFile(
        "shiu_result_sugarR_100Hz.parquet", SHIU_REPO, SHIU_COMMIT,
        "results/example/sugarR_100Hz.parquet",
        "93722ec03c3faa5a85790d77ed16bdd7f1e38a7c847ed0bc3af3dc2e4d0c3d34",
    ),
    # sugarR was run with default params. model.py says r_poi = 150 Hz, but the
    # sugar GRNs in this file fire at ~197 Hz, so it was produced at 200 Hz (as the
    # notebook text states). Kept for reference; not used as the sanity target.
    "reference_sugarR": DataFile(
        "shiu_result_sugarR.parquet", SHIU_REPO, SHIU_COMMIT,
        "results/example/sugarR.parquet",
        "83921d50089d966785e402d6c0e3be5ab3eba5beb680410a09c557b0f22dcc28",
    ),
    "annotations": DataFile(
        "flywire_annotations_783.tsv", ANNOTATIONS_REPO, ANNOTATIONS_COMMIT,
        "supplemental_files/Supplemental_file1_neuron_annotations.tsv",
        "9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be",
    ),
}

# ---------------------------------------------------------------------------
# LIF model (units: ms, mV, Hz)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LIFParams:
    """Leaky integrate-and-fire constants, from Shiu et al. model.py `default_params`.

    Neuron model (model.py `eqs`), both variables frozen while refractory:
        dv/dt = (v_0 - v + g) / t_mbr
        dg/dt = -g / tau
    On spike: v = v_rst, g = 0. Presynaptic spike: g_post += w after t_dly.
    """

    v_0: float = -52.0     # resting potential [mV]; Kakaria & de Bivort 2017
    v_rst: float = -52.0   # reset potential [mV]; Kakaria & de Bivort 2017
    v_th: float = -45.0    # spike threshold [mV]; Kakaria & de Bivort 2017
    t_mbr: float = 20.0    # membrane time constant [ms]; Kakaria & de Bivort 2017
    tau: float = 5.0       # synaptic time constant [ms]; Jürgensen et al. 2021
    t_rfc: float = 2.2     # refractory period [ms]; Lazar et al. 2021
    t_dly: float = 1.8     # synaptic delay [ms]; Paul et al. 2015
    w_syn: float = 0.275   # weight per synapse [mV]; free parameter in the paper
    f_poi: float = 250.0   # Poisson input weight = w_syn * f_poi, added directly to v
    # Not set in the repo; Brian2's default clock (defaultclock.dt = 0.1 ms) applies.
    dt: float = 0.1        # integration step [ms]


# Default Poisson input rate in model.py (`r_poi`). Note: example.ipynb text says
# 200 Hz, but every revision of model.py uses 150 Hz.
DEFAULT_INPUT_RATE_HZ = 150.0

# The live simulator advances in chunks of this length.
CHUNK_MS = 50.0


@dataclass(frozen=True)
class NoiseParams:
    """Optional background noise for live play. NOT part of the reference model.

    Every neuron receives independent Poisson noise events at `rate_hz`; each event
    adds `jump_mv` to v, like a Poisson input, and is discarded while the neuron
    is refractory. Validation runs use no noise.
    """

    rate_hz: float
    jump_mv: float

# ---------------------------------------------------------------------------
# Phase 1 validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationConfig:
    """Experiment settings and pass/fail thresholds for Phase 1.

    Thresholds were proposed in the Phase 1 plan and approved; they are
    project choices, not values from the paper.
    """

    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    trial_ms: float = 1000.0             # same trial length as the repo (t_run)
    sugar_hz: float = DEFAULT_INPUT_RATE_HZ
    bitter_hz: float = DEFAULT_INPUT_RATE_HZ
    shuffle_seed: int = 12345
    # Sugar -> MN9 must fire at least this much [Hz].
    min_sugar_mn9_hz: float = 20.0
    # Sugar + bitter must lower MN9 by at least this fraction ...
    min_bitter_reduction: float = 0.25
    # ... and the drop must exceed this many (pooled) SDs across seeds.
    min_reduction_sds: float = 2.0
    # Shuffled brain counts as "no feeding" if sugar -> MN9 stays below this [Hz].
    max_shuffled_mn9_hz: float = 5.0
    # Sanity check against the repo's own result: sugar at this rate, and our MN9
    # rate must be within this fraction of theirs.
    reference_file: str = "reference_sugar_100hz"
    reference_sugar_hz: float = 100.0
    reference_trials: int = 30   # model.py n_run
    reference_tolerance: float = 0.25
    groups: dict[str, str] = field(default_factory=lambda: {
        "sugar": "sugar_grn", "bitter": "bitter_grn", "readout": "mn9_primary",
    })


VALIDATION = ValidationConfig()


# ---------------------------------------------------------------------------
# Phase 2: reduced circuit for real-time play
# ---------------------------------------------------------------------------
REDUCED_CIRCUIT_PATH = DATA_DIR / "reduced_circuit.json"
PHASE2_RESULTS_PATH = DATA_DIR / "phase2_validation.json"


@dataclass(frozen=True)
class ReducedCircuitConfig:
    """Which neurons the reduced circuit keeps (see reports/PHASE_2_PLAN.md).

    A neuron is kept if it lies on a path of at most `max_path_hops` connections
    from any `source_groups` neuron to any `target_groups` neuron, counting every
    connection (no synapse threshold). `always_include` groups are kept regardless.
    K = 5 was chosen on design seed 100, which is not a validation seed.
    """

    max_path_hops: int = 5
    source_groups: tuple[str, ...] = ("sugar_grn", "bitter_grn")
    target_groups: tuple[str, ...] = ("mn9",)
    always_include: tuple[str, ...] = ("sugar_grn", "bitter_grn", "mn9", "mn9_primary")


REDUCED = ReducedCircuitConfig()


@dataclass(frozen=True)
class Phase2ValidationConfig:
    """Pass/fail thresholds for the reduced circuit, fixed before the first
    validation run (reports/PHASE_2_PLAN.md). Seeds, conditions and the Phase 1
    thresholds come from VALIDATION."""

    # Reduced MN9 mean must be within this fraction of the full-brain mean ...
    max_rel_diff: float = 0.10
    # ... for these conditions.
    compared_conditions: tuple[str, ...] = ("sugar", "sugar+bitter")
    # Every one of these shuffles of the reduced circuit must fail both effects.
    shuffle_seeds: tuple[int, ...] = (12345, 12346, 12347, 12348, 12349)
    # Wall time per 50 ms chunk, over all reduced real-brain chunks [ms].
    max_mean_chunk_ms: float = 35.0
    max_p95_chunk_ms: float = 35.0


PHASE2 = Phase2ValidationConfig()
