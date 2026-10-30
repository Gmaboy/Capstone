import sqlite3

from tools.common.anchors import DEFAULT_REAL_CSV, load_anchors
from tools.synth.config import load_config
from tools.synth.generate import generate
from tools.synth.load import load
from tools.synth.validate import validate

from tests.conftest import CFG_SMALL as SMALL_CFG

ANCHORS = load_anchors()
REAL_CSV = DEFAULT_REAL_CSV


def test_small_generation_passes_all_checks(tmp_path):
    generate(SMALL_CFG, tmp_path)
    report = (tmp_path / "validation_report.md").read_text()
    assert "FAIL" not in report and "38689" not in report  # 2023 not in small config years
    assert (tmp_path / "synth_system_hourly.csv").exists()


def test_generation_is_deterministic(tmp_path):
    generate(SMALL_CFG, tmp_path / "a")
    generate(SMALL_CFG, tmp_path / "b")
    for f in (tmp_path / "a").glob("*.csv"):
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes()


def test_validation_fails_on_tampered_totals(tmp_path):
    tables = generate(SMALL_CFG, tmp_path)
    tables["synth_system_hourly"].loc[0, "load_mw"] += 5
    assert not all(c.passed for c in validate(ANCHORS, load_config(SMALL_CFG), tables))


def test_load_is_idempotent(tmp_path):
    db = tmp_path / "t.db"
    generate(SMALL_CFG, tmp_path / "out")
    load(db, REAL_CSV, tmp_path / "out")
    load(db, REAL_CSV, tmp_path / "out")
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from synth_households").fetchone()[0] == 200
    assert con.execute("select count(*) from utility_monthly_energy").fetchone()[0] == 72
    assert con.execute("select notes from utility_annual_stats where year=2023").fetchone()[0]
