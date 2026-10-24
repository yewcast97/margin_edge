"""script/aspects.py: the six aspects a season is read against, and the comparisons of each season.

The aspects are data: these tests pin their keys, titles and order, and hold the domain's
AGENTS.md table of them to the code. The comparisons are tried on listings built here: a
10-Q season has one, ``quarter``, against the season listed before it; a 10-K season has two,
``quarter`` and ``year``, against the season before it and against the previous 10-K season.
"""

from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from market_state_research.fundamentals.script.aspects import (
    ASPECTS,
    BASELINE_SEASONS,
    KINDS,
    Comparison,
    comparison,
    comparisons,
)
from market_state_research.fundamentals.script.filings import Filing, Season, Seasons
from market_state_research.fundamentals.script.readings import WORDING

AGENTS = Path(__file__).resolve().parents[2] / "market_state_research" / "fundamentals" / "AGENTS.md"


def season(form: str, period: date) -> Season:
    stamp = period.strftime("%Y%m%d")
    return Season(
        Filing(form, f"0000050863-{stamp[2:4]}-{stamp[4:]}00", period, period, f"intc-{stamp}.htm"), ()
    )


K_2023 = season("10-K", date(2023, 12, 30))
Q1_2024 = season("10-Q", date(2024, 3, 30))
Q2_2024 = season("10-Q", date(2024, 6, 29))
Q3_2024 = season("10-Q", date(2024, 9, 28))
K_2024 = season("10-K", date(2024, 12, 28))
Q1_2025 = season("10-Q", date(2025, 3, 29))
LISTING = Seasons((K_2023, Q1_2024, Q2_2024, Q3_2024, K_2024, Q1_2025), (), (), date(2024, 1, 31))


def test_the_six_aspects_in_their_order():
    assert [(aspect.key, aspect.title) for aspect in ASPECTS] == [
        ("guidance", "Guidance"),
        ("capex", "Capital expenditure"),
        ("supply", "Upstream supply"),
        ("demand", "Downstream demand"),
        ("debt", "Debt structure"),
        ("roadmap", "Product roadmap"),
    ]


def test_each_aspect_covers_one_sentence_of_facts_without_valuation_forecast_or_advice_wording():
    for aspect in ASPECTS:
        assert aspect.covers.isprintable() and aspect.covers.endswith("."), aspect.key
        assert aspect.covers.count(". ") == 0, aspect.key
        assert WORDING.search(aspect.title) is None and WORDING.search(aspect.covers) is None, aspect.key


def test_an_aspect_cannot_be_changed():
    with pytest.raises(FrozenInstanceError):
        ASPECTS[0].title = "Outlook"  # type: ignore[misc]


def test_the_kinds_and_the_seasons_a_comparison_reaches_back():
    assert KINDS == ("quarter", "year")
    assert BASELINE_SEASONS == 4


def test_a_10_q_season_is_compared_with_the_season_before_it_alone():
    assert comparisons(LISTING, Q2_2024) == (Comparison("quarter", Q1_2024),)
    assert comparison(LISTING, Q2_2024, "quarter") == Comparison("quarter", Q1_2024)
    assert comparison(LISTING, Q2_2024, "year") is None


def test_the_first_quarter_is_compared_with_the_10_k_season():
    assert comparisons(LISTING, Q1_2025) == (Comparison("quarter", K_2024),)
    assert comparisons(LISTING, Q1_2024) == (Comparison("quarter", K_2023),)


def test_a_10_k_season_is_compared_with_the_third_quarter_and_with_the_previous_10_k():
    assert comparisons(LISTING, K_2024) == (Comparison("quarter", Q3_2024), Comparison("year", K_2023))
    assert comparison(LISTING, K_2024, "year") == Comparison("year", K_2023)


def test_a_comparison_whose_baseline_is_not_listed_has_none():
    assert comparisons(LISTING, K_2023) == (Comparison("quarter", None), Comparison("year", None))
    # Five quarters between two 10-Ks: the previous 10-K is beyond the four seasons reached back.
    gap = (
        K_2023,
        Q1_2024,
        Q2_2024,
        Q3_2024,
        season("10-Q", date(2024, 12, 28)),
        season("10-K", date(2025, 3, 29)),
    )
    listing = Seasons(gap, (), (), date(2024, 1, 31))
    assert comparisons(listing, gap[-1]) == (Comparison("quarter", gap[-2]), Comparison("year", None))


def test_a_season_the_listing_does_not_hold_has_no_baseline():
    other = season("10-Q", date(2025, 6, 28))
    assert comparisons(LISTING, other) == (Comparison("quarter", None),)


def test_the_domains_agents_md_states_every_aspect_as_the_code_does():
    stated = AGENTS.read_text(encoding="utf-8")
    places = []
    for aspect in ASPECTS:
        line = f"\n| `{aspect.key}` | {aspect.title} | {aspect.covers} |\n"
        assert line in stated, aspect.key
        places.append(stated.index(line))
    assert places == sorted(places)
