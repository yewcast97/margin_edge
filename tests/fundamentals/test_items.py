"""script/items.py: the catalogue of items a season is read against, and its order by importance.

The catalogue is data: these tests pin its shape (68 items in nine sections, who reads each,
the baselines, scopes and statuses the readings' rules depend on, each item's importance) and
the report's order. Every expected value is written out from the design, so a change to the
catalogue fails here first.
The domain's AGENTS.md states the catalogue for the bot, each item on a line of its own; the
last test holds those lines to the code.
"""

import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from market_state_research.fundamentals.script.items import (
    BOT_ITEMS,
    BY_ID,
    IMPORTANCE,
    ITEMS,
    PYTHON_ITEMS,
    SECTIONS,
    STATUSES,
    by_importance,
)
from market_state_research.fundamentals.script.readings import WORDING

COUNTS = {1: 10, 2: 11, 3: 11, 4: 8, 5: 7, 6: 6, 7: 4, 8: 6, 9: 5}  # the items of each section
IDS = [f"{section}.{number}" for section, count in COUNTS.items() for number in range(1, count + 1)]
PYTHON = ("2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.10", "2.11", "5.7", "8.5", "8.6")
PYTHON += ("9.1", "9.3", "9.4", "9.5")
WITHOUT_SOURCE = ("1.3", "1.8")
ANNUAL = ("3.2", "3.8", "3.9", "3.11", "4.8")
PROXY = ("5.5", "5.6")
CALL = ("7.1", "7.2", "7.3", "7.4", "8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "9.3")
NOT_DISCLOSED = ("1.1", "1.2", "1.4", "1.6", "1.7", "1.10", "2.7", "2.8", "2.9", "3.9", "3.10", "4.5")
NOT_DISCLOSED += ("4.6", "4.7", "4.8", "5.5", "5.6", "6.2", "6.5")
NOT_COMPUTABLE = ("2.9",)
HIGH = ("1.1", "1.2", "1.3", "1.5", "1.7", "2.3", "2.5", "3.1", "3.2", "3.3", "3.4", "3.5", "4.2", "4.4")
HIGH += ("5.1", "5.2", "6.5", "7.4", "8.3", "9.1", "9.2", "9.5")
LOW = ("1.9", "2.7", "2.10", "4.3", "6.2", "8.4", "8.5", "8.6", "9.4")
# A number a value is held to: "more than 5%", "above 0.7", "at least six", "twice", "15 days".
THRESHOLD = re.compile(
    r"more than|(above|below|under) \d|at least|twice|\d+ ?%|\d+ (days|basis points|percentage)"
)
AGENTS = Path(__file__).resolve().parents[2] / "market_state_research" / "fundamentals" / "AGENTS.md"


def ids(items) -> list[str]:
    return [item.id for item in items]


def test_the_catalogue_holds_68_items_numbered_in_order_within_nine_sections():
    assert ids(ITEMS) == IDS
    assert len(ITEMS) == 68
    assert [item.section for item in ITEMS] == [int(identifier.split(".")[0]) for identifier in IDS]


def test_the_sections_are_nine_titles():
    assert SECTIONS == {
        1: "Guidance",
        2: "Financials",
        3: "Accounting and audit",
        4: "Risk, legal and related parties",
        5: "Governance and insiders",
        6: "Capital allocation and financing",
        7: "Earnings call: statements",
        8: "Earnings call: questions and answers",
        9: "Disclosure",
    }


def test_python_reads_15_items_the_bot_51_and_2_have_no_source():
    assert ids(item for item in ITEMS if item.who == "python") == list(PYTHON)
    assert ids(item for item in ITEMS if item.who == "none") == list(WITHOUT_SOURCE)
    assert ids(item for item in ITEMS if item.who == "bot") == [
        identifier for identifier in IDS if identifier not in PYTHON + WITHOUT_SOURCE
    ]
    assert (len(PYTHON_ITEMS), len(BOT_ITEMS)) == (15, 51)


def test_the_bot_and_python_items_are_the_catalogues_in_its_order():
    assert ids(PYTHON_ITEMS) == list(PYTHON)
    assert ids(BOT_ITEMS) == [identifier for identifier in IDS if identifier not in PYTHON + WITHOUT_SOURCE]
    assert set(PYTHON_ITEMS).isdisjoint(BOT_ITEMS)


def test_an_item_is_found_by_its_id():
    assert list(BY_ID) == IDS
    assert all(BY_ID[identifier].id == identifier for identifier in IDS)
    assert (BY_ID["2.1"].title, BY_ID["2.10"].title) == (
        "Revenue and net income growth",
        "Weighted diluted shares",
    )


def test_a_heading_is_the_id_then_the_title():
    assert BY_ID["1.10"].heading == "1.10 Full-year kept, next quarter lowered"
    assert BY_ID["1.10"].section == 1
    assert BY_ID["9.5"].heading == "9.5 Call cancelled"
    assert BY_ID["9.4"].heading == "9.4 8-K count"


def test_an_item_cannot_be_changed():
    with pytest.raises(FrozenInstanceError):
        BY_ID["1.1"].rule = "Anything."  # type: ignore[misc]


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        pytest.param("annual", ANNUAL, id="annual"),
        pytest.param("proxy", PROXY, id="proxy"),
        pytest.param("call", CALL, id="call"),
        pytest.param("season", tuple(i for i in IDS if i not in ANNUAL + PROXY + CALL), id="season"),
    ],
)
def test_the_items_of_each_scope(scope, expected):
    assert ids(item for item in ITEMS if item.scope == scope) == list(expected)


@pytest.mark.parametrize(
    ("identifier", "baseline"),
    [
        ("1.1", "previous guidance"),
        ("1.7", "previous guidance"),
        ("1.9", "previous eight seasons"),
        ("2.1", "previous quarter and same quarter last year"),
        ("2.4", "same quarter last year"),
        ("2.5", "same quarter last year"),
        ("2.6", "previous quarter"),
        ("2.7", "same quarter last year"),
        ("2.9", "none"),
        ("3.1", "none"),
        ("3.3", "previous quarter"),
        ("4.1", "previous filings"),
        ("4.3", "previous filings"),
        ("5.1", "none"),
        ("5.7", "none"),
        ("6.4", "none"),
        ("8.5", "previous quarter"),
        ("9.1", "previous four seasons"),
        ("9.4", "previous four seasons"),
        ("9.5", "previous four seasons"),
    ],
)
def test_an_items_baseline(identifier, baseline):
    assert BY_ID[identifier].baseline == baseline


def test_annual_items_compare_with_the_previous_10k_and_proxy_items_with_the_previous_proxy():
    assert {BY_ID[identifier].baseline for identifier in ANNUAL} == {"previous 10-K"}
    assert {BY_ID[identifier].baseline for identifier in PROXY} == {"previous proxy"}


def test_the_items_without_a_source_compare_with_nothing():
    for identifier in WITHOUT_SOURCE:
        item = BY_ID[identifier]
        assert (item.baseline, item.scope, item.allows) == ("none", "season", frozenset())
        assert item.rule == "No source: the domain reads no consensus."


def test_not_disclosed_and_not_computable_are_allowed_where_the_catalogue_says():
    assert ids(item for item in ITEMS if "not disclosed" in item.allows) == list(NOT_DISCLOSED)
    assert ids(item for item in ITEMS if "not computable" in item.allows) == list(NOT_COMPUTABLE)
    assert all(item.allows <= {"not disclosed", "not computable"} for item in ITEMS)


def test_the_importance_levels_and_statuses():
    assert IMPORTANCE == ("high", "medium", "low")
    assert STATUSES == (
        "no baseline",
        "not applicable",
        "not disclosed",
        "unavailable",
        "not computable",
        "no source",
    )


def test_each_items_importance():
    assert ids(item for item in ITEMS if item.importance == "high") == list(HIGH)
    assert ids(item for item in ITEMS if item.importance == "low") == list(LOW)
    assert ids(item for item in ITEMS if item.importance == "medium") == [
        identifier for identifier in IDS if identifier not in HIGH + LOW
    ]
    assert (len(HIGH), len(IDS) - len(HIGH) - len(LOW), len(LOW)) == (22, 37, 9)


def test_the_reports_order_is_high_medium_low_each_in_catalogue_order():
    ordered = ids(by_importance())
    assert ordered == list(HIGH) + [i for i in IDS if i not in HIGH + LOW] + list(LOW)
    assert ids(by_importance((BY_ID["9.4"], BY_ID["2.1"], BY_ID["1.1"], BY_ID["1.4"]))) == [
        "1.1",
        "1.4",
        "2.1",
        "9.4",
    ]


def test_no_rule_holds_a_threshold_or_a_level():
    for item in ITEMS:
        assert "→" not in item.rule, item.id
        assert re.search(r"\b(red|yellow|grey)\b", item.rule) is None, item.id
        assert THRESHOLD.search(item.rule) is None, item.id


def test_a_compared_rule_states_the_seasons_old_and_new_values_come_from():
    for item in ITEMS:
        if item.who != "none" and item.baseline != "none":
            assert "against" in item.rule, item.id


def test_titles_and_rules_carry_no_valuation_forecast_or_advice_wording():
    for item in ITEMS:
        assert WORDING.search(item.title) is None, item.id
        assert WORDING.search(item.rule) is None, item.id
        assert item.title.isprintable() and item.rule.isprintable() and item.rule.endswith("."), item.id


def test_the_domains_agents_md_states_every_item_as_the_code_does():
    who = {"python": "Python", "bot": "bot", "none": "no source"}
    scope = {"season": "", "annual": "; annual item", "proxy": "; proxy item", "call": "; call item"}
    stated = AGENTS.read_text(encoding="utf-8")
    places = []
    for number, title in SECTIONS.items():
        places.append(stated.index(f"\n#### {number} {title}\n\n"))
        for item in ITEMS:
            if item.section != number:
                continue
            allows = " or ".join(f"`{status}`" for status in sorted(item.allows))
            line = (
                f"\n- **{item.heading}** ({who[item.who]}; {item.importance} importance; baseline: "
                f"{item.baseline}{scope[item.scope]}{'; may be ' + allows if allows else ''}): {item.rule}\n"
            )
            assert line in stated, item.id
            places.append(stated.index(line))
    assert places == sorted(places)
