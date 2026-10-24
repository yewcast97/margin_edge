"""The six aspects a season is read against, and the comparisons each season is read in.

Pure data. An aspect (``ASPECTS``, in the order every readings file and report follows) is one
subject the bot reads the documents for: the issuer's guidance, its capital expenditure, its
upstream supply, its downstream demand, its debt structure and its product roadmap, each with
one sentence of what it covers, its whole definition. Within an aspect the bot lists every item
it finds, as the documents of the season and of the baseline state it, with no fixed list of
items: an aspect whose documents state nothing of it is ``na``. Nothing ranks, weighs or
scores an aspect or an item.

A season is read in one comparison per kind (``Kind``) that applies to it (``comparisons``):
``quarter`` for every season, against the previous listed season, so that a 10-Q season is
compared with the quarter before it and the first quarter with the 10-K season, the fourth;
and ``year`` for a 10-K season alone, against the latest 10-K season among the
``BASELINE_SEASONS`` listed before it, the previous fiscal year's. A comparison's baseline is
every document of its season: the 10-K or 10-Q, the 8-Ks Rule B places in it and its call.
``fetch`` writes the window's seasons and the ``BASELINE_SEASONS`` listed before the oldest of
them, so the baselines of every window season are in ``raw/``.
"""

from dataclasses import dataclass
from typing import Final, Literal

from .filings import Season, Seasons

Kind = Literal["quarter", "year"]

KINDS: Final[tuple[Kind, ...]] = ("quarter", "year")
# How many listed seasons back a comparison reaches: the previous 10-K season is the fourth.
BASELINE_SEASONS: Final = 4


@dataclass(frozen=True)
class Aspect:
    """One aspect: its key, its title (the heading of its section in a readings file and a report)
    and what it covers."""

    key: str
    title: str
    covers: str


ASPECTS: Final[tuple[Aspect, ...]] = (
    Aspect(
        "guidance",
        "Guidance",
        "Every measure the issuer guides (revenue, margins, earnings per share, expenses, tax rate, cash "
        "flow, share count and any other), each with its period, its range or point and its basis, and "
        "the results of a period set against the guidance given for it.",
    ),
    Aspect(
        "capex",
        "Capital expenditure",
        "Capital expenditure as guided and as spent, gross and net of partners' contributions, grants and "
        "other offsets, and the projects it funds (fabs, plants, equipment) with their timing.",
    ),
    Aspect(
        "supply",
        "Upstream supply",
        "The inputs the issuer buys or makes: suppliers, components, materials, wafers, substrates, "
        "equipment and capacity, with their availability, constraints, lead times and prices, and the "
        "issuer's own inventory.",
    ),
    Aspect(
        "demand",
        "Downstream demand",
        "Customers and end markets: demand, orders, backlog, bookings, pricing, customers' inventory and "
        "the share of revenue from the largest customers.",
    ),
    Aspect(
        "debt",
        "Debt structure",
        "Notes and loans with their rates and maturities, credit facilities and what they leave available, "
        "commercial paper, covenants, issuance, repayment and refinancing, and interest expense.",
    ),
    Aspect(
        "roadmap",
        "Product roadmap",
        "Products, process nodes, technologies and services: launches, ramps, timelines, milestones, "
        "delays and discontinuations.",
    ),
)


@dataclass(frozen=True)
class Comparison:
    """One comparison of a season: its kind and its baseline season (None when none is listed)."""

    kind: Kind
    baseline: Season | None


def comparisons(listing: Seasons, season: Season) -> tuple[Comparison, ...]:
    """The comparisons of ``season`` (module docstring): ``quarter``, then ``year`` for a 10-K
    season."""
    earlier = listing.before(season, BASELINE_SEASONS)
    found = [Comparison("quarter", earlier[0] if earlier else None)]
    if season.filing.form == "10-K":
        found.append(
            Comparison("year", next((other for other in earlier if other.filing.form == "10-K"), None))
        )
    return tuple(found)


def comparison(listing: Seasons, season: Season, kind: Kind) -> Comparison | None:
    """The comparison of ``kind`` of ``season``, or None: a 10-Q season has no ``year``."""
    return next((found for found in comparisons(listing, season) if found.kind == kind), None)
