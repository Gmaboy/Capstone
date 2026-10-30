from pathlib import Path

from tools.common.anchors import load_anchors

CFG = Path("tools/synth/config.json")
CFG_SMALL = Path("tests/fixtures/config_small.json")
ANCHORS = load_anchors()
