import pytest
from src.strategies import STRATEGY_REGISTRY

@pytest.mark.strategy
def test_strategy_registry_keys():
    # Ensure all expected strategies are present
    expected = [
        "ORB", "VWAPBounce", "TrendFollowing", "OrderFlow",
        "SwingBreakout", "EMACrossover", "Pullback",
        "ORBIntraday", "VWAPReversion",
        "IronCondor", "Butterfly", "LongStrangle",
        "BullCallSpread", "BearPutSpread", "RatioSpread", "CalendarSpread",
        "LongStraddle", "VIXTrading",
        "DeltaHedging", "PortfolioHedge", "PairTrading",
        "CrossSectionalMomentum", "VolatilityArbitrage", "PairsFinder",
        "EarningsMomentum", "GapFill", "MomentumRotation", "SectorRotation",
        "Universal"
    ]
    for key in expected:
        assert key in STRATEGY_REGISTRY, f"Missing strategy: {key}"

def test_strategy_registry_types():
    # Ensure all registry values are classes or callables
    for name, cls in STRATEGY_REGISTRY.items():
        assert callable(cls), f"Strategy {name} is not callable"
