import numpy as np
import pandas as pd
import pytest
from sklearn.compose import TransformedTargetRegressor

from the_bank_project.training.evaluate import NAIVE_BASELINES, regression_metrics, skill_score
from the_bank_project.training.models import CANDIDATES, make_estimator, trial_params

TINY = {"random_forest": {"n_estimators": 10}, "gradient_boosting": {"max_iter": 10}, "xgboost": {"n_estimators": 10}}


def test_regression_metrics_known_values():
    m = regression_metrics(np.array([10.0, 20.0, 30.0]), np.array([12.0, 18.0, 33.0]))
    assert m["mae"] == pytest.approx(7 / 3)
    assert m["rmse"] == pytest.approx(np.sqrt(17 / 3))
    assert m["r2"] == pytest.approx(1 - 17 / 200)
    assert set(m) == {"mae", "rmse", "r2"}  # as mesmas métricas em todos os runs


def test_skill_score_is_positive_only_when_beating_the_naive_baseline():
    assert skill_score(80.0, 100.0) == pytest.approx(0.2)
    assert skill_score(120.0, 100.0) < 0


def test_naive_baselines_use_features_present_in_the_service():
    assert set(NAIVE_BASELINES.values()) == {"outflow_amount", "outflow_3m_avg"}


def test_trial_params_start_with_defaults_have_no_duplicates_and_are_reproducible():
    cand = next(c for c in CANDIDATES if c.name == "xgboost")
    trials = trial_params(cand, 5, seed=1)
    assert trials[0] == cand.defaults and len(trials) == len({str(sorted(t.items())) for t in trials})
    assert trials == trial_params(cand, 5, seed=1) and trials != trial_params(cand, 5, seed=2)
    assert trial_params(cand, 0, seed=1) == [cand.defaults]


def test_linear_model_has_no_search_space():
    linear = next(c for c in CANDIDATES if c.name == "regressao_linear")
    assert trial_params(linear, 8, seed=1) == [{}]


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.name)
@pytest.mark.parametrize("log_target", [True, False])
def test_every_candidate_fits_handles_nan_and_predicts_on_the_original_scale(candidate, log_target: bool, dataset):  # type: ignore[no-untyped-def]
    params = {**candidate.defaults, **TINY.get(candidate.name, {})}
    model = make_estimator(candidate, params, seed=0, log_target=log_target).fit(dataset.X, dataset.y)
    pred = model.predict(dataset.X)
    assert dataset.X.isna().any().any() and np.isfinite(pred).all()
    assert regression_metrics(dataset.y, pred)["r2"] > 0.5  # o sinal sintético é forte; escala revertida
    assert pd.Series(pred).between(0, 200_000).all()


def test_linear_baseline_ignores_log_target_but_trees_use_it():
    by_name = {c.name: c for c in CANDIDATES}
    assert not isinstance(
        make_estimator(by_name["regressao_linear"], {}, 0, log_target=True), TransformedTargetRegressor
    )
    assert isinstance(make_estimator(by_name["xgboost"], {}, 0, log_target=True), TransformedTargetRegressor)
    assert not isinstance(make_estimator(by_name["xgboost"], {}, 0, log_target=False), TransformedTargetRegressor)
