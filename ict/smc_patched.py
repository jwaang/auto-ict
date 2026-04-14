from functools import wraps
import pandas as pd
import numpy as np
from pandas import DataFrame, Series
from datetime import datetime

def inputvalidator(input_="ohlc"):
    def dfcheck(func):
        @wraps(func)
        def wrap(*args, **kwargs):
            args = list(args)
            i = 0 if isinstance(args[0], pd.DataFrame) else 1

            args[i] = args[i].rename(columns={c: c.lower() for c in args[i].columns})

            inputs = {
                "o": "open",
                "h": "high",
                "l": "low",
                "c": kwargs.get("column", "close").lower(),
                "v": "volume",
            }

            if inputs["c"] != "close":
                kwargs["column"] = inputs["c"]

            for l in input_:
                if inputs[l] not in args[i].columns:
                    raise LookupError(
                        'Must have a dataframe column named "{0}"'.format(inputs[l])
                    )

            return func(*args, **kwargs)

        return wrap

    return dfcheck


def apply(decorator):
    def decorate(cls):
        for attr in cls.__dict__:
            if callable(getattr(cls, attr)):
                setattr(cls, attr, decorator(getattr(cls, attr)))

        return cls

    return decorate


@apply(inputvalidator(input_="ohlc"))
class smc:
    __version__ = "0.0.27"

    @classmethod
    def fvg(cls, ohlc: DataFrame, join_consecutive=False) -> Series:
        """
        FVG - Fair Value Gap (causal / no look-ahead bias)

        A fair value gap is when the previous high is lower than the next low
        if the current candle is bullish, or when the previous low is higher
        than the next high if the current candle is bearish.

        The detection uses shift(-1) to check the 3rd candle, then shifts
        all outputs forward by 1 bar so the signal only appears once the
        confirming (3rd) candle has closed. This prevents look-ahead bias.

        parameters:
        join_consecutive: bool - merge consecutive same-direction FVGs

        returns:
        FVG = 1 if bullish fair value gap, -1 if bearish fair value gap
        Top = the top of the fair value gap
        Bottom = the bottom of the fair value gap
        MitigatedIndex = the index of the candle that mitigated the fair value gap
        """

        fvg = np.where(
            (
                (ohlc["high"].shift(1) < ohlc["low"].shift(-1))
                & (ohlc["close"] > ohlc["open"])
            )
            | (
                (ohlc["low"].shift(1) > ohlc["high"].shift(-1))
                & (ohlc["close"] < ohlc["open"])
            ),
            np.where(ohlc["close"] > ohlc["open"], 1, -1),
            np.nan,
        ).copy()

        top = np.where(
            ~np.isnan(fvg),
            np.where(
                ohlc["close"] > ohlc["open"],
                ohlc["low"].shift(-1),
                ohlc["low"].shift(1),
            ),
            np.nan,
        ).copy()

        bottom = np.where(
            ~np.isnan(fvg),
            np.where(
                ohlc["close"] > ohlc["open"],
                ohlc["high"].shift(1),
                ohlc["high"].shift(-1),
            ),
            np.nan,
        ).copy()

        # if there are multiple consecutive fvg then join them together using the highest top and lowest bottom and the last index
        if join_consecutive:
            for i in range(len(fvg) - 1):
                if fvg[i] == fvg[i + 1]:
                    top[i + 1] = max(top[i], top[i + 1])
                    bottom[i + 1] = min(bottom[i], bottom[i + 1])
                    fvg[i] = top[i] = bottom[i] = np.nan

        # Causal shift: move signals forward by 1 bar so the FVG is only
        # visible after the 3rd candle (the confirming candle) has closed.
        fvg = np.roll(fvg, 1); fvg[0] = np.nan
        top = np.roll(top, 1); top[0] = np.nan
        bottom = np.roll(bottom, 1); bottom[0] = np.nan

        # Mitigation: check when price returns into the FVG after it forms.
        # Since we shifted forward by 1, start checking from i + 1 (not i + 2).
        ohlc_low_arr = ohlc["low"].values
        ohlc_high_arr = ohlc["high"].values
        n_bars = len(ohlc)
        mitigated_index = np.zeros(n_bars, dtype=np.int32)
        fvg_indices = np.where(~np.isnan(fvg))[0]
        for i in fvg_indices:
            if i + 1 >= n_bars:
                continue
            if fvg[i] == 1:
                # Bullish FVG mitigated when low <= top
                remaining = ohlc_low_arr[i + 1:]
                hits = np.where(remaining <= top[i])[0]
            else:
                # Bearish FVG mitigated when high >= bottom
                remaining = ohlc_high_arr[i + 1:]
                hits = np.where(remaining >= bottom[i])[0]
            if len(hits) > 0:
                mitigated_index[i] = hits[0] + i + 1

        mitigated_index = np.where(np.isnan(fvg), np.nan, mitigated_index)

        return pd.concat(
            [
                pd.Series(fvg, name="FVG"),
                pd.Series(top, name="Top"),
                pd.Series(bottom, name="Bottom"),
                pd.Series(mitigated_index, name="MitigatedIndex"),
            ],
            axis=1,
        )

    @classmethod
    def swing_highs_lows(cls, ohlc: DataFrame, swing_length: int = 50) -> Series:
        """
        Swing Highs and Lows (causal / no look-ahead bias)

        A swing high is confirmed when the candidate bar's high is the highest
        in the lookback window AND subsequent confirm_bars all have lower highs.
        A swing low is confirmed analogously with lows.

        This uses only past and present data — no future bars are accessed.

        parameters:
        swing_length: int - bars for both lookback and confirmation

        returns:
        HighLow = 1 if swing high, -1 if swing low
        Level = the level of the swing high or low
        """

        highs = ohlc["high"].values
        lows = ohlc["low"].values
        n = len(ohlc)
        lookback = swing_length
        confirm_bars = swing_length

        swing_highs_lows = np.full(n, np.nan)
        # Store the actual swing price level separately, since the signal
        # is emitted at the confirmation bar (i), not the candidate bar.
        swing_level = np.full(n, np.nan)

        # Precompute rolling max/min for lookback windows (vectorized)
        # rolling_high_max[c] = max of highs[c-lookback : c+1]
        # rolling_low_min[c] = min of lows[c-lookback : c+1]
        _high_series = pd.Series(highs)
        _low_series = pd.Series(lows)
        rolling_high_max = _high_series.rolling(window=lookback + 1, min_periods=lookback + 1).max().values
        rolling_low_min = _low_series.rolling(window=lookback + 1, min_periods=lookback + 1).min().values

        # Precompute forward-looking confirmation max/min
        # For confirmation bar i, we need max of highs[candidate+1 : i+1] where candidate = i - confirm_bars
        # That's max of highs[i - confirm_bars + 1 : i + 1] = rolling max over confirm_bars ending at i
        confirm_high_max = _high_series.rolling(window=confirm_bars, min_periods=confirm_bars).max().values
        confirm_low_min = _low_series.rolling(window=confirm_bars, min_periods=confirm_bars).min().values

        for i in range(lookback + confirm_bars, n):
            candidate = i - confirm_bars

            # Swing high: candidate is highest in lookback (use precomputed rolling max)
            if highs[candidate] == rolling_high_max[candidate]:
                # Confirm: max of highs[candidate+1:i+1] < highs[candidate]
                # confirm_high_max[i] = max of highs[i-confirm_bars+1 : i+1] = max of highs[candidate+1:i+1]
                if confirm_high_max[i] < highs[candidate]:
                    # Signal emitted at confirmation bar (i), not candidate.
                    # This ensures downstream code (BOS/ChoCH, OB) cannot use
                    # this swing before it was actually knowable.
                    swing_highs_lows[i] = 1
                    swing_level[i] = highs[candidate]

            # Swing low: candidate is lowest in lookback (use precomputed rolling min)
            if lows[candidate] == rolling_low_min[candidate]:
                # Confirm: min of lows[candidate+1:i+1] > lows[candidate]
                if confirm_low_min[i] > lows[candidate]:
                    swing_highs_lows[i] = -1
                    swing_level[i] = lows[candidate]

        while True:
            positions = np.where(~np.isnan(swing_highs_lows))[0]

            if len(positions) < 2:
                break

            current = swing_highs_lows[positions[:-1]]
            next_vals = swing_highs_lows[positions[1:]]

            # Use swing_level for price comparisons (not OHLC at signal index,
            # since signal is at the confirmation bar, not the swing price bar)
            cur_levels = swing_level[positions[:-1]]
            next_levels = swing_level[positions[1:]]

            index_to_remove = np.zeros(len(positions), dtype=bool)

            consecutive_highs = (current == 1) & (next_vals == 1)
            index_to_remove[:-1] |= consecutive_highs & (cur_levels < next_levels)
            index_to_remove[1:] |= consecutive_highs & (cur_levels >= next_levels)

            consecutive_lows = (current == -1) & (next_vals == -1)
            index_to_remove[:-1] |= consecutive_lows & (cur_levels > next_levels)
            index_to_remove[1:] |= consecutive_lows & (cur_levels <= next_levels)

            if not index_to_remove.any():
                break

            swing_highs_lows[positions[index_to_remove]] = np.nan
            swing_level[positions[index_to_remove]] = np.nan

        positions = np.where(~np.isnan(swing_highs_lows))[0]

        # NOTE: No boundary swings are injected at start or end.
        # The original library fabricated swings at bar 0 and the last bar.
        # This creates false structure context (OTE, premium/discount) from
        # invented price action. Early windows remain structure-incomplete
        # until enough real confirmed swings exist.

        # Use the pre-computed swing_level which stores the actual swing price
        # (from the candidate bar), not the OHLC price at the signal index.
        return pd.concat(
            [
                pd.Series(swing_highs_lows, name="HighLow"),
                pd.Series(swing_level, name="Level"),
            ],
            axis=1,
        )

    @classmethod
    def bos_choch(
        cls, ohlc: DataFrame, swing_highs_lows: DataFrame, close_break: bool = True
    ) -> Series:
        """
        BOS - Break of Structure
        CHoCH - Change of Character
        these are both indications of market structure changing

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        close_break: bool - if True then the break of structure will be mitigated based on the close of the candle otherwise it will be the high/low.

        returns:
        BOS = 1 if bullish break of structure, -1 if bearish break of structure
        CHOCH = 1 if bullish change of character, -1 if bearish change of character
        Level = the level of the break of structure or change of character
        BrokenIndex = the index of the candle that broke the level
        """

        swing_highs_lows = swing_highs_lows.copy()

        level_order = []
        highs_lows_order = []

        shl_hl_arr = swing_highs_lows["HighLow"].values
        shl_lv_arr = swing_highs_lows["Level"].values
        n_shl = len(shl_hl_arr)

        bos = np.zeros(len(ohlc), dtype=np.int32)
        choch = np.zeros(len(ohlc), dtype=np.int32)
        level = np.zeros(len(ohlc), dtype=np.float32)

        last_positions = []

        for i in range(n_shl):
            if not np.isnan(shl_hl_arr[i]):
                level_order.append(shl_lv_arr[i])
                highs_lows_order.append(shl_hl_arr[i])
                if len(level_order) >= 4:
                    # Emit BOS/CHoCH at bar i (where the 4th swing makes
                    # the pattern knowable), NOT at last_positions[-2].
                    h0, h1, h2, h3 = highs_lows_order[-4], highs_lows_order[-3], highs_lows_order[-2], highs_lows_order[-1]
                    l0, l1, l2, l3 = level_order[-4], level_order[-3], level_order[-2], level_order[-1]

                    # bullish bos: pattern [-1, 1, -1, 1] with l0 < l2 < l1 < l3
                    if h0 == -1 and h1 == 1 and h2 == -1 and h3 == 1 and l0 < l2 < l1 < l3:
                        bos[i] = 1
                        level[i] = l1

                    # bearish bos: pattern [1, -1, 1, -1] with l0 > l2 > l1 > l3
                    if h0 == 1 and h1 == -1 and h2 == 1 and h3 == -1 and l0 > l2 > l1 > l3:
                        bos[i] = -1
                        level[i] = l1

                    # bullish choch: pattern [-1, 1, -1, 1] with l3 > l1 > l0 > l2
                    if h0 == -1 and h1 == 1 and h2 == -1 and h3 == 1 and l3 > l1 > l0 > l2:
                        choch[i] = 1
                        level[i] = l1

                    # bearish choch: pattern [1, -1, 1, -1] with l3 < l1 < l0 < l2
                    if h0 == 1 and h1 == -1 and h2 == 1 and h3 == -1 and l3 < l1 < l0 < l2:
                        choch[i] = -1
                        level[i] = l1

                last_positions.append(i)

        break_col = ohlc["close" if close_break else "high"].values
        break_col_low = ohlc["close" if close_break else "low"].values
        n_ohlc = len(ohlc)

        broken = np.zeros(n_ohlc, dtype=np.int32)
        signal_indices = np.where(np.logical_or(bos != 0, choch != 0))[0]
        n_signals = len(signal_indices)
        for si in range(n_signals):
            i = signal_indices[si]
            # if the bos is 1 then check if the candles high has gone above the level
            if bos[i] == 1 or choch[i] == 1:
                remaining = break_col[i + 2:n_ohlc]
                hits = np.where(remaining > level[i])[0]
            # if the bos is -1 then check if the candles low has gone below the level
            elif bos[i] == -1 or choch[i] == -1:
                remaining = break_col_low[i + 2:n_ohlc]
                hits = np.where(remaining < level[i])[0]
            else:
                continue
            if len(hits) > 0:
                j = hits[0] + i + 2
                broken[i] = j
                # Only scan PRIOR signals (k < i) — use index to limit scan
                for sk in range(si):
                    k = signal_indices[sk]
                    if broken[k] >= j:
                        bos[k] = 0
                        choch[k] = 0
                        level[k] = 0

        # remove the ones that aren't broken
        for i in np.where(
            np.logical_and(np.logical_or(bos != 0, choch != 0), broken == 0)
        )[0]:
            bos[i] = 0
            choch[i] = 0
            level[i] = 0

        # replace all the 0s with np.nan
        bos = np.where(bos != 0, bos, np.nan)
        choch = np.where(choch != 0, choch, np.nan)
        level = np.where(level != 0, level, np.nan)
        broken = np.where(broken != 0, broken, np.nan)

        bos = pd.Series(bos, name="BOS")
        choch = pd.Series(choch, name="CHOCH")
        level = pd.Series(level, name="Level")
        broken = pd.Series(broken, name="BrokenIndex")

        return pd.concat([bos, choch, level, broken], axis=1)

    @classmethod
    def ob(
        cls,
        ohlc: DataFrame,
        swing_highs_lows: DataFrame,
        close_mitigation: bool = False,
    ) -> Series:
        """
        OB - Order Blocks
        This method detects order blocks when there is a high amount of market orders exist on a price range.

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        close_mitigation: bool - if True then the order block will be mitigated based on the close of the candle otherwise it will be the high/low.

        returns:
        OB = 1 if bullish order block, -1 if bearish order block
        Top = top of the order block
        Bottom = bottom of the order block
        OBVolume = volume + 2 last volumes amounts
        Percentage = strength of order block (min(highVolume, lowVolume)/max(highVolume, lowVolume))
        """

        ohlc_len = len(ohlc)
        _open = ohlc["open"].values
        _high = ohlc["high"].values
        _low = ohlc["low"].values
        _close = ohlc["close"].values
        _volume = ohlc["volume"].values
        swing_hl = swing_highs_lows["HighLow"].values
        swing_lv = swing_highs_lows["Level"].values

        # Pre-allocate arrays
        crossed = np.full(ohlc_len, False, dtype=bool)
        ob = np.zeros(ohlc_len, dtype=np.int32)
        top_arr = np.zeros(ohlc_len, dtype=np.float32)
        bottom_arr = np.zeros(ohlc_len, dtype=np.float32)
        obVolume = np.zeros(ohlc_len, dtype=np.float32)
        lowVolume = np.zeros(ohlc_len, dtype=np.float32)
        highVolume = np.zeros(ohlc_len, dtype=np.float32)
        percentage = np.zeros(ohlc_len, dtype=np.float32)
        mitigated_index = np.zeros(ohlc_len, dtype=np.int32)
        breaker = np.full(ohlc_len, False, dtype=bool)

        # Precompute swing indices (assumed sorted)
        swing_high_indices = np.flatnonzero(swing_hl == 1)
        swing_low_indices = np.flatnonzero(swing_hl == -1)

        # Single pass: detect both bullish and bearish OBs together
        active_bullish = []
        active_bearish = []
        # Cache last searchsorted positions to avoid redundant binary searches
        last_bull_pos = 0
        last_bear_pos = 0
        n_swing_hi = len(swing_high_indices)
        n_swing_lo = len(swing_low_indices)

        for i in range(ohlc_len):
            hi = _high[i]
            lo = _low[i]
            cl = _close[i]
            op = _open[i]

            # --- Update active bullish OBs ---
            if active_bullish:
                new_bull = []
                for idx in active_bullish:
                    if breaker[idx]:
                        if hi > top_arr[idx]:
                            ob[idx] = 0
                            top_arr[idx] = 0.0
                            bottom_arr[idx] = 0.0
                            obVolume[idx] = 0.0
                            lowVolume[idx] = 0.0
                            highVolume[idx] = 0.0
                            mitigated_index[idx] = 0
                            percentage[idx] = 0.0
                        else:
                            new_bull.append(idx)
                    else:
                        if ((not close_mitigation and lo < bottom_arr[idx])
                            or (close_mitigation and min(op, cl) < bottom_arr[idx])):
                            breaker[idx] = True
                            mitigated_index[idx] = i - 1
                        new_bull.append(idx)
                active_bullish = new_bull

            # --- Update active bearish OBs ---
            if active_bearish:
                new_bear = []
                for idx in active_bearish:
                    if breaker[idx]:
                        if lo < bottom_arr[idx]:
                            ob[idx] = 0
                            top_arr[idx] = 0.0
                            bottom_arr[idx] = 0.0
                            obVolume[idx] = 0.0
                            lowVolume[idx] = 0.0
                            highVolume[idx] = 0.0
                            mitigated_index[idx] = 0
                            percentage[idx] = 0.0
                        else:
                            new_bear.append(idx)
                    else:
                        if ((not close_mitigation and hi > top_arr[idx])
                            or (close_mitigation and max(op, cl) > top_arr[idx])):
                            breaker[idx] = True
                            mitigated_index[idx] = i
                        new_bear.append(idx)
                active_bearish = new_bear

            # --- Detect new bullish OB (swing high crossed) ---
            # Advance cached position
            while last_bull_pos < n_swing_hi and swing_high_indices[last_bull_pos] < i:
                last_bull_pos += 1
            last_top_index = swing_high_indices[last_bull_pos - 1] if last_bull_pos > 0 else None

            if last_top_index is not None:
                swing_high_price = swing_lv[last_top_index]
                if cl > swing_high_price and not crossed[last_top_index]:
                    crossed[last_top_index] = True
                    default_index = i - 1
                    obBtm = _high[default_index]
                    obTop = _low[default_index]
                    obIndex = default_index
                    if i - last_top_index > 1:
                        start = last_top_index + 1
                        end = i
                        if end > start:
                            segment = _low[start:end]
                            min_val = segment.min()
                            candidates = np.nonzero(segment == min_val)[0]
                            if candidates.size:
                                candidate_index = start + candidates[-1]
                                obBtm = _low[candidate_index]
                                obTop = _high[candidate_index]
                                obIndex = candidate_index
                    ob[obIndex] = 1
                    top_arr[obIndex] = obTop
                    bottom_arr[obIndex] = obBtm
                    vol_cur = _volume[i]
                    vol_prev1 = _volume[i - 1] if i >= 1 else 0.0
                    vol_prev2 = _volume[i - 2] if i >= 2 else 0.0
                    obVolume[obIndex] = vol_cur + vol_prev1 + vol_prev2
                    lowVolume[obIndex] = vol_prev2
                    highVolume[obIndex] = vol_cur + vol_prev1
                    max_vol = max(highVolume[obIndex], lowVolume[obIndex])
                    percentage[obIndex] = (min(highVolume[obIndex], lowVolume[obIndex]) / max_vol * 100.0) if max_vol != 0 else 100.0
                    active_bullish.append(obIndex)

            # --- Detect new bearish OB (swing low crossed) ---
            while last_bear_pos < n_swing_lo and swing_low_indices[last_bear_pos] < i:
                last_bear_pos += 1
            last_btm_index = swing_low_indices[last_bear_pos - 1] if last_bear_pos > 0 else None

            if last_btm_index is not None:
                swing_low_price = swing_lv[last_btm_index]
                if cl < swing_low_price and not crossed[last_btm_index]:
                    crossed[last_btm_index] = True
                    default_index = i - 1
                    obTop = _high[default_index]
                    obBtm = _low[default_index]
                    obIndex = default_index
                    if i - last_btm_index > 1:
                        start = last_btm_index + 1
                        end = i
                        if end > start:
                            segment = _high[start:end]
                            max_val = segment.max()
                            candidates = np.nonzero(segment == max_val)[0]
                            if candidates.size:
                                candidate_index = start + candidates[-1]
                                obTop = _high[candidate_index]
                                obBtm = _low[candidate_index]
                                obIndex = candidate_index
                    ob[obIndex] = -1
                    top_arr[obIndex] = obTop
                    bottom_arr[obIndex] = obBtm
                    vol_cur = _volume[i]
                    vol_prev1 = _volume[i - 1] if i >= 1 else 0.0
                    vol_prev2 = _volume[i - 2] if i >= 2 else 0.0
                    obVolume[obIndex] = vol_cur + vol_prev1 + vol_prev2
                    lowVolume[obIndex] = vol_cur + vol_prev1
                    highVolume[obIndex] = vol_prev2
                    max_vol = max(highVolume[obIndex], lowVolume[obIndex])
                    percentage[obIndex] = (min(highVolume[obIndex], lowVolume[obIndex]) / max_vol * 100.0) if max_vol != 0 else 100.0
                    active_bearish.append(obIndex)

        # Convert zeros to NaN where OB was not set
        ob = np.where(ob != 0, ob, np.nan)
        top_arr = np.where(~np.isnan(ob), top_arr, np.nan)
        bottom_arr = np.where(~np.isnan(ob), bottom_arr, np.nan)
        obVolume = np.where(~np.isnan(ob), obVolume, np.nan)
        mitigated_index = np.where(~np.isnan(ob), mitigated_index, np.nan)
        percentage = np.where(~np.isnan(ob), percentage, np.nan)

        ob_series = pd.Series(ob, name="OB")
        top_series = pd.Series(top_arr, name="Top")
        bottom_series = pd.Series(bottom_arr, name="Bottom")
        obVolume_series = pd.Series(obVolume, name="OBVolume")
        mitigated_index_series = pd.Series(mitigated_index, name="MitigatedIndex")
        percentage_series = pd.Series(percentage, name="Percentage")

        return pd.concat(
            [
                ob_series,
                top_series,
                bottom_series,
                obVolume_series,
                mitigated_index_series,
                percentage_series,
            ],
            axis=1,
        )

    @classmethod
    def liquidity(cls, ohlc: DataFrame, swing_highs_lows: DataFrame, range_percent: float = 0.01) -> Series:
        """
        Liquidity
        Liquidity is when there are multiple highs within a small range of each other,
        or multiple lows within a small range of each other.

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        range_percent: float - the percentage of the range to determine liquidity

        returns:
        Liquidity = 1 if bullish liquidity, -1 if bearish liquidity
        Level = the level of the liquidity
        End = the index of the last liquidity level
        Swept = the index of the candle that swept the liquidity
        """

        # Work on a copy so the original is not modified.
        shl = swing_highs_lows.copy()
        n = len(ohlc)
        
        # Calculate the pip range based on the overall high-low range.
        pip_range = (ohlc["high"].max() - ohlc["low"].min()) * range_percent

        # Preconvert required columns to numpy arrays.
        ohlc_high = ohlc["high"].values
        ohlc_low = ohlc["low"].values
        # Make a copy to allow in-place marking of used candidates.
        shl_HL = shl["HighLow"].values.copy()
        shl_Level = shl["Level"].values.copy()

        # Initialise output arrays with NaN (to match later replacement of zeros).
        liquidity = np.full(n, np.nan, dtype=np.float32)
        liquidity_level = np.full(n, np.nan, dtype=np.float32)
        liquidity_end = np.full(n, np.nan, dtype=np.float32)
        liquidity_swept = np.full(n, np.nan, dtype=np.float32)

        # Process bullish liquidity (HighLow == 1)
        bull_indices = np.nonzero(shl_HL == 1)[0]
        n_bull = len(bull_indices)
        for bi in range(n_bull):
            i = bull_indices[bi]
            # Skip if this candidate has already been used.
            if shl_HL[i] != 1:
                continue
            high_level = shl_Level[i]
            range_low = high_level - pip_range
            range_high = high_level + pip_range
            group_levels = [high_level]
            group_end = i

            # Determine the swept index:
            c_start = i + 1
            if c_start < n:
                remaining = ohlc_high[c_start:]
                hits = np.where(remaining >= range_high)[0]
                swept = (c_start + hits[0]) if len(hits) > 0 else 0
            else:
                swept = 0

            # Only scan candidates after i (start from bi+1 in the index array)
            for bj in range(bi + 1, n_bull):
                j = bull_indices[bj]
                if swept and j >= swept:
                    break
                if shl_HL[j] == 1 and (range_low <= shl_Level[j] <= range_high):
                    group_levels.append(shl_Level[j])
                    group_end = j
                    shl_HL[j] = 0  # mark candidate as used
            if len(group_levels) > 1:
                avg_level = sum(group_levels) / len(group_levels)
                liquidity[i] = 1
                liquidity_level[i] = avg_level
                liquidity_end[i] = group_end
                liquidity_swept[i] = swept

        # Process bearish liquidity (HighLow == -1)
        bear_indices = np.nonzero(shl_HL == -1)[0]
        n_bear = len(bear_indices)
        for bi in range(n_bear):
            i = bear_indices[bi]
            if shl_HL[i] != -1:
                continue
            low_level = shl_Level[i]
            range_low = low_level - pip_range
            range_high = low_level + pip_range
            group_levels = [low_level]
            group_end = i

            c_start = i + 1
            if c_start < n:
                remaining = ohlc_low[c_start:]
                hits = np.where(remaining <= range_low)[0]
                swept = (c_start + hits[0]) if len(hits) > 0 else 0
            else:
                swept = 0

            for bj in range(bi + 1, n_bear):
                j = bear_indices[bj]
                if swept and j >= swept:
                    break
                if shl_HL[j] == -1 and (range_low <= shl_Level[j] <= range_high):
                    group_levels.append(shl_Level[j])
                    group_end = j
                    shl_HL[j] = 0
            if len(group_levels) > 1:
                avg_level = sum(group_levels) / len(group_levels)
                liquidity[i] = -1
                liquidity_level[i] = avg_level
                liquidity_end[i] = group_end
                liquidity_swept[i] = swept

        # Convert arrays to Series with the proper names.
        liq_series = pd.Series(liquidity, name="Liquidity")
        level_series = pd.Series(liquidity_level, name="Level")
        end_series = pd.Series(liquidity_end, name="End")
        swept_series = pd.Series(liquidity_swept, name="Swept")

        return pd.concat([liq_series, level_series, end_series, swept_series], axis=1)

    @classmethod
    def previous_high_low(cls, ohlc: DataFrame, time_frame: str = "1D") -> DataFrame:
        """
        Previous High Low
        This method returns the previous high and low of the given time frame.

        parameters:
        time_frame: str - the time frame to get the previous high and low 15m, 1H, 4H, 1D, 1W, 1M

        returns:
        PreviousHigh = the previous high
        PreviousLow = the previous low
        BrokenHigh = 1 once price has broken the previous high of the timeframe, 0 otherwise
        BrokenLow = 1 once price has broken the previous low of the timeframe, 0 otherwise
        """
        ohlc = ohlc.copy()
        ohlc.index = pd.to_datetime(ohlc.index)
        n = len(ohlc)

        # Resample to target timeframe
        resampled = ohlc.resample(time_frame).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()

        # Edge case: not enough resampled periods
        if len(resampled) < 2:
            return pd.concat([
                pd.Series(np.full(n, np.nan, dtype=np.float32), name="PreviousHigh"),
                pd.Series(np.full(n, np.nan, dtype=np.float32), name="PreviousLow"),
                pd.Series(np.zeros(n, dtype=np.int32), name="BrokenHigh"),
                pd.Series(np.zeros(n, dtype=np.int32), name="BrokenLow"),
            ], axis=1)

        resampled_times = resampled.index.values
        resampled_highs = resampled["high"].values
        resampled_lows = resampled["low"].values
        candle_times = ohlc.index.values

        # For each candle, find how many resampled periods have start time < candle time
        # This is equivalent to: len(np.where(resampled_times < candle_time)[0])
        periods_before = np.searchsorted(resampled_times, candle_times, side='left')

        # Original takes second-to-last: indices[-2] = periods_before - 2
        prev_period_idx = periods_before - 2

        # Valid only if more than 1 period before (original: len > 1, i.e., >= 2 periods)
        valid_mask = periods_before > 1

        # Initialize output arrays
        previous_high = np.full(n, np.nan, dtype=np.float32)
        previous_low = np.full(n, np.nan, dtype=np.float32)

        # Fill valid entries
        valid_indices = np.where(valid_mask)[0]
        if len(valid_indices) > 0:
            lookup_indices = prev_period_idx[valid_indices]
            previous_high[valid_indices] = resampled_highs[lookup_indices]
            previous_low[valid_indices] = resampled_lows[lookup_indices]

        # Group candles by their reference period for cumulative broken tracking
        # Original resets broken flags when the reference period changes
        group_changes = np.concatenate([[True], prev_period_idx[1:] != prev_period_idx[:-1]])
        group_id = np.cumsum(group_changes)

        ohlc_high = ohlc["high"].values
        ohlc_low = ohlc["low"].values

        # Compute cumulative max/min within each group
        df_temp = pd.DataFrame({
            'group': group_id,
            'high': ohlc_high,
            'low': ohlc_low,
        })

        cummax_high = df_temp.groupby('group')['high'].cummax().values
        cummin_low = df_temp.groupby('group')['low'].cummin().values

        # Broken = 1 if cumulative high > previous_high (or cummin < previous_low)
        broken_high = np.where(valid_mask & (cummax_high > previous_high), 1, 0).astype(np.int32)
        broken_low = np.where(valid_mask & (cummin_low < previous_low), 1, 0).astype(np.int32)

        return pd.concat([
            pd.Series(previous_high, name="PreviousHigh"),
            pd.Series(previous_low, name="PreviousLow"),
            pd.Series(broken_high, name="BrokenHigh"),
            pd.Series(broken_low, name="BrokenLow"),
        ], axis=1)
    
    @classmethod
    def sessions(
        cls,
        ohlc: DataFrame,
        session: str,
        start_time: str = "",
        end_time: str = "",
        time_zone: str = "UTC",
    ) -> Series:
        """
        Sessions
        This method returns wwhich candles are within the session specified

        parameters:
        session: str - the session you want to check (Sydney, Tokyo, London, New York, Asian kill zone, London open kill zone, New York kill zone, london close kill zone, Custom)
        start_time: str - the start time of the session in the format "HH:MM" only required for custom session.
        end_time: str - the end time of the session in the format "HH:MM" only required for custom session.
        time_zone: str - the time zone of the candles can be in the format "UTC+0" or "GMT+0"

        returns:
        Active = 1 if the candle is within the session, 0 if not
        High = the highest point of the session
        Low = the lowest point of the session
        """

        if session == "Custom" and (start_time == "" or end_time == ""):
            raise ValueError("Custom session requires a start and end time")

        default_sessions = {
            "Sydney": {
                "start": "21:00",
                "end": "06:00",
            },
            "Tokyo": {
                "start": "00:00",
                "end": "09:00",
            },
            "London": {
                "start": "07:00",
                "end": "16:00",
            },
            "New York": {
                "start": "13:00",
                "end": "22:00",
            },
            "Asian kill zone": {
                "start": "00:00",
                "end": "04:00",
            },
            "London open kill zone": {
                "start": "6:00",
                "end": "9:00",
            },
            "New York kill zone": {
                "start": "11:00",
                "end": "14:00",
            },
            "london close kill zone": {
                "start": "14:00",
                "end": "16:00",
            },
            "Custom": {
                "start": start_time,
                "end": end_time,
            },
        }

        ohlc.index = pd.to_datetime(ohlc.index)
        if time_zone != "UTC":
            time_zone = time_zone.replace("GMT", "Etc/GMT")
            time_zone = time_zone.replace("UTC", "Etc/GMT")
            ohlc.index = ohlc.index.tz_localize(time_zone).tz_convert("UTC")

        start_str = default_sessions[session]["start"]
        end_str = default_sessions[session]["end"]
        start_parts = start_str.split(":")
        end_parts = end_str.split(":")
        start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
        end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])

        # Vectorized time-of-day in minutes
        minutes_of_day = ohlc.index.hour * 60 + ohlc.index.minute

        # Vectorized active mask (handles wrap-around sessions like Sydney 21:00-06:00)
        if start_minutes < end_minutes:
            active_mask = (minutes_of_day >= start_minutes) & (minutes_of_day <= end_minutes)
        else:
            active_mask = (minutes_of_day >= start_minutes) | (minutes_of_day <= end_minutes)

        active = np.where(active_mask, 1, 0).astype(np.int32)

        # Compute cumulative session high/low (reset when session becomes inactive)
        ohlc_high = ohlc["high"].values
        ohlc_low = ohlc["low"].values
        n_bars = len(ohlc)
        high = np.zeros(n_bars, dtype=np.float32)
        low = np.zeros(n_bars, dtype=np.float32)

        # Vectorized: group contiguous active runs, cummax/cummin within each
        active_mask_bool = active == 1
        if active_mask_bool.any():
            transitions = np.diff(active, prepend=0)
            group_ids = np.cumsum((transitions == 1).astype(np.int32))
            group_ids[~active_mask_bool] = -1
            tmp = pd.DataFrame({"group": group_ids, "high": ohlc_high, "low": ohlc_low})
            active_df = tmp[active_mask_bool]
            high[active_mask_bool] = active_df.groupby("group")["high"].cummax().values.astype(np.float32)
            low[active_mask_bool] = active_df.groupby("group")["low"].cummin().values.astype(np.float32)

        active = pd.Series(active, name="Active")
        high = pd.Series(high, name="High")
        low = pd.Series(low, name="Low")

        return pd.concat([active, high, low], axis=1)

    @classmethod
    def retracements(cls, ohlc: DataFrame, swing_highs_lows: DataFrame) -> Series:
        """
        Retracement
        This method returns the percentage of a retracement from the swing high or low

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function

        returns:
        Direction = 1 if bullish retracement, -1 if bearish retracement
        CurrentRetracement% = the current retracement percentage from the swing high or low
        DeepestRetracement% = the deepest retracement percentage from the swing high or low
        """

        swing_highs_lows = swing_highs_lows.copy()

        n = len(ohlc)
        shl_hl = swing_highs_lows["HighLow"].values
        shl_lv = swing_highs_lows["Level"].values
        ohlc_low = ohlc["low"].values
        ohlc_high = ohlc["high"].values

        direction = np.zeros(n, dtype=np.int32)
        current_retracement = np.zeros(n, dtype=np.float64)
        deepest_retracement = np.zeros(n, dtype=np.float64)

        # Precompute swing indices to skip NaN checks on non-swing bars
        swing_indices = np.flatnonzero(~np.isnan(shl_hl))
        swing_map = {}  # bar_index -> (hl_value, level_value)
        for si in swing_indices:
            swing_map[si] = (shl_hl[si], shl_lv[si])

        top = 0.0
        bottom = 0.0
        prev_dir = 0
        prev_deepest = 0.0
        for i in range(n):
            if i in swing_map:
                hl_val, lv_val = swing_map[i]
                if hl_val == 1:
                    direction[i] = 1
                    top = lv_val
                else:
                    direction[i] = -1
                    bottom = lv_val
            else:
                direction[i] = prev_dir

            if prev_dir == 1:
                divisor = top - bottom
                if divisor != 0:
                    current_retracement[i] = 100 - (((ohlc_low[i] - bottom) / divisor) * 100)
                deepest_retracement[i] = max(prev_deepest, current_retracement[i])
            if direction[i] == -1:
                divisor = bottom - top
                if divisor != 0:
                    current_retracement[i] = 100 - ((ohlc_high[i] - top) / divisor) * 100
                deepest_retracement[i] = max(
                    prev_deepest if prev_dir == -1 else 0,
                    current_retracement[i],
                )

            prev_dir = direction[i]
            prev_deepest = deepest_retracement[i]

        # Vectorized round (much faster than per-bar round())
        current_retracement = np.round(current_retracement, 1)
        deepest_retracement = np.round(deepest_retracement, 1)
        # Ensure deepest >= current after rounding (rounding can flip the relationship)
        deepest_retracement = np.maximum(deepest_retracement, current_retracement)

        # shift the arrays by 1
        current_retracement = np.roll(current_retracement, 1)
        deepest_retracement = np.roll(deepest_retracement, 1)
        direction = np.roll(direction, 1)

        # remove the first 3 retracements as they get calculated incorrectly due to not enough data
        remove_first_count = 0
        for i in range(n):
            if i + 1 == n:
                break
            if direction[i] != direction[i + 1]:
                remove_first_count += 1
            direction[i] = 0
            current_retracement[i] = 0
            deepest_retracement[i] = 0
            if remove_first_count == 3:
                direction[i + 1] = 0
                current_retracement[i + 1] = 0
                deepest_retracement[i + 1] = 0
                break

        direction = pd.Series(direction, name="Direction")
        current_retracement = pd.Series(current_retracement, name="CurrentRetracement%")
        deepest_retracement = pd.Series(deepest_retracement, name="DeepestRetracement%")

        return pd.concat([direction, current_retracement, deepest_retracement], axis=1)
