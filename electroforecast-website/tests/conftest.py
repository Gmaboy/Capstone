from pathlib import Path

from tools.common.anchors import load_anchors

CFG = Path("tools/synth/config.json")
CFG_SMALL = Path("tests/fixtures/config_small.json")
TYPES = Path("tools/synth/household_types.json")
ANCHORS = load_anchors()


def build_small():
    """Anchors + small config -> household_monthly, using one seeded RNG."""
    import numpy as np

    from tools.synth.config import load_config
    from tools.synth.customers import customer_counts
    from tools.synth.households import (
        household_monthly,
        load_household_types,
        sample_households,
    )

    cfg = load_config(CFG_SMALL)
    types = load_household_types(TYPES)
    rng = np.random.default_rng(cfg.seed)
    counts = customer_counts(ANCHORS, cfg)
    hh = sample_households(ANCHORS, cfg, types, rng, counts)
    return household_monthly(ANCHORS, cfg, types, hh, counts, rng)
