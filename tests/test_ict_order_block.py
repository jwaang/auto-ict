"""The four order-block conditions, each rejected on its own.

`smc.ob()` implements none of these, so the point of the tests is that a
candidate failing any single condition is thrown out — otherwise the detector
drifts back toward "last opposing candle before a move", which is what has been
measured all along.
"""
import pandas as pd
import pytest

from research.ict_order_block import detect_order_blocks


def bars(rows):
    """rows: list of (open, high, low, close)."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def fvg(idx, kind="bullish"):
    return {"candle_index": idx, "type": kind}


def mss(idx, direction="bullish"):
    return {"index": idx, "direction": direction}


# A valid bullish setup: candle 0 is a down-close; candle 1 takes out its low
# and closes above its high.
VALID_BULL = [
    (100, 102, 95, 96),     # 0: down-close opposing candle, range 95-102
    (96, 112, 93, 110),     # 1: grabs 93 < 95, closes 110 > 102
    (110, 115, 108, 114),
    (114, 118, 112, 117),
]


class TestValidSetup:
    def test_all_four_conditions_met_yields_a_block(self):
        blocks, funnel = detect_order_blocks(bars(VALID_BULL), [fvg(2)], [mss(2)])
        assert funnel["accepted"] == 1
        b = blocks[0]
        assert b["type"] == "bullish"
        assert (b["high"], b["low"]) == (102, 95)
        assert b["mean_threshold"] == pytest.approx(98.5)
        assert b["candle_index"] == 0
        assert b["impulse_index"] == 1
        # The confirming shift is when the block becomes knowable.
        assert b["confirmed_index"] == 2


class TestEachConditionRejects:
    def test_rejects_when_the_impulse_does_not_grab_the_low(self):
        rows = list(VALID_BULL)
        rows[1] = (96, 112, 97, 110)      # low 97 does not take out 95
        blocks, funnel = detect_order_blocks(bars(rows), [fvg(2)], [mss(2)])
        assert blocks == [] and funnel["no_grab"] >= 1

    def test_rejects_when_the_close_does_not_engulf(self):
        rows = list(VALID_BULL)
        rows[1] = (96, 112, 93, 101)      # closes 101, below the 102 high
        blocks, funnel = detect_order_blocks(bars(rows), [fvg(2)], [mss(2)])
        assert blocks == [] and funnel["no_engulf"] >= 1

    def test_rejects_when_no_fvg_prints(self):
        blocks, funnel = detect_order_blocks(bars(VALID_BULL), [], [mss(2)])
        assert blocks == [] and funnel["no_fvg"] >= 1

    def test_rejects_when_no_mss_confirms(self):
        blocks, funnel = detect_order_blocks(bars(VALID_BULL), [fvg(2)], [])
        assert blocks == [] and funnel["no_mss"] >= 1

    def test_rejects_an_up_close_candle_as_a_bullish_order_block(self):
        rows = list(VALID_BULL)
        rows[0] = (95, 102, 94, 101)      # up-close, so not a bullish OB base
        blocks, _ = detect_order_blocks(bars(rows), [fvg(2)], [mss(2)])
        assert all(b["type"] != "bullish" for b in blocks)


class TestPolarity:
    def test_fvg_of_the_wrong_polarity_does_not_satisfy_the_condition(self):
        blocks, funnel = detect_order_blocks(bars(VALID_BULL),
                                             [fvg(2, "bearish")], [mss(2)])
        assert blocks == [] and funnel["no_fvg"] >= 1

    def test_mss_of_the_wrong_direction_does_not_confirm(self):
        blocks, funnel = detect_order_blocks(bars(VALID_BULL), [fvg(2)],
                                             [mss(2, "bearish")])
        assert blocks == [] and funnel["no_mss"] >= 1

    def test_bearish_setup_mirrors(self):
        rows = [
            (96, 105, 94, 101),           # 0: up-close opposing candle
            (101, 107, 90, 92),           # 1: grabs 105, closes 92 < 94
            (92, 94, 88, 90),
            (90, 92, 86, 88),
        ]
        blocks, funnel = detect_order_blocks(bars(rows), [fvg(2, "bearish")],
                                             [mss(2, "bearish")])
        assert funnel["accepted"] == 1
        assert blocks[0]["type"] == "bearish"
        assert (blocks[0]["high"], blocks[0]["low"]) == (105, 94)


class TestWindows:
    def test_fvg_outside_the_window_does_not_count(self):
        blocks, funnel = detect_order_blocks(bars(VALID_BULL), [fvg(3)], [mss(2)],
                                             fvg_within=1)
        assert blocks == [] and funnel["no_fvg"] >= 1

    def test_mss_outside_the_window_does_not_count(self):
        blocks, funnel = detect_order_blocks(bars(VALID_BULL), [fvg(2)], [mss(3)],
                                             mss_within=1)
        assert blocks == [] and funnel["no_mss"] >= 1


class TestConfirmationIndex:
    def test_confirmed_index_is_the_bar_structure_shifted(self):
        blocks, _ = detect_order_blocks(bars(VALID_BULL), [fvg(2)], [mss(3)])
        assert blocks[0]["confirmed_index"] == 3

    def test_confirmed_index_is_never_before_the_impulse(self):
        blocks, _ = detect_order_blocks(bars(VALID_BULL), [fvg(2)], [mss(2)])
        assert blocks[0]["confirmed_index"] > blocks[0]["candle_index"]


class TestNoLookAhead:
    def test_blocks_carry_no_future_derived_fields(self):
        """`mitigated` is what made a full-frame pass a 97% win-rate artifact."""
        blocks, _ = detect_order_blocks(bars(VALID_BULL), [fvg(2)], [mss(2)])
        assert not any(k in blocks[0] for k in ("mitigated", "mitigated_index", "filled"))
