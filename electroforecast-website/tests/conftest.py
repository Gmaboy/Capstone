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


def build_small_system():
    """Small config -> system_hourly, using one seeded RNG."""
    import numpy as np

    from tools.synth.config import load_config
    from tools.synth.households import load_household_types
    from tools.synth.profiles import load_profiles
    from tools.synth.system_load import system_hourly

    cfg = load_config(CFG_SMALL)
    types = load_household_types(TYPES)
    profiles = load_profiles(types, cfg)
    rng = np.random.default_rng(cfg.seed)
    return system_hourly(ANCHORS, cfg, types, profiles, rng)


_NET_CACHE: dict = {}


def _network_pipeline():
    """Small-config pipeline through transformer peaks, one RNG, generator order."""
    if "p" in _NET_CACHE:
        return _NET_CACHE["p"]
    import numpy as np

    from tools.synth.config import load_config
    from tools.synth.customers import customer_counts
    from tools.synth.households import (
        household_monthly,
        load_household_types,
        sample_households,
    )
    from tools.synth.network import build_network, feeder_hourly, transformer_monthly_peak
    from tools.synth.profiles import load_profiles
    from tools.synth.system_load import system_hourly

    cfg = load_config(CFG_SMALL)
    types = load_household_types(TYPES)
    rng = np.random.default_rng(cfg.seed)
    counts = customer_counts(ANCHORS, cfg)
    hh = sample_households(ANCHORS, cfg, types, rng, counts)
    hm = household_monthly(ANCHORS, cfg, types, hh, counts, rng)
    profiles = load_profiles(types, cfg)
    system = system_hourly(ANCHORS, cfg, types, profiles, rng)
    feeders, transformers, hh_net = build_network(cfg, hh, counts, rng)
    fh = feeder_hourly(feeders, hh_net, hm, profiles, system)
    tm = transformer_monthly_peak(transformers, hh_net, hm, fh, cfg, rng)
    _NET_CACHE["p"] = {
        "network": (feeders, transformers, hh_net),
        "feeder_hourly": (fh, system),
        "peaks": (tm, transformers),
    }
    return _NET_CACHE["p"]


def build_small_network():
    return _network_pipeline()["network"]


def build_small_feeder_hourly():
    return _network_pipeline()["feeder_hourly"]


def build_small_transformer_peaks():
    return _network_pipeline()["peaks"]


def _real_series():
    from tools.model.forecast import real_series
    from tools.synth.config import load_config

    return real_series(ANCHORS, load_config(CFG))


SERIES, CUSTOMERS = _real_series()
