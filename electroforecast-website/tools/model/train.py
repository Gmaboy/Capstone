"""Train the three models on the DB tables and store runs, models and reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tools.model.demand import LABELS, build_features, train_demand  # noqa: E402
from tools.model.explain import forecast_breakdown, permutation_importance_table  # noqa: E402
from tools.model.forecast import (  # noqa: E402
    CANDIDATES, _hours, backtest, forecast_monthly, forecast_peak, real_series, select_model,
)
from tools.model.store import MissingDataError, check_inputs, connect, ensure_schema, read_anchors, read_daily, save_run  # noqa: E402
from tools.synth.config import load_config  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "synth" / "config.json"
REAL_VERSION = "real:guimelco_residential_2020_2025"
FC_COLS = ["year", "month", "forecast_mwh", "lo80", "hi80", "lo95", "hi95"]

__all__ = ["train", "MissingDataError", "main"]


def _load_factors(anchors) -> dict[int, float]:
    return {
        int(y): float(sum(anchors.monthly_mwh[(y, m)] for m in range(1, 13)) / (anchors.peak_mw[y] * _hours(y)))
        for y in anchors.years
    }


def nested_metric(bt: pd.DataFrame) -> dict:
    """Select the model on the 2024 fold only, then report its untouched 2025 fold.

    Less optimistic than the headline mean MAPE, which selects and scores on the same folds.
    """
    f24 = bt[bt.fold == "2024"].set_index("model_name")["mape"]
    f25 = bt[bt.fold == "2025"].set_index("model_name")
    model = str(f24.idxmin())
    return {
        "selected_on": "2024",
        "model": model,
        "mape_2025": float(f25.loc[model, "mape"]),
        "rmse_2025": float(f25.loc[model, "rmse"]),
        "baseline_mape_2025": float(f25.loc["seasonal_naive", "mape"]),
    }


def _plot_backtests(series, customers, reports_dir: Path) -> None:
    years = np.asarray(series.index.year)
    for test_year in (2024, 2025):
        train_s, test_s = series[years < test_year], series[years == test_year]
        fig, ax = plt.subplots(figsize=(9, 4.5))
        try:
            ax.plot(range(1, 13), test_s.to_numpy(), "k-o", lw=2, label="actual")
            for name, make in CANDIDATES.items():
                fc = make(train_s, customers.loc[train_s.index]).predict(len(test_s), None)
                ax.plot(range(1, 13), fc["forecast_mwh"].to_numpy(), "--", label=name)
            ax.set_xlabel("month")
            ax.set_ylabel("MWh")
            ax.set_title(f"Monthly energy backtest {test_year} (trained through {test_year - 1})")
            ax.legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(reports_dir / f"forecast_backtest_{test_year}.png", dpi=110)
        finally:
            plt.close(fig)


def _plot_confusion(metrics: dict, reports_dir: Path) -> None:
    cm = np.array(metrics["confusion_matrix"])
    fig, ax = plt.subplots(figsize=(4.8, 4.2))
    try:
        ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(len(LABELS)), LABELS)
        ax.set_yticks(range(len(LABELS)), LABELS)
        ax.set_xlabel("predicted")
        ax.set_ylabel("actual")
        ax.set_title("Demand level confusion matrix (test year)")
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                        color="white" if cm[i, j] > cm.max() / 2 else "black")
        fig.tight_layout()
        fig.savefig(reports_dir / "demand_confusion_matrix.png", dpi=110)
    finally:
        plt.close(fig)


def _plot_importance(perm: pd.DataFrame, breakdown: pd.DataFrame, reports_dir: Path) -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.5))
    try:
        p = perm.sort_values("importance")
        a1.barh(p["feature"], p["importance"])
        a1.set_title("Demand classifier permutation importance")
        a1.set_xlabel("drop in macro F1")
        x = np.arange(len(breakdown))
        pos = np.zeros(len(breakdown))
        for col in ("trend", "seasonality", "customer_growth"):
            vals = breakdown[col].to_numpy()
            a2.bar(x, vals, bottom=pos, label=col)
            pos = pos + vals
        labels = [f"{y}-{m:02d}" for y, m in zip(breakdown["year"], breakdown["month"])]
        a2.set_xticks(x[::3], labels[::3], rotation=45, fontsize=7)
        a2.set_ylabel("MWh")
        a2.set_title("Forecast breakdown")
        a2.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(reports_dir / "feature_importance.png", dpi=110)
    finally:
        plt.close(fig)


def train(
    db_path: Path,
    models_dir: Path,
    reports_dir: Path,
    dataset_version: str = "synth-v1-seed42",
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, int]:
    db_path, models_dir, reports_dir = Path(db_path), Path(models_dir), Path(reports_dir)
    with connect(db_path) as con:
        check_inputs(con, dataset_version)
        ensure_schema(con)
        anchors = read_anchors(con)
        daily = read_daily(con, dataset_version)
        cfg = load_config(Path(config_path))
        models_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)

        # ---- monthly energy
        series, customers = real_series(anchors, cfg)
        bt = backtest(series, customers)
        best, beats = select_model(bt)
        means = bt.groupby("model_name")[["mape", "rmse"]].mean()
        fc = forecast_monthly(series, customers, best)
        m_metrics = {
            "backtest": bt.to_dict(orient="records"),
            "selected_model": best,
            "beats_baseline": bool(beats),
            "mean_mape": float(means.loc[best, "mape"]),
            "mean_rmse": float(means.loc[best, "rmse"]),
            "baseline_mean_mape": float(means.loc["seasonal_naive", "mape"]),
            "baseline_mean_rmse": float(means.loc["seasonal_naive", "rmse"]),
            "nested": nested_metric(bt),
        }
        breakdown = forecast_breakdown(series, customers, best)
        bd_rows = breakdown.melt(id_vars=["year", "month"], var_name="feature", value_name="importance")
        run_m = save_run(con, "monthly_energy", best, REAL_VERSION, m_metrics, [
            ("forecast_monthly", FC_COLS, fc, {}),
            ("feature_importance", ["feature", "importance", "year", "month"], bd_rows, {"kind": "breakdown"}),
        ])
        joblib.dump(CANDIDATES[best](series, customers), models_dir / f"monthly_energy-{run_m}.joblib")

        # ---- annual peak
        peak = forecast_peak(anchors, fc)
        lfs = _load_factors(anchors)
        lv = np.array(list(lfs.values()))
        p_metrics = {
            "method": "peak_MW = annual_MWh / (load_factor * hours_in_year); central = mean historical LF, "
                      "lo uses max LF, hi uses min LF; hours = 8784 for leap years",
            "load_factors": {str(y): v for y, v in lfs.items()},
            "lf_mean": float(lv.mean()), "lf_max": float(lv.max()), "lf_min": float(lv.min()),
        }
        run_p = save_run(con, "annual_peak", "load_factor", REAL_VERSION, p_metrics, [
            ("forecast_annual_peak", ["year", "peak_mw", "lo", "hi"], peak, {}),
        ])
        joblib.dump({"load_factors": lfs, "lf_mean": p_metrics["lf_mean"]}, models_dir / f"annual_peak-{run_p}.joblib")

        # ---- demand class
        features = build_features(daily, cfg)
        test_year = int(daily["year"].max())
        res = train_demand(features, test_year=test_year)
        perm = permutation_importance_table(res, features, test_year=test_year)
        d_metrics = {**res.metrics, "trained_on": "synthetic", "model_name": res.model_name, "test_year": test_year}
        preds = res.predictions.copy()
        preds["date"] = pd.to_datetime(preds["date"]).dt.strftime("%Y-%m-%d")
        run_d = save_run(con, "demand_class", res.model_name, dataset_version, d_metrics, [
            ("demand_predictions",
             ["date", "predicted_level", "p_high", "p_medium", "p_low", "actual_level"], preds, {}),
            ("feature_importance", ["feature", "importance"], perm, {"kind": "permutation"}),
        ])
        joblib.dump(res.model, models_dir / f"demand_class-{run_d}.joblib")

    (reports_dir / "metrics.json").write_text(json.dumps({
        "monthly_energy": m_metrics,
        "annual_peak": p_metrics,
        "demand_class": d_metrics,
        "backtest": m_metrics["backtest"],
    }, indent=2), encoding="utf-8")
    _plot_backtests(series, customers, reports_dir)
    _plot_confusion(res.metrics, reports_dir)
    _plot_importance(perm, breakdown, reports_dir)
    return {"monthly_energy": run_m, "annual_peak": run_p, "demand_class": run_d}


def _table(reports_dir: Path) -> str:
    m = json.loads((Path(reports_dir) / "metrics.json").read_text(encoding="utf-8"))
    me, ap, dc = m["monthly_energy"], m["annual_peak"], m["demand_class"]
    ne = me["nested"]
    rows = [
        ("task", "model", "key metric", "beats baseline"),
        ("monthly_energy", me["selected_model"],
         f"MAPE {me['mean_mape']:.2f}% (baseline {me['baseline_mean_mape']:.2f}%)", str(me["beats_baseline"])),
        ("  nested", ne["model"],
         f"2025 MAPE {ne['mape_2025']:.2f}% (baseline {ne['baseline_mape_2025']:.2f}%), selected on 2024 only",
         str(ne["mape_2025"] < ne["baseline_mape_2025"])),
        ("annual_peak", "load_factor", f"LF mean {ap['lf_mean']:.3f}", "n/a"),
        ("demand_class", dc["model_name"],
         f"macro F1 {dc['macro_f1']:.3f} (LR baseline {dc['baseline_macro_f1']:.3f}, "
         f"majority {dc['majority_macro_f1']:.3f}); acc {dc['accuracy']:.3f} (majority {dc['majority_accuracy']:.3f})",
         str(dc["macro_f1"] > max(dc["baseline_macro_f1"], dc["majority_macro_f1"]))),
    ]
    w = [max(len(r[i]) for r in rows) for i in range(4)]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train forecasting and demand models from the SQLite DB.")
    ap.add_argument("--db", type=Path, default=Path("database/electroforecast.db"))
    ap.add_argument("--models-dir", type=Path, default=Path("models"))
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--dataset-version", default="synth-v1-seed42")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    a = ap.parse_args(argv)
    try:
        train(a.db, a.models_dir, a.reports_dir, a.dataset_version, a.config)
    except MissingDataError as e:
        print(e)
        return 2
    print(_table(a.reports_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
