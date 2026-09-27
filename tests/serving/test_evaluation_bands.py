"""Erro por faixa de gasto: cada conta-mês cai numa faixa só, e os erros batem com o cálculo manual."""

import numpy as np
import pytest

from the_bank_project.serving.evaluation import BANDS, error_by_band

Y = np.array([1_000.0, 4_999.0, 5_000.0, 12_000.0, 30_000.0, 80_000.0, 200_000.0])


def test_every_row_lands_in_exactly_one_band_and_boundaries_belong_to_the_upper_band() -> None:
    bands = error_by_band(Y, Y * 0.9, Y * 1.2)
    assert sum(b.n for b in bands) == len(Y)
    by_label = {b.label: b.n for b in bands}
    assert by_label == {"Até 5 mil": 2, "5 a 10 mil": 1, "10 a 20 mil": 1, "20 a 50 mil": 1, "Acima de 50 mil": 2}


def test_errors_match_a_manual_calculation() -> None:
    pred, base = Y - 100, Y + 300
    top = error_by_band(Y, pred, base)[-1]  # 80 mil e 200 mil
    assert (top.model_mae, top.baseline_mae) == pytest.approx((100.0, 300.0))
    assert top.upper is None and top.lower == 50_000


def test_empty_bands_are_left_out_and_bands_are_contiguous() -> None:
    only_small = np.array([100.0, 200.0])
    assert [b.label for b in error_by_band(only_small, only_small, only_small)] == ["Até 5 mil"]
    edges = [(lo, hi) for _, lo, hi in BANDS]
    assert all(edges[i][1] == edges[i + 1][0] for i in range(len(edges) - 1))  # sem buracos nem sobreposição
