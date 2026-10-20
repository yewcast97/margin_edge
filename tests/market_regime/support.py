"""Clock readings and builders for the offline market_regime tests.

Expected instants are written with fixed ``EDT``/``EST`` offsets, independently of
``zoneinfo`` and of the code under test. Option records are built from strike, delta and
IV text, and daily bars from close text, so every expected value in a test can be worked
out by hand. No Tiingo answer is recorded: its data may not be redistributed.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from market_state_research.common.layout import DataLayout
from market_state_research.market_regime.script.api import FIELDS, Record
from market_state_research.market_regime.script.chain import Chain, Expiry
from market_state_research.market_regime.script.fetch import write_chain, write_prices
from market_state_research.market_regime.script.prices import BAR_FIELDS, Bar, Prices, check_bar
from market_state_research.market_regime.script.tiingo import prices_url

EDT = timezone(timedelta(hours=-4), "EDT")
EST = timezone(timedelta(hours=-5), "EST")
TICKER = "TEST"
CANARY = "CANARYkey0123456789"
TIINGO_CANARY = "TIINGOkey0123456789"


def edt(*fields: int) -> datetime:
    return datetime(*fields, tzinfo=EDT)


def est(*fields: int) -> datetime:
    return datetime(*fields, tzinfo=EST)


AS_OF = date(2026, 10, 16)  # a Friday session
NOW = edt(2026, 10, 19, 9, 0)  # Monday morning: the latest completed session is AS_OF
FETCHED = edt(2026, 10, 17, 10, 0)  # a Saturday, after every session these tests fetch

# One expiry's quotes worked by hand (surface's module docstring): the call IV is 0.29 at
# +0.50 and 0.2725 at +0.25, the put IV 0.345 at -0.50 and exactly 0.345 at -0.25 (strike
# 145), so the 25-delta skew is 7.25 pp and the ATM IV 31.75 %.
CALLS = (("150", "0.60", "0.30"), ("155", "0.40", "0.28"), ("160", "0.20", "0.27"))
PUTS = (
    ("155", "-0.65", "0.36"),
    ("150", "-0.45", "0.34"),
    ("145", "-0.25", "0.345"),
    ("140", "-0.15", "0.35"),
)


def occ(ticker: str, expiry: date, right: str, strike: str) -> str:
    """The OCC symbol of one contract."""
    thousandths = int(Decimal(strike) * 1000)
    return f"{ticker}{expiry:%y%m%d}{'C' if right == 'call' else 'P'}{thousandths:08d}"


def attributes(
    ticker: str,
    expiry: date,
    right: str,
    strike: str,
    *,
    delta: str | None = "0.5",
    iv: str | None = "0.3",
    bid: str | None = "1",
    ask: str | None = "1.1",
    volume: str | None = "0",
    open_interest: str | None = "0",
    tradetime: str | None = None,
    kind: str = "monthly",
) -> dict[str, str | None]:
    """One record's attributes as provider text, in ``FIELDS`` order."""
    values: dict[str, str | None] = {
        "contract": occ(ticker, expiry, right, strike),
        "exp_date": expiry.isoformat(),
        "expiration_type": kind,
        "type": right,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "volume": volume,
        "open_interest": open_interest,
        "volatility": iv,
        "delta": delta,
        "tradetime": tradetime,
    }
    return {name: values[name] for name in FIELDS}


def quotes(ticker: str, expiry: date, bump: str = "0", **extra: str | None) -> list[dict[str, str | None]]:
    """The hand-worked quotes at ``expiry``, every put IV raised by ``bump``: the skew is
    7.25 + 100 x bump pp and the ATM IV 31.75 + 50 x bump %."""
    rows = [
        attributes(ticker, expiry, "call", strike, delta=delta, iv=iv, **extra)  # type: ignore[arg-type]
        for strike, delta, iv in CALLS
    ]
    rows += [
        attributes(ticker, expiry, "put", strike, delta=delta, iv=str(Decimal(iv) + Decimal(bump)), **extra)  # type: ignore[arg-type]
        for strike, delta, iv in PUTS
    ]
    return rows


def eod(day: date, values: Mapping[str, str | None]) -> Record:
    """An ``eod`` record of ``values`` dated ``day``."""
    return Record(f"{values['contract']}-{day.isoformat()}", "options-eod", dict(values))


def listed(values: Mapping[str, str | None]) -> Record:
    """A ``contracts`` listing record of ``values``."""
    return Record(str(values["contract"]), "options-contracts", dict(values))


def chain(
    session: date,
    by_expiry: Mapping[date, Sequence[Mapping[str, str | None]]],
    *,
    ticker: str = TICKER,
    fetched_at: datetime = FETCHED,
    source: str = "eod",
    traded: Iterable[Mapping[str, str | None]] | None = None,
    requests: tuple[str, ...] = (
        "https://eodhd.com/api/mp/unicornbay/options/eod?filter%5Bunderlying_symbol%5D=TEST&page%5Blimit%5D=1000",
    ),
) -> Chain:
    """A chain of ``session`` listing ``by_expiry``; its rows are every expiry's records."""
    expiries = tuple(Expiry(expiry, len(by_expiry[expiry])) for expiry in sorted(by_expiry))
    if source == "eod":
        rows = tuple(eod(session, values) for expiry in sorted(by_expiry) for values in by_expiry[expiry])
        held = None
    else:
        rows = tuple(listed(values) for expiry in sorted(by_expiry) for values in by_expiry[expiry])
        held = tuple(eod(session, values) for values in (traded or ()))
    return Chain(session, ticker, fetched_at, source, requests, expiries, rows, held)  # type: ignore[arg-type]


def standard(session: date, bump: str = "0", ticker: str = TICKER, **options: object) -> Chain:
    """A session listing expiries 9, 19 and 40 days out with the hand-worked quotes, every put IV
    raised by ``bump``: E1 is 9 days out and E2 19, so the 14-DTE value is their mean. Its
    14-DTE skew is 7.25 + 100 x bump, its ATM IV 31.75 + 50 x bump, its 25-delta call IV 27.25
    and its put IV 34.50 + 100 x bump."""
    expiries = [session + timedelta(days=days) for days in (9, 19, 40)]
    return chain(
        session, {expiry: quotes(ticker, expiry, bump) for expiry in expiries}, ticker=ticker, **options
    )  # type: ignore[arg-type]


def save(layout: DataLayout, item: Chain) -> str:
    """Write ``item`` as ``fetch`` does; the file name."""
    return write_chain(layout, item).name


def bar_values(day: date, close: str, adjusted: str | None = None) -> dict[str, str]:
    """One daily bar as Tiingo's text: ``close`` everywhere, ``adjusted`` (default ``close``) as
    every adjusted price."""
    adjusted = close if adjusted is None else adjusted
    values = {
        "date": f"{day.isoformat()}T00:00:00.000Z",
        "close": close,
        "high": close,
        "low": close,
        "open": close,
        "volume": "1000",
        "adjClose": adjusted,
        "adjHigh": adjusted,
        "adjLow": adjusted,
        "adjOpen": adjusted,
        "adjVolume": "1000",
        "divCash": "0.0",
        "splitFactor": "1.0",
    }
    return {name: values[name] for name in BAR_FIELDS}


def bars(closes: Mapping[date, str]) -> tuple[Bar, ...]:
    """Bars of ``closes`` (adjusted close equal to close), ascending."""
    return tuple(
        check_bar(bar_values(day, closes[day]), number) for number, day in enumerate(sorted(closes), 1)
    )


def prices(
    closes: Mapping[date, str],
    *,
    start: date | None = None,
    end: date | None = None,
    ticker: str = TICKER,
    fetched_at: datetime = FETCHED,
) -> Prices:
    """A prices file of ``closes``, from ``start`` (default the first close's day) to ``end``
    (default the last's)."""
    days = sorted(closes)
    first = days[0] if start is None else start
    last = days[-1] if end is None else end
    return Prices(ticker, first, last, fetched_at, prices_url(ticker, first, last), bars(closes))


def rising(sessions: Sequence[date], first: str = "100") -> dict[date, str]:
    """Closes rising by 1 a session from ``first``: each return is 100 / the previous close %."""
    return {day: str(Decimal(first) + index) for index, day in enumerate(sorted(sessions))}


def save_prices(layout: DataLayout, item: Prices) -> str:
    """Write ``item`` as ``fetch`` does; the file name."""
    return write_prices(layout, item).name
