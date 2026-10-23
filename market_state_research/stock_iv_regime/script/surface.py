"""A session's levels at 14 and 30 days to expiry from its own chain.

At one expiry, the implied volatility at a target delta is read from the usable contracts
of one type (``volatility`` above 0, ``delta`` given, ``ask`` above 0), ordered from in
the money to out of the money (calls by rising strike, puts by falling strike): it is the
IV of the first contract whose delta equals the target, or else the IV interpolated
linearly in delta between the first adjacent pair whose deltas lie on either side of it.
Nothing is extrapolated: without such a contract or pair there is no reading.

- A horizon's levels are the IVs, in percent, at its target deltas (``REQUIRED``): at
  ``HORIZON`` (14 days) the call at +0.25 and +0.50 and the put at -0.25 and -0.50; at
  ``TERM_HORIZON`` (30 days) the call at +0.50 and the put at -0.50.
- They are read at two bracket expiries that give every reading of the horizon: E1, the
  last such expiry 1 to H calendar days out, and E2, the first such expiry H or more days
  out (within ``chain.WINDOW_DAYS``). An expiry nearer to H that lacks a reading (a stray
  listing of one strike, a side without usable quotes) is passed over and named, with why
  (``skipped``). An expiry exactly H days out gives its own levels (``exact``); otherwise
  each level is interpolated linearly in calendar days between E1's and E2's
  (``interpolated``). A session without E1 or E2 has no level at H (``none``), with the
  reason; a session with both has every level of H.
- At one expiry, for the readings a report shows, the 25Δ skew is the put IV at -0.25
  minus the call IV at +0.25, in percentage points, and the ATM IV the mean of the call IV
  at +0.50 and the put IV at -0.50, in percent. The indicators of a session are computed
  from its rounded levels (``indicators``), never from these.

Every level is computed exactly with fractions and rounded half-even once, to ``PLACES``
decimal places; zero is written without a sign. Every function here is pure.
"""

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Final, Literal

from .api import Record
from .chain import WINDOW_DAYS

HORIZON: Final = 14  # calendar days: the skew, the 25Δ IVs and the nearer ATM IV
TERM_HORIZON: Final = 30  # calendar days: the farther ATM IV of the term structure
HORIZONS: Final = (HORIZON, TERM_HORIZON)
PLACES: Final = 2
Method = Literal["exact", "interpolated", "none"]
Right = Literal["call", "put"]
Target = Literal["call25", "put25", "call50", "put50"]
TARGETS: Final[Mapping[Target, tuple[Right, Fraction]]] = {
    "call25": ("call", Fraction(1, 4)),
    "put25": ("put", Fraction(-1, 4)),
    "call50": ("call", Fraction(1, 2)),
    "put50": ("put", Fraction(-1, 2)),
}
# The levels of each horizon, which its bracket expiries must give.
REQUIRED: Final[Mapping[int, tuple[Target, ...]]] = {
    HORIZON: ("call25", "put25", "call50", "put50"),
    TERM_HORIZON: ("call50", "put50"),
}
_READINGS: Final[Mapping[int, str]] = {HORIZON: "all four readings", TERM_HORIZON: "both 50Δ readings"}
_HUNDRED: Final = Fraction(100)


def rounded(value: Fraction, places: int = PLACES) -> Decimal:
    """``value`` rounded half-even to ``places`` decimal places, exactly; zero without a sign."""
    exact = round(value, places)  # Fraction rounding is half-even and exact
    result = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(Decimal(1).scaleb(-places))
    return result.copy_abs() if result.is_zero() else result


def difference(current: Decimal, previous: Decimal) -> Decimal:
    """``current - previous``, exact: Decimal keeps the finer exponent; zero is written without a sign."""
    value = current - previous
    return value.copy_abs() if value.is_zero() else value


def _delta_text(target: Fraction) -> str:
    return f"{'+' if target > 0 else '-'}{rounded(abs(target))}"


def usable(row: Record) -> bool:
    """Whether a contract's quote can be read: an IV above 0, a delta and an ask above 0."""
    values = row.attributes
    volatility, delta, ask = values["volatility"], values["delta"], values["ask"]
    return (
        volatility is not None
        and Decimal(volatility) > 0
        and delta is not None
        and ask is not None
        and Decimal(ask) > 0
    )


@dataclass(frozen=True)
class Point:
    """The IV at one target delta of one expiry, the strikes it was read at, or why there is none."""

    iv: Fraction | None
    strikes: tuple[Decimal, ...] = ()
    reason: str | None = None

    def describe(self) -> str:
        """The strikes as a report names them, ascending: ``155`` (exact) or ``155–160``."""
        return "–".join(format(strike, "f") for strike in sorted(self.strikes))


def iv_at(rows: Sequence[Record], right: Right, target: Fraction) -> Point:
    """The IV at ``target`` delta among ``rows`` of type ``right`` (see the module docstring)."""
    chosen = sorted((row for row in rows if row.right == right and usable(row)), key=lambda row: row.strike)
    if right == "put":
        chosen.reverse()  # in the money first: puts by falling strike
    if not chosen:
        return Point(None, (), f"no usable {right}")
    readings = [
        (
            Fraction(Decimal(str(row.attributes["delta"]))),
            Fraction(Decimal(str(row.attributes["volatility"]))),
            row.strike,
        )
        for row in chosen
    ]
    for index, (delta, iv, strike) in enumerate(readings):
        if delta == target:
            return Point(iv, (strike,))
        if index + 1 < len(readings):
            next_delta, next_iv, next_strike = readings[index + 1]
            if (delta - target) * (next_delta - target) < 0:
                weight = (target - delta) / (next_delta - delta)
                return Point(iv + (next_iv - iv) * weight, (strike, next_strike))
    return Point(
        None, (), f"no usable {right} has delta {_delta_text(target)} and no two adjacent ones bracket it"
    )


@dataclass(frozen=True)
class ExpiryReading:
    """The four IV points of one expiry and the values they give there, for the readings a
    report shows."""

    expiry: dt.date
    days: int
    points: Mapping[Target, Point]

    @property
    def skew(self) -> Fraction | None:
        """Put IV at -0.25 minus call IV at +0.25, in percentage points."""
        put, call = self.points["put25"].iv, self.points["call25"].iv
        return None if put is None or call is None else (put - call) * _HUNDRED

    @property
    def atm(self) -> Fraction | None:
        """The mean of the call IV at +0.50 and the put IV at -0.50, in percent."""
        call, put = self.points["call50"].iv, self.points["put50"].iv
        return None if call is None or put is None else (call + put) / 2 * _HUNDRED

    def gives(self, targets: Sequence[Target]) -> bool:
        """Whether each of ``targets`` has a reading, so that the expiry can be a bracket."""
        return all(self.points[target].iv is not None for target in targets)

    def missing(self, targets: Sequence[Target] = tuple(TARGETS)) -> str:
        """Why ``targets`` (default: every target) have no reading at this expiry."""
        reasons = [
            f"{target[:-2]} {_delta_text(TARGETS[target][1])}: {self.points[target].reason}"
            for target in targets
            if self.points[target].iv is None
        ]
        return f"at {self.expiry.isoformat()} ({self.days}d) " + "; ".join(reasons)

    def label(self) -> str:
        return f"{self.expiry.isoformat()} ({self.days}d)"


def read_expiry(rows: Sequence[Record], expiry: dt.date, session: dt.date) -> ExpiryReading:
    """The four points of ``expiry`` from its ``rows``."""
    mine = [row for row in rows if row.expiry == expiry]
    points = {target: iv_at(mine, right, delta) for target, (right, delta) in TARGETS.items()}
    return ExpiryReading(expiry, (expiry - session).days, points)


def _candidates(
    expiries: Sequence[dt.date], session: dt.date, horizon: int
) -> tuple[tuple[dt.date, ...], tuple[dt.date, ...]]:
    """The expiries E1 is sought among, 1 to ``horizon`` days out and latest first, and those E2
    is sought among, ``horizon`` or more days out and earliest first.

    An expiry exactly ``horizon`` days out is in both. The session's own expiry (0 days out)
    is in neither.
    """
    days = {expiry: (expiry - session).days for expiry in expiries}
    lower = sorted((expiry for expiry, dte in days.items() if 1 <= dte <= horizon), reverse=True)
    upper = sorted(expiry for expiry, dte in days.items() if dte >= horizon)
    return tuple(lower), tuple(upper)


def _search(
    candidates: Sequence[dt.date], read: Callable[[dt.date], ExpiryReading], targets: Sequence[Target]
) -> tuple[ExpiryReading | None, tuple[ExpiryReading, ...]]:
    """The first of ``candidates`` whose reading gives ``targets``, or None, and the readings
    passed over before it."""
    passed: list[ExpiryReading] = []
    for expiry in candidates:
        reading = read(expiry)
        if reading.gives(targets):
            return reading, tuple(passed)
        passed.append(reading)
    return None, tuple(passed)


def interpolate(
    lower: Fraction, lower_days: int, upper: Fraction, upper_days: int, horizon: int = HORIZON
) -> Fraction:
    """The value at ``horizon`` days, linear in calendar days between two expiries' values; exact."""
    if not lower_days < horizon < upper_days:
        raise ValueError(f"interpolate: the expiries must lie on either side of {horizon} days")
    return lower + (upper - lower) * Fraction(horizon - lower_days, upper_days - lower_days)


@dataclass(frozen=True)
class Value:
    """One value: rounded, or None and why."""

    value: Decimal | None
    reason: str | None = None


@dataclass(frozen=True)
class Surface:
    """A session's brackets at one horizon, their readings and its levels there: the IVs at the
    horizon's target deltas (``REQUIRED``), in percent.

    ``readings`` holds E1's reading, then E2's when it differs (one reading for ``exact``,
    none for ``none``). ``skipped`` holds the readings of the expiries passed over because
    they lack a reading, ascending. ``reason`` says why there is no bracket.
    """

    session: dt.date
    horizon: int
    method: Method
    readings: tuple[ExpiryReading, ...]
    levels: Mapping[Target, Value]
    skipped: tuple[ExpiryReading, ...] = ()
    reason: str | None = None

    @property
    def targets(self) -> tuple[Target, ...]:
        """The targets whose levels the horizon gives."""
        return REQUIRED[self.horizon]

    def level(self, target: Target) -> Value:
        """The level at ``target``: rounded, or None and why."""
        return self.levels[target]

    @property
    def expiries(self) -> tuple[dt.date, ...]:
        """The bracket expiries."""
        return tuple(reading.expiry for reading in self.readings)

    @property
    def read(self) -> tuple[dt.date, ...]:
        """Every expiry whose rows the levels rest on: the brackets and the expiries skipped."""
        return tuple(sorted({*self.expiries, *(reading.expiry for reading in self.skipped)}))

    def detail(self) -> str:
        """One line for people: the horizon and the method with its expiries and those skipped, or
        why there is no level."""
        if self.method == "none":
            return f"{self.horizon}-DTE: none · {self.reason}"
        line = f"{self.horizon}-DTE: {self.method} · " + " → ".join(
            reading.label() for reading in self.readings
        )
        if self.skipped:
            line += " · skipped " + ", ".join(reading.label() for reading in self.skipped)
        return line


def _level(readings: Sequence[ExpiryReading], target: Target, horizon: int) -> Value:
    """The level at ``target`` and ``horizon`` days from the bracket readings, each of which
    gives it."""
    ivs = [reading.points[target].iv for reading in readings]
    known = [iv for iv in ivs if iv is not None]
    if len(known) != len(ivs):
        raise ValueError(f"a bracket expiry gives no {target} reading")
    if len(known) == 1:
        return Value(rounded(known[0] * _HUNDRED))
    (first, second), (lower, upper) = readings, known
    return Value(rounded(interpolate(lower, first.days, upper, second.days, horizon) * _HUNDRED))


def _no_bracket(where: str, passed: Sequence[ExpiryReading], horizon: int) -> str:
    if not passed:
        return f"no expiry is listed {where}"
    return f"no expiry listed {where} gives {_READINGS[horizon]}: " + "; ".join(
        reading.missing(REQUIRED[horizon]) for reading in passed
    )


def _skipped(*passed: Sequence[ExpiryReading]) -> tuple[ExpiryReading, ...]:
    """The readings passed over, once each (an expiry exactly at the horizon is sought twice),
    ascending."""
    by_expiry = {reading.expiry: reading for group in passed for reading in group}
    return tuple(by_expiry[expiry] for expiry in sorted(by_expiry))


def surface(
    session: dt.date, expiries: Sequence[dt.date], rows: Sequence[Record], horizon: int = HORIZON
) -> Surface:
    """The session's levels at ``horizon`` days (one of ``HORIZONS``) from the expiries it lists
    and the rows of (at least) the expiries it reads (``Surface.read``)."""
    if horizon not in REQUIRED:
        raise ValueError(f"the horizon must be one of {', '.join(map(str, HORIZONS))} days")
    targets = REQUIRED[horizon]
    by_expiry: dict[dt.date, list[Record]] = {}
    for row in rows:
        by_expiry.setdefault(row.expiry, []).append(row)
    cache: dict[dt.date, ExpiryReading] = {}

    def read(expiry: dt.date) -> ExpiryReading:
        if expiry not in cache:
            cache[expiry] = read_expiry(by_expiry.get(expiry, ()), expiry, session)
        return cache[expiry]

    lower_candidates, upper_candidates = _candidates(expiries, session, horizon)
    at = session + dt.timedelta(days=horizon)
    lower, passed_lower = _search(lower_candidates, read, targets)
    upper, passed_upper = (None, ()) if lower is None else _search(upper_candidates, read, targets)
    skipped = _skipped(passed_lower, passed_upper)
    if lower is None or upper is None:
        if lower is None:
            where = f"1 to {horizon} days out ({session + dt.timedelta(days=1)} to {at})"
            reason = _no_bracket(where, passed_lower, horizon)
        else:
            last = session + dt.timedelta(days=WINDOW_DAYS)
            reason = _no_bracket(
                f"{horizon} to {WINDOW_DAYS} days out ({at} to {last})", passed_upper, horizon
            )
        blank = Value(None, reason)
        return Surface(session, horizon, "none", (), {target: blank for target in targets}, skipped, reason)
    readings = tuple({reading.expiry: reading for reading in (lower, upper)}.values())
    method: Method = "exact" if lower.expiry == upper.expiry else "interpolated"
    levels = {target: _level(readings, target, horizon) for target in targets}
    return Surface(session, horizon, method, readings, levels, skipped)
