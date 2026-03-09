from decimal import Decimal
import datetime

import pytest

import basana as bs
from basana.quant import NormalizedSignal


def test_normalized_signal_validates_numeric_fields():
    signal = NormalizedSignal(
        when=datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc),
        pair=bs.Pair("BTC", "USDT"),
        position=bs.Position.LONG,
        source="unit-test",
        strength=Decimal("0.7"),
        target_gross_exposure=Decimal("0.5"),
    )
    assert signal.source == "unit-test"
    assert signal.strength == Decimal("0.7")

    with pytest.raises(ValueError):
        NormalizedSignal(
            when=datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc),
            pair=bs.Pair("BTC", "USDT"),
            position=bs.Position.LONG,
            source="unit-test",
            strength=Decimal("-1"),
        )
