# Basana
#
# Copyright 2026 Christian Pojoni
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from decimal import Decimal
from unittest.mock import MagicMock
import datetime

import basana as bs
from basana.core import enums
from basana.core.risk.perp_limits import LiquidationDistanceLimit, MarginUtilizationLimit, MaxLeverageLimit
from basana.core.risk.types import PortfolioSnapshot

utc = datetime.timezone.utc
btc_pair = bs.Pair("BTC", "USD")
eth_pair = bs.Pair("ETH", "USD")


def _snapshot(
    gross_exposure=Decimal("100000"),
    total_equity=Decimal("10000"),
    positions=None,
):
    if positions is None:
        positions = {}
    return PortfolioSnapshot(
        when=datetime.datetime(2026, 1, 1, tzinfo=utc),
        positions=positions,
        total_equity=total_equity,
        gross_exposure=gross_exposure,
        net_exposure=gross_exposure,
        realized_pnl_today=Decimal(0),
        unrealized_pnl=Decimal(0),
    )


def _signal(pairs=None):
    sig = MagicMock()
    if pairs is None:
        pairs = [(btc_pair, enums.Position.LONG)]
    sig.get_pairs.return_value = pairs
    return sig


# --- MaxLeverageLimit ---


class TestMaxLeverageLimit:
    def test_within_limit_approved(self):
        limit = MaxLeverageLimit(max_leverage=Decimal("10"))
        result = limit.check(_signal(), _snapshot(gross_exposure=Decimal("50000"), total_equity=Decimal("10000")))
        assert result.approved

    def test_at_exact_limit_approved(self):
        limit = MaxLeverageLimit(max_leverage=Decimal("10"))
        result = limit.check(_signal(), _snapshot(gross_exposure=Decimal("100000"), total_equity=Decimal("10000")))
        assert result.approved

    def test_exceeds_limit_rejected(self):
        limit = MaxLeverageLimit(max_leverage=Decimal("10"))
        result = limit.check(_signal(), _snapshot(gross_exposure=Decimal("110000"), total_equity=Decimal("10000")))
        assert not result.approved
        assert "leverage" in result.reason.lower()

    def test_close_signal_allowed_when_over_limit(self):
        limit = MaxLeverageLimit(max_leverage=Decimal("10"))
        sig = _signal(pairs=[(btc_pair, enums.Position.NEUTRAL)])
        result = limit.check(sig, _snapshot(gross_exposure=Decimal("200000"), total_equity=Decimal("10000")))
        assert result.approved

    def test_zero_equity_rejected(self):
        limit = MaxLeverageLimit(max_leverage=Decimal("10"))
        result = limit.check(_signal(), _snapshot(total_equity=Decimal("0")))
        assert not result.approved
        assert "zero" in result.reason.lower()


# --- LiquidationDistanceLimit ---


class TestLiquidationDistanceLimit:
    def test_safe_distance_approved(self):
        limit = LiquidationDistanceLimit(min_distance_pct=Decimal("5"))
        limit.update_liquidation_distance(btc_pair, Decimal("10"))
        result = limit.check(_signal(), _snapshot())
        assert result.approved

    def test_too_close_rejected(self):
        limit = LiquidationDistanceLimit(min_distance_pct=Decimal("5"))
        limit.update_liquidation_distance(btc_pair, Decimal("3"))
        result = limit.check(_signal(), _snapshot())
        assert not result.approved
        assert "liquidation" in result.reason.lower()

    def test_close_signal_allowed_when_near_liquidation(self):
        limit = LiquidationDistanceLimit(min_distance_pct=Decimal("5"))
        limit.update_liquidation_distance(btc_pair, Decimal("2"))
        sig = _signal(pairs=[(btc_pair, enums.Position.NEUTRAL)])
        result = limit.check(sig, _snapshot())
        assert result.approved

    def test_no_meta_approved(self):
        limit = LiquidationDistanceLimit(min_distance_pct=Decimal("5"))
        result = limit.check(_signal(), _snapshot())
        assert result.approved

    def test_remove_pair_clears_meta(self):
        limit = LiquidationDistanceLimit(min_distance_pct=Decimal("5"))
        limit.update_liquidation_distance(btc_pair, Decimal("2"))
        limit.remove_pair(btc_pair)
        result = limit.check(_signal(), _snapshot())
        assert result.approved

    def test_different_pair_not_blocked(self):
        limit = LiquidationDistanceLimit(min_distance_pct=Decimal("5"))
        limit.update_liquidation_distance(eth_pair, Decimal("2"))
        sig = _signal(pairs=[(btc_pair, enums.Position.LONG)])
        result = limit.check(sig, _snapshot())
        assert result.approved

    def test_initial_meta_from_constructor(self):
        meta = {btc_pair: Decimal("1")}
        limit = LiquidationDistanceLimit(min_distance_pct=Decimal("5"), position_meta=meta)
        result = limit.check(_signal(), _snapshot())
        assert not result.approved


# --- MarginUtilizationLimit ---


class TestMarginUtilizationLimit:
    def test_within_limit_approved(self):
        limit = MarginUtilizationLimit(max_utilization_pct=Decimal("80"))
        result = limit.check(
            _signal(),
            _snapshot(gross_exposure=Decimal("7000"), total_equity=Decimal("10000")),
        )
        assert result.approved

    def test_exceeds_limit_rejected(self):
        limit = MarginUtilizationLimit(max_utilization_pct=Decimal("80"))
        result = limit.check(
            _signal(),
            _snapshot(gross_exposure=Decimal("9000"), total_equity=Decimal("10000")),
        )
        assert not result.approved
        assert "utilization" in result.reason.lower()

    def test_close_signal_allowed_when_over_limit(self):
        limit = MarginUtilizationLimit(max_utilization_pct=Decimal("80"))
        sig = _signal(pairs=[(btc_pair, enums.Position.NEUTRAL)])
        result = limit.check(
            sig, _snapshot(gross_exposure=Decimal("9500"), total_equity=Decimal("10000")),
        )
        assert result.approved

    def test_zero_equity_rejected(self):
        limit = MarginUtilizationLimit(max_utilization_pct=Decimal("80"))
        result = limit.check(_signal(), _snapshot(total_equity=Decimal("0")))
        assert not result.approved
