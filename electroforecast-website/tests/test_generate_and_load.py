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


def _failing(monkeypatch):
    import tools.synth.generate as g
    from tools.synth.validate import Check

    monkeypatch.setattr(g, "validate", lambda *a, **k: [Check("forced", 1.0, 0.0, False)])


def test_failed_validation_leaves_no_csvs_but_writes_fail_report(tmp_path, monkeypatch):
    import pytest

    from tools.synth.validate import ValidationError

    out = tmp_path / "out"
    generate(SMALL_CFG, out)  # a previous good run exists
    _failing(monkeypatch)
    with pytest.raises(ValidationError):
        generate(SMALL_CFG, out)
    assert not list(out.glob("*.csv"))
    assert "FAIL" in (out / "validation_report.md").read_text()
    assert [p.name for p in tmp_path.iterdir()] == ["out"]  # no temp dirs left


def test_failed_validation_fresh_dir(tmp_path, monkeypatch):
    import pytest

    from tools.synth.validate import ValidationError

    _failing(monkeypatch)
    with pytest.raises(ValidationError):
        generate(SMALL_CFG, tmp_path / "new")
    assert not list((tmp_path / "new").glob("*.csv"))
    assert "FAIL" in (tmp_path / "new" / "validation_report.md").read_text()


def test_load_refuses_missing_or_failed_report(tmp_path):
    import pytest

    generate(SMALL_CFG, tmp_path / "out")
    report = tmp_path / "out" / "validation_report.md"
    good = report.read_text()
    report.write_text(good + "\n| FAIL | x | 1 | 0 |\n")
    with pytest.raises(RuntimeError, match="FAIL"):
        load(tmp_path / "t.db", REAL_CSV, tmp_path / "out")
    report.unlink()
    with pytest.raises(RuntimeError, match="missing"):
        load(tmp_path / "t.db", REAL_CSV, tmp_path / "out")
    assert not (tmp_path / "t.db").exists()


def test_report_has_limitations_section(tmp_path):
    generate(SMALL_CFG, tmp_path)
    r = (tmp_path / "validation_report.md").read_text()
    assert "## Limitations" in r and "final config year" in r
