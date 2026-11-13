def test_requires_login(client):
    assert client.get("/api/forecast/monthly").status_code == 401


def test_no_model_returns_404(client_logged_in_empty):
    r = client_logged_in_empty.get("/api/forecast/monthly")
    assert r.status_code == 404 and r.json["error"] == "No trained model yet"


def test_models_active_empty_is_200(client_logged_in_empty):
    r = client_logged_in_empty.get("/api/models/active")
    assert r.status_code == 200 and r.json == {"runs": []}


def test_models_active_lists_three(client_logged_in_trained):
    runs = client_logged_in_trained.get("/api/models/active").json["runs"]
    assert {r["task"] for r in runs} == {"monthly_energy", "annual_peak", "demand_class"}
    assert all(isinstance(r["metrics"], dict) for r in runs)
    src = {r["task"]: r["data_source"] for r in runs}
    assert src["demand_class"] == "synthetic" and src["monthly_energy"] == "real"


def test_monthly_forecast_shape(client_logged_in_trained):
    j = client_logged_in_trained.get("/api/forecast/monthly").json
    assert j["data_source"] == "real" and len(j["history"]) == 72 and len(j["forecast"]) == 24
    assert set(j["forecast"][0]) == {"year", "month", "forecast_mwh", "lo80", "hi80", "lo95", "hi95"}
    assert j["model"]["task"] == "monthly_energy"
    assert j["dataset_version"] == j["model"]["dataset_version"] == "real:guimelco_residential_2020_2025"


def test_peak_forecast_shape(client_logged_in_trained):
    j = client_logged_in_trained.get("/api/forecast/peak").json
    assert j["data_source"] == "real" and len(j["history"]) >= 1
    assert set(j["history"][0]) == {"year", "peak_mw"}
    assert j["dataset_version"] == j["model"]["dataset_version"]
    assert set(j["forecast"][0]) == {"year", "peak_mw", "lo", "hi"}


def test_demand_daily_defaults_and_validation(client_logged_in_trained):
    j = client_logged_in_trained.get("/api/demand/daily").json
    assert j["data_source"] == "synthetic" and len(j["days"]) == 30 and j["dataset_version"]
    dates = [d["date"] for d in j["days"]]
    assert dates == sorted(dates)
    assert set(j["days"][0]) == {"date", "peak_mw", "actual_level", "predicted_level", "p_high", "p_medium", "p_low"}
    assert client_logged_in_trained.get("/api/demand/daily?from=2025-02-01&to=2025-01-01").status_code == 400
    assert client_logged_in_trained.get("/api/demand/daily?from=yesterday").status_code == 400


def test_demand_daily_range_cap_and_one_sided(client_logged_in_trained):
    c = client_logged_in_trained
    r = c.get("/api/demand/daily?from=2020-01-01&to=2025-12-31")
    assert r.status_code == 400 and "400" in r.json["error"]
    last = c.get("/api/demand/daily").json["days"][-1]["date"]
    j = c.get(f"/api/demand/daily?from={last}").json
    assert [d["date"] for d in j["days"]] == [last]
    j = c.get(f"/api/demand/daily?from={last}&to={last}").json
    assert len(j["days"]) == 1


def test_explain_has_both_sources(client_logged_in_trained):
    j = client_logged_in_trained.get("/api/explain").json
    assert j["classifier"]["data_source"] == "synthetic" and j["forecast"]["data_source"] == "real"
    assert j["classifier"]["dataset_version"] == j["classifier"]["model"]["dataset_version"]
    assert j["forecast"]["dataset_version"] == "real:guimelco_residential_2020_2025"
    imp = [r["importance"] for r in j["classifier"]["importance"]]
    assert imp and imp == sorted(imp, reverse=True)
    bd = j["forecast"]["breakdown"]
    assert bd and set(bd[0]) == {"year", "month", "trend", "seasonality", "customer_growth"}
    keys = [(r["year"], r["month"]) for r in bd]
    assert keys == sorted(set(keys))


def test_explain_404_without_models(client_logged_in_empty):
    r = client_logged_in_empty.get("/api/explain")
    assert r.status_code == 404 and r.json["error"] == "No trained model yet"


def test_every_forecast_month_has_a_breakdown_to_explain(client_logged_in_trained):
    # the chart's hover card explains each forecast month from this breakdown
    forecast = client_logged_in_trained.get("/api/forecast/monthly").json["forecast"]
    bd = {(r["year"], r["month"]): r for r in client_logged_in_trained.get("/api/explain").json["forecast"]["breakdown"]}
    for row in forecast:
        parts = bd[(row["year"], row["month"])]
        assert parts["trend"] is not None and parts["seasonality"] is not None
