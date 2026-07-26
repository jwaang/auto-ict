"""The day-trade cutoff must hold on days the market closes early.

Two faults measured in experiment 27, neither of which had a test. The engine
closed on any bar whose ET hour was 16, so on a holiday or half-day with no such
bar the position rode into later sessions — 24 trades, longest 119 hours,
carrying nearly all of the run's gross profit. And nothing stopped an entry
being taken during that same hour, so 31 positions opened at the cutoff and 19
were liquidated on the very next bar.
"""
import pandas as pd
import pytest

from backtest.engine import session_cutoff_masks

ET = "America/New_York"


def bars(times: list[str]) -> pd.Series:
    """ET wall-clock strings to the UTC series the engine works in."""
    return pd.Series(pd.DatetimeIndex(times).tz_localize(ET).tz_convert("UTC"))


class TestOrdinaryWeekday:
    def test_closes_on_the_1600_bar_not_an_hour_late(self):
        """The 17:00 bar is the last of the session, but the cutoff is 16:00.

        Anchoring the close on the session-day rollover would pick 17:00, since
        the next bar after it is the 18:00 evening open belonging to the next
        session day. That is an hour past the documented day-trade cutoff.
        """
        ts = bars(["2024-03-05 15:30", "2024-03-05 15:45", "2024-03-05 16:00",
                   "2024-03-05 16:15", "2024-03-05 17:00", "2024-03-05 18:15"])
        after, close = session_cutoff_masks(ts)
        # The last bar of any series always closes — see the terminal-bar test
        # below — so the interesting run is everything before it.
        assert list(close[:-1]) == [False, False, True, False, False]
        assert list(after) == [False, False, True, True, True, False]

    def test_evening_bars_belong_to_the_next_session(self):
        """18:00 ET Monday opens Tuesday's session, so it is not past a cutoff."""
        ts = bars(["2024-03-04 18:15", "2024-03-04 20:00", "2024-03-05 09:30"])
        after, close = session_cutoff_masks(ts)
        assert not after.any()
        assert not close[:-1].any()


class TestHolidayAndHalfDay:
    def test_half_day_closes_on_its_last_bar(self):
        """No 16:00 bar exists on the Friday after Thanksgiving.

        The session ends 13:15 ET. Before the fix the position was carried until
        some later session happened to produce a bar in the 16:00 hour.
        """
        ts = bars(["2024-11-29 12:45", "2024-11-29 13:00", "2024-11-29 13:15",
                   "2024-12-01 18:15", "2024-12-02 09:30"])
        after, close = session_cutoff_masks(ts)
        assert list(close[:-1]) == [False, False, True, False]
        assert not after[:3].any(), "a half-day's bars are all before 16:00"

    def test_full_holiday_does_not_carry_into_the_next_session(self):
        """Independence Day 2023: the 119-hour hold in the baseline."""
        ts = bars(["2023-06-30 15:45", "2023-06-30 16:00", "2023-07-02 18:15",
                   "2023-07-03 12:00", "2023-07-05 09:30", "2023-07-05 16:00"])
        _, close = session_cutoff_masks(ts)
        assert close[1], "closes at Friday's cutoff"
        assert close[3], "closes on the last bar of the shortened 3 July session"
        assert close[5]

    def test_the_final_bar_always_closes(self):
        """Nothing may be left open when the data runs out."""
        ts = bars(["2024-03-05 09:30", "2024-03-05 10:00"])
        _, close = session_cutoff_masks(ts)
        assert list(close) == [False, True]


class TestDaylightSaving:
    """The cutoff follows ET wall-clock, so it must survive both transitions.

    `session_day` does its arithmetic on naive ET precisely because absolute-time
    arithmetic drags Sunday-evening bars onto Saturday at every spring-forward.
    The cutoff is built on top of it and inherits that requirement.
    """

    def test_spring_forward(self):
        ts = bars(["2024-03-08 16:00", "2024-03-10 18:15", "2024-03-11 09:30",
                   "2024-03-11 16:00", "2024-03-11 16:15"])
        after, close = session_cutoff_masks(ts)
        assert list(close) == [True, False, False, True, False]
        assert list(after) == [True, False, False, True, True]

    def test_fall_back(self):
        ts = bars(["2024-11-01 16:00", "2024-11-03 18:15", "2024-11-04 09:30",
                   "2024-11-04 16:00"])
        after, close = session_cutoff_masks(ts)
        assert list(close) == [True, False, False, True]
        assert list(after) == [True, False, False, True]

    def test_consecutive_closures(self):
        """Christmas Eve is a half day and Christmas Day is shut."""
        ts = bars(["2024-12-24 12:00", "2024-12-24 13:00",
                   "2024-12-26 09:30", "2024-12-26 16:00"])
        after, close = session_cutoff_masks(ts)
        assert list(close) == [False, True, False, True]
        assert not after[:3].any()


class TestEntryGuard:
    @pytest.mark.parametrize("minute", ["00", "15", "30", "45"])
    def test_no_entry_anywhere_in_the_cutoff_hour(self, minute):
        """All four 15-minute bars of the 16:00 hour were used in the baseline."""
        ts = bars([f"2024-03-05 16:{minute}"])
        after, _ = session_cutoff_masks(ts)
        assert after[0]

    def test_entries_are_allowed_right_up_to_the_cutoff(self):
        ts = bars(["2024-03-05 15:45"])
        after, _ = session_cutoff_masks(ts)
        assert not after[0]
