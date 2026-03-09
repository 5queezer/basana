from decimal import Decimal
import datetime

import basana as bs
from basana.quant import NormalizedSignal, PortfolioRiskManager


BASE_TS = datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc)


def build_signal(symbol: str, position: bs.Position, exposure: str) -> NormalizedSignal:
    return NormalizedSignal(
        when=BASE_TS,
        pair=bs.Pair(symbol, "USDT"),
        position=position,
        source="test",
        target_gross_exposure=Decimal(exposure),
    )


def test_portfolio_risk_manager_enforces_limits():
    manager = PortfolioRiskManager(max_positions=1, max_gross_exposure=Decimal("1.0"))

    first = manager.apply_signal(build_signal("BTC", bs.Position.LONG, "0.6"), Decimal("100"))
    assert first.accepted is True

    second = manager.apply_signal(build_signal("ETH", bs.Position.LONG, "0.6"), Decimal("50"))
    assert second.accepted is False
    assert second.reason == "max positions exceeded"


def test_portfolio_risk_manager_flattens_existing_position():
    manager = PortfolioRiskManager(max_positions=2, max_gross_exposure=Decimal("1.0"))
    manager.apply_signal(build_signal("BTC", bs.Position.LONG, "0.6"), Decimal("100"))

    flatten = manager.apply_signal(build_signal("BTC", bs.Position.NEUTRAL, "0"), Decimal("101"))
    assert flatten.accepted is True
    assert manager.active_positions == 0
    assert manager.gross_exposure == Decimal("0")
