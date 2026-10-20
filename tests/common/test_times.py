"""common/times.py: New York time, the fixed-offset normalisation and file-name tokens.

Expected values are fixed ``EDT``/``EST`` offsets written out independently of
``zoneinfo``. The fall-back hour (2026-11-01 01:00-02:00 occurs twice) and the
spring-forward gap (2026-03-08 02:00-03:00 does not exist) are covered for every
conversion, token and ordering path, together with the comparison pitfall of raw
``ZoneInfo`` datetimes that ``to_eastern`` exists to avoid.
"""

import re
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from market_state_research.common.times import (
    NEW_YORK,
    TOKEN_FORMAT,
    TOKEN_PATTERN,
    eastern_midnight,
    epoch_ms,
    et_display,
    et_isoformat,
    from_epoch_ms,
    parse_timestamp_token,
    require_aware,
    timestamp_token,
    to_eastern,
)

from .support import (
    ARABIC_INDIC_ZERO,
    EDT,
    EST,
    FULLWIDTH_ZERO,
    MICROSECOND,
    NOW,
    TOKYO,
    OffsetlessZone,
    edt,
    est,
    foreign_digits,
)

SECOND = timedelta(seconds=1)
HOUR = timedelta(hours=1)
ERA = "falls outside New York's EDT/EST era"
NAIVE = [
    pytest.param(NOW.replace(tzinfo=None), id="naive"),
    pytest.param(datetime(2026, 10, 2, 20, tzinfo=OffsetlessZone()), id="tzinfo-without-offset"),
]


def utc(*fields: int) -> datetime:
    return datetime(*fields, tzinfo=UTC)


def ny(*fields: int, fold: int = 0) -> datetime:
    """A raw ``ZoneInfo`` New York wall clock reading, as a library or a clock may supply it."""
    return datetime(*fields, tzinfo=NEW_YORK, fold=fold)


def assert_eastern(moment: datetime, text: str) -> None:
    """``moment`` is a fixed-offset EDT/EST datetime whose ISO text is exactly ``text``."""
    assert type(moment) is datetime
    assert type(moment.tzinfo) is timezone
    assert moment.fold == 0
    assert moment.isoformat() == text
    assert moment.tzname() == {"-04:00": "EDT", "-05:00": "EST"}[text[-6:]]


def test_new_york_is_the_iana_zone_and_tokens_have_a_fixed_shape():
    assert ZoneInfo("America/New_York") is NEW_YORK  # cached: every New York datetime shares it
    assert NEW_YORK.key == "America/New_York"
    assert TOKEN_FORMAT == "%Y%m%dT%H%M%S"
    assert TOKEN_PATTERN == r"[0-9]{8}T[0-9]{6}(?:EDT|EST)"


# --- require_aware ------------------------------------------------------------------------------


def test_require_aware_accepts_aware_datetimes():
    assert require_aware(NOW) is None
    assert require_aware(NOW.astimezone(ZoneInfo("Asia/Tokyo")), "captured_at") is None
    assert require_aware(ny(2026, 11, 1, 1, 30, fold=1)) is None


@pytest.mark.parametrize("moment", NAIVE)
def test_require_aware_names_the_rejected_value(moment):
    with pytest.raises(ValueError, match="^now must include a timezone$"):
        require_aware(moment)
    with pytest.raises(ValueError, match="^captured_at must include a timezone$"):
        require_aware(moment, "captured_at")


# --- to_eastern ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "text"),
    [
        pytest.param(utc(2026, 10, 2, 20), "2026-10-02T16:00:00-04:00", id="utc-summer"),
        pytest.param(utc(2026, 12, 4, 21), "2026-12-04T16:00:00-05:00", id="utc-winter"),
        pytest.param(utc(2026, 10, 3, 2), "2026-10-02T22:00:00-04:00", id="utc-next-day"),
        pytest.param(datetime(2026, 10, 3, 5, tzinfo=TOKYO), "2026-10-02T16:00:00-04:00", id="tokyo-fixed"),
        pytest.param(
            datetime(2026, 10, 3, 1, 45, tzinfo=ZoneInfo("Asia/Kathmandu")),
            "2026-10-02T16:00:00-04:00",
            id="kathmandu-0545",
        ),
        pytest.param(
            datetime(2026, 10, 2, 8, tzinfo=timezone(timedelta(hours=-12))),
            "2026-10-02T16:00:00-04:00",
            id="fixed-minus12",
        ),
        pytest.param(edt(2026, 10, 2, 16), "2026-10-02T16:00:00-04:00", id="already-eastern"),
        pytest.param(ny(2026, 10, 2, 16), "2026-10-02T16:00:00-04:00", id="zoneinfo-summer"),
        pytest.param(ny(2026, 12, 4, 16), "2026-12-04T16:00:00-05:00", id="zoneinfo-winter"),
        pytest.param(
            utc(2026, 10, 6, 9, 9, 17, 44_000), "2026-10-06T05:09:17.044000-04:00", id="microseconds-kept"
        ),
        pytest.param(utc(2026, 3, 8, 6, 59, 59), "2026-03-08T01:59:59-05:00", id="last-second-before-gap"),
        pytest.param(utc(2026, 3, 8, 7), "2026-03-08T03:00:00-04:00", id="first-second-after-gap"),
        pytest.param(utc(2026, 11, 1, 5, 59, 59), "2026-11-01T01:59:59-04:00", id="last-edt-second"),
        pytest.param(utc(2026, 11, 1, 6), "2026-11-01T01:00:00-05:00", id="first-est-second"),
        pytest.param(ny(2026, 11, 1, 1, 30), "2026-11-01T01:30:00-04:00", id="fall-back-fold-0"),
        pytest.param(ny(2026, 11, 1, 1, 30, fold=1), "2026-11-01T01:30:00-05:00", id="fall-back-fold-1"),
        # A wall time in the gap does not exist: fold 0 reads it with the earlier offset (EST)
        # and fold 1 with the later one (EDT); each names a real instant outside the gap.
        pytest.param(ny(2026, 3, 8, 2, 30), "2026-03-08T03:30:00-04:00", id="gap-fold-0"),
        pytest.param(ny(2026, 3, 8, 2, 30, fold=1), "2026-03-08T01:30:00-05:00", id="gap-fold-1"),
        pytest.param(
            utc(9999, 12, 31, 23, 59, 59, 999_999), "9999-12-31T18:59:59.999999-05:00", id="latest-instant"
        ),
    ],
)
def test_to_eastern_keeps_the_instant_with_a_fixed_edt_or_est_offset(moment, text):
    eastern = to_eastern(moment)

    assert_eastern(eastern, text)
    assert eastern.astimezone(UTC) == moment.astimezone(UTC)
    assert eastern - moment == timedelta(0)
    assert to_eastern(eastern).isoformat() == text  # idempotent


def test_to_eastern_never_depends_on_the_input_zone():
    instant = utc(2026, 11, 1, 6, 30)  # 01:30 EST, the second 01:30 of the fall-back day
    readings = [
        instant,
        instant.astimezone(NEW_YORK),
        instant.astimezone(ZoneInfo("Asia/Tokyo")),
        instant.astimezone(TOKYO),
        instant.astimezone(EDT),
        instant.astimezone(EST),
        ny(2026, 11, 1, 1, 30, fold=1),
    ]
    assert {to_eastern(reading).isoformat() for reading in readings} == {"2026-11-01T01:30:00-05:00"}


@pytest.mark.parametrize("moment", NAIVE)
def test_to_eastern_rejects_a_moment_without_a_utc_offset(moment):
    with pytest.raises(ValueError, match="^timestamp must include a timezone$"):
        to_eastern(moment)
    with pytest.raises(ValueError, match="^captured_at must include a timezone$"):
        to_eastern(moment, "captured_at")


@pytest.mark.parametrize(
    ("instant", "text"),
    [
        pytest.param(utc(1883, 11, 18, 17), "1883-11-18T12:00:00-05:00", id="standard-time-adopted"),
        pytest.param(
            utc(1942, 2, 9, 7) - MICROSECOND, "1942-02-09T01:59:59.999999-05:00", id="before-war-time"
        ),
        pytest.param(utc(1945, 9, 30, 6), "1945-09-30T01:00:00-05:00", id="after-war-time"),
    ],
)
def test_to_eastern_accepts_every_edt_or_est_instant_up_to_the_era_boundaries(instant, text):
    assert_eastern(to_eastern(instant), text)


@pytest.mark.parametrize(
    "instant",
    [
        pytest.param(utc(1883, 11, 18, 17) - MICROSECOND, id="local-mean-time"),
        pytest.param(utc(1942, 2, 9, 7), id="war-time-begins"),
        pytest.param(utc(1943, 6, 1), id="war-time"),
        pytest.param(utc(1945, 9, 30, 6) - MICROSECOND, id="peace-time-ends"),
        pytest.param(utc(1, 1, 1, 5), id="year-1"),
    ],
)
def test_to_eastern_refuses_instants_new_york_named_neither_edt_nor_est(instant):
    with pytest.raises(ValueError, match=f"^timestamp {ERA}$"):
        to_eastern(instant)
    with pytest.raises(ValueError, match=f"^captured_at {ERA}$"):
        to_eastern(instant, "captured_at")


@pytest.mark.parametrize(
    "moment",
    [
        pytest.param(utc(1, 1, 1), id="new-york-before-year-1"),
        pytest.param(datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))), id="utc-before-year-1"),
        pytest.param(est(9999, 12, 31, 19), id="utc-after-year-9999"),
    ],
)
def test_to_eastern_overflows_outside_the_datetime_range(moment):
    with pytest.raises(OverflowError):
        to_eastern(moment)


# --- the comparison pitfall ---------------------------------------------------------------------


def test_raw_new_york_datetimes_compare_by_wall_time_but_eastern_ones_by_instant():
    first, second = ny(2026, 11, 1, 1, 30), ny(2026, 11, 1, 1, 30, fold=1)

    # The pitfall: one shared ZoneInfo object, so Python compares wall times and ignores fold.
    assert first.tzinfo is second.tzinfo
    assert first == second
    assert second - first == timedelta(0)
    # Normalised, they are the two distinct instants they denote.
    assert to_eastern(first) != to_eastern(second)
    assert to_eastern(first) < to_eastern(second)
    assert to_eastern(second) - to_eastern(first) == HOUR
    assert to_eastern(first) + HOUR == to_eastern(second)
    # PEP 495: an inter-zone == with a time whose offset depends on fold is always False,
    # even for the same instant; ordering and subtraction do respect fold.
    assert to_eastern(second) != second
    assert not to_eastern(second) < second and not to_eastern(second) > second
    assert to_eastern(second) - second == timedelta(0)
    assert to_eastern(second).astimezone(UTC) == second.astimezone(UTC)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(ny(2026, 11, 1, 1, 30), id="fall-back-fold-0"),
        pytest.param(ny(2026, 11, 1, 1, 30, fold=1), id="fall-back-fold-1"),
        pytest.param(ny(2026, 3, 8, 2, 30), id="spring-forward-gap-fold-0"),
        pytest.param(ny(2026, 3, 8, 2, 30, fold=1), id="spring-forward-gap-fold-1"),
    ],
)
def test_equality_and_hashing_need_both_operands_normalised_when_the_offset_depends_on_fold(raw):
    """As ``to_eastern`` documents: ordering and subtraction work against a raw ``ZoneInfo``
    time, but ``==``, ``!=`` and set or dict lookups hold only between normalised values."""
    eastern = to_eastern(raw)

    assert eastern - raw == timedelta(0) and raw - eastern == timedelta(0)
    assert not eastern < raw and not eastern > raw and eastern <= raw and eastern >= raw
    assert eastern != raw and raw != eastern
    assert raw not in {eastern} and eastern not in {raw}
    assert eastern not in {raw: None}
    assert eastern == to_eastern(raw) == to_eastern(eastern.astimezone(UTC))
    assert to_eastern(raw) in {eastern}
    assert hash(to_eastern(raw)) == hash(eastern)


def test_a_raw_time_whose_offset_does_not_depend_on_fold_equals_its_normalised_instant():
    raw = ny(2026, 10, 6, 5, 9, 17)
    assert to_eastern(raw) == raw
    assert raw in {to_eastern(raw)}


def test_sorting_normalised_instants_is_chronological_through_the_fall_back_hour():
    readings = [
        ny(2026, 11, 1, 1, 0, fold=1),  # 01:00 EST
        ny(2026, 11, 1, 1, 59, 59),  # 01:59:59 EDT
        ny(2026, 11, 1, 1, 30, fold=1),  # 01:30 EST
        ny(2026, 11, 1, 1, 30),  # 01:30 EDT
    ]
    chronological = [
        "2026-11-01T01:30:00-04:00",
        "2026-11-01T01:59:59-04:00",
        "2026-11-01T01:00:00-05:00",
        "2026-11-01T01:30:00-05:00",
    ]
    assert [to_eastern(value).isoformat() for value in sorted(readings)] != chronological  # wall-time order
    assert [value.isoformat() for value in sorted(map(to_eastern, readings))] == chronological
    assert [to_eastern(value).isoformat() for value in sorted(readings, key=to_eastern)] == chronological


def test_fixed_offset_arithmetic_spans_daylight_saving_changes_exactly():
    # Wall-clock arithmetic on a ZoneInfo datetime keeps the wall time; on a fixed offset it
    # is elapsed time, which is what a settle period or a deadline means.
    friday = ny(2026, 10, 30, 16)
    assert (friday + timedelta(days=3)).isoformat() == "2026-11-02T16:00:00-05:00"
    assert to_eastern(to_eastern(friday) + timedelta(days=3)).isoformat() == "2026-11-02T15:00:00-05:00"
    assert to_eastern(est(2026, 3, 8, 1, 59, 59) + SECOND).isoformat() == "2026-03-08T03:00:00-04:00"


# --- et_isoformat and et_display ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "text"),
    [
        pytest.param(edt(2026, 10, 2, 17), "2026-10-02T17:00:00-04:00", id="edt"),
        pytest.param(est(2026, 12, 4, 16), "2026-12-04T16:00:00-05:00", id="est"),
        pytest.param(utc(2026, 10, 2, 21), "2026-10-02T17:00:00-04:00", id="utc-converted"),
        pytest.param(
            edt(2026, 10, 2, 17, 0, 0, 123_456), "2026-10-02T17:00:00.123456-04:00", id="microseconds"
        ),
        pytest.param(edt(2026, 10, 2, 17, 0, 0, 1), "2026-10-02T17:00:00.000001-04:00", id="one-microsecond"),
        pytest.param(
            datetime(2026, 10, 3, 6, 0, 0, 500_000, tzinfo=TOKYO),
            "2026-10-02T17:00:00.500000-04:00",
            id="positive-offset-with-fraction",
        ),
        pytest.param(ny(2026, 11, 1, 1, 30), "2026-11-01T01:30:00-04:00", id="fall-back-first"),
        pytest.param(ny(2026, 11, 1, 1, 30, fold=1), "2026-11-01T01:30:00-05:00", id="fall-back-second"),
    ],
)
def test_et_isoformat_is_new_york_time_with_offset_and_full_precision(moment, text):
    assert et_isoformat(moment) == text
    assert "Z" not in text and "+00:00" not in text
    parsed = datetime.fromisoformat(text)
    assert parsed.astimezone(UTC) == moment.astimezone(UTC)
    assert et_isoformat(parsed) == text  # exact round trip
    assert timestamp_token(parsed) == timestamp_token(moment)


@pytest.mark.parametrize(
    ("moment", "text"),
    [
        pytest.param(
            utc(2026, 10, 6, 9, 9, 17, 44_000), "2026-10-06 05:09:17 EDT", id="edt-truncates-fraction"
        ),
        pytest.param(utc(2026, 12, 4, 21, 0, 0, 999_999), "2026-12-04 16:00:00 EST", id="est"),
        pytest.param(ny(2026, 11, 1, 1, 30), "2026-11-01 01:30:00 EDT", id="fall-back-first"),
        pytest.param(ny(2026, 11, 1, 1, 30, fold=1), "2026-11-01 01:30:00 EST", id="fall-back-second"),
    ],
)
def test_et_display_is_new_york_time_to_the_second_with_its_zone(moment, text):
    assert et_display(moment) == text


@pytest.mark.parametrize("helper", [et_isoformat, et_display, timestamp_token, epoch_ms])
@pytest.mark.parametrize("moment", NAIVE)
def test_time_helpers_reject_moments_without_a_utc_offset(helper, moment):
    with pytest.raises(ValueError, match="^timestamp must include a timezone$"):
        helper(moment)


# --- timestamp_token ----------------------------------------------------------------------------


def test_timestamp_token_is_compact_new_york_time_with_its_zone():
    token = timestamp_token(edt(2026, 10, 2, 17, 30, 15))
    assert token == "20261002T173015EDT"
    assert re.fullmatch(TOKEN_PATTERN, token, re.ASCII)
    assert timestamp_token(NOW) == "20261002T200000EDT"
    assert timestamp_token(est(2026, 12, 4, 16)) == "20261204T160000EST"


@pytest.mark.parametrize(
    ("moment", "token"),
    [
        pytest.param(utc(2026, 10, 2, 21, 30, 15), "20261002T173015EDT", id="utc"),
        pytest.param(utc(2026, 10, 3, 2), "20261002T220000EDT", id="utc-already-next-day"),
        pytest.param(datetime(2026, 10, 3, 6, tzinfo=TOKYO), "20261002T170000EDT", id="positive-offset"),
        pytest.param(ny(2026, 10, 2, 16), "20261002T160000EDT", id="new-york-summer"),
        pytest.param(ny(2026, 12, 4, 16), "20261204T160000EST", id="new-york-winter"),
        pytest.param(ny(2026, 11, 1, 1, 30), "20261101T013000EDT", id="fall-back-first"),
        pytest.param(ny(2026, 11, 1, 1, 30, fold=1), "20261101T013000EST", id="fall-back-second"),
        pytest.param(ny(2026, 3, 8, 2, 30), "20260308T033000EDT", id="gap-fold-0"),
        pytest.param(ny(2026, 3, 8, 2, 30, fold=1), "20260308T013000EST", id="gap-fold-1"),
    ],
)
def test_timestamp_token_names_the_new_york_wall_time_and_zone(moment, token):
    assert timestamp_token(moment) == token


def test_timestamp_token_truncates_sub_second_precision():
    assert timestamp_token(edt(2026, 10, 2, 17, 30, 15, 999_999)) == "20261002T173015EDT"
    assert timestamp_token(edt(2026, 10, 2, 17, 30, 16)) == "20261002T173016EDT"


def test_timestamp_tokens_must_be_ordered_by_instant_never_as_strings():
    earlier, later = "20261101T015959EDT", "20261101T010000EST"

    assert earlier > later  # string order is wrong in the fall-back hour
    assert parse_timestamp_token(earlier) < parse_timestamp_token(later)
    assert parse_timestamp_token(later) - parse_timestamp_token(earlier) == SECOND
    tokens = [timestamp_token(utc(2026, 11, 1, 5, 59, 59) + SECOND * step) for step in range(3)]
    assert tokens == ["20261101T015959EDT", "20261101T010000EST", "20261101T010001EST"]
    assert sorted(tokens) != tokens
    assert sorted(tokens, key=parse_timestamp_token) == tokens


# --- parse_timestamp_token ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "text"),
    [
        pytest.param("20261002T200000EDT", "2026-10-02T20:00:00-04:00", id="edt"),
        pytest.param("20261204T160000EST", "2026-12-04T16:00:00-05:00", id="est"),
        pytest.param("20261101T013000EDT", "2026-11-01T01:30:00-04:00", id="fall-back-first"),
        pytest.param("20261101T013000EST", "2026-11-01T01:30:00-05:00", id="fall-back-second"),
        pytest.param("20261101T005959EDT", "2026-11-01T00:59:59-04:00", id="before-the-repeated-hour"),
        pytest.param("20261101T010000EDT", "2026-11-01T01:00:00-04:00", id="repeated-hour-starts-edt"),
        pytest.param("20261101T015959EDT", "2026-11-01T01:59:59-04:00", id="repeated-hour-ends-edt"),
        pytest.param("20261101T010000EST", "2026-11-01T01:00:00-05:00", id="repeated-hour-starts-est"),
        pytest.param("20261101T015959EST", "2026-11-01T01:59:59-05:00", id="repeated-hour-ends-est"),
        pytest.param("20261101T020000EST", "2026-11-01T02:00:00-05:00", id="after-the-repeated-hour"),
        pytest.param("20260308T015959EST", "2026-03-08T01:59:59-05:00", id="before-the-gap"),
        pytest.param("20260308T030000EDT", "2026-03-08T03:00:00-04:00", id="after-the-gap"),
        pytest.param("20240229T120000EST", "2024-02-29T12:00:00-05:00", id="leap-day"),
        pytest.param("18831118T120000EST", "1883-11-18T12:00:00-05:00", id="first-est-instant"),
        pytest.param("19420209T015959EST", "1942-02-09T01:59:59-05:00", id="last-est-second-before-war-time"),
        pytest.param("19450930T010000EST", "1945-09-30T01:00:00-05:00", id="first-est-second-after-war-time"),
        pytest.param("99991231T185959EST", "9999-12-31T18:59:59-05:00", id="last-representable-second"),
    ],
)
def test_parse_timestamp_token_returns_the_fixed_offset_instant(token, text):
    instant = parse_timestamp_token(token)

    assert_eastern(instant, text)
    assert timestamp_token(instant) == token


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("20260308T020000EST", id="gap-start-est"),
        pytest.param("20260308T020000EDT", id="gap-start-edt"),
        pytest.param("20260308T023000EST", id="gap-middle-est"),
        pytest.param("20260308T023000EDT", id="gap-middle-edt"),
        pytest.param("20260308T025959EST", id="gap-end-est"),
        pytest.param("20260308T025959EDT", id="gap-end-edt"),
        pytest.param("20260308T015959EDT", id="edt-before-the-gap"),
        pytest.param("20260308T030000EST", id="est-after-the-gap"),
        pytest.param("20261101T005959EST", id="est-before-the-repeated-hour"),
        pytest.param("20261101T020000EDT", id="edt-after-the-repeated-hour"),
        pytest.param("20260701T120000EST", id="est-in-summer"),
        pytest.param("20261204T120000EDT", id="edt-in-winter"),
        pytest.param("19430601T120000EDT", id="war-time-is-not-edt"),
        # A gap whose wall time reads as EST but whose instant falls in war time.
        pytest.param("19420209T023000EST", id="gap-into-war-time"),
        pytest.param("19450930T005959EST", id="peace-time-is-not-est"),
        pytest.param("18831118T115959EST", id="local-mean-time"),
        pytest.param("99991231T190000EST", id="beyond-the-datetime-range"),
        pytest.param("99991231T235959EST", id="last-wall-second-of-9999"),
    ],
)
def test_parse_timestamp_token_rejects_wall_times_that_never_occurred_in_that_zone(token):
    assert parse_timestamp_token(token) is None


REJECTED_TOKENS = {
    "old-utc-z": "20261002T213015Z",
    "utc-suffix": "20261002T213015UTC",
    "gmt-suffix": "20261002T213015GMT",
    "other-zone": "20261002T213015PDT",
    "lowercase-zone": "20261002T213015edt",
    "mixed-case-zone": "20261002T213015Edt",
    "missing-zone": "20261002T213015",
    "numeric-offset": "20261002T213015-0400",
    "lowercase-t": "20261002t213015EDT",
    "space-separator": "20261002 213015EDT",
    "extended-iso": "2026-10-02T21:30:15EDT",
    "short-time": "20261002T2130EDT",
    "nine-digit-date": "202610021T213015EDT",
    "impossible-timestamp": "20261332T250000EDT",
    "february-30": "20260230T120000EST",
    "month-zero": "20260002T120000EST",
    "hour-24": "20261002T240000EDT",
    "minute-60": "20261002T216000EDT",
    "leap-second": "20261002T215960EDT",
    "year-zero": "00001002T213015EDT",
    "fullwidth-digits": foreign_digits("20261002T213015", FULLWIDTH_ZERO) + "EDT",
    "arabic-indic-digits": foreign_digits("20261002T213015", ARABIC_INDIC_ZERO) + "EDT",
    "trailing-newline": "20261002T213015EDT\n",
    "trailing-space": "20261002T213015EDT ",
    "leading-space": " 20261002T213015EDT",
    "trailing-junk": "20261002T213015EDTX",
    "doubled-zone": "20261002T213015EDTEDT",
    "empty": "",
}


@pytest.mark.parametrize("token", list(REJECTED_TOKENS.values()), ids=list(REJECTED_TOKENS))
def test_parse_timestamp_token_rejects_non_canonical_text(token):
    assert parse_timestamp_token(token) is None


def every_wall_token(day: date, hours: int) -> set[str]:
    """Every syntactically valid token for the first ``hours`` wall-clock hours of ``day``, in both zones."""
    start = datetime.combine(day, datetime.min.time())
    return {
        (start + SECOND * step).strftime(TOKEN_FORMAT) + zone
        for step in range(hours * 3600)
        for zone in ("EDT", "EST")
    }


@pytest.mark.parametrize(
    ("day", "hours", "end"),
    [
        pytest.param(date(2026, 10, 2), 4, "20261002T040000EDT", id="edt-day"),
        pytest.param(date(2026, 12, 4), 4, "20261204T040000EST", id="est-day"),
        pytest.param(date(2026, 3, 8), 3, "20260308T040000EDT", id="spring-forward-day-loses-an-hour"),
        pytest.param(date(2026, 11, 1), 5, "20261101T040000EST", id="fall-back-day-repeats-an-hour"),
    ],
)
def test_tokens_and_instants_correspond_one_to_one_on_the_second_grid(day, hours, end):
    """The first four wall-clock hours of each day: every instant has a distinct token that
    parses back to it, and no other token of those wall times parses at all."""
    start = eastern_midnight(day)
    moments = [start + SECOND * step for step in range(hours * 3600)]
    assert timestamp_token(moments[-1] + SECOND) == end  # the instants fill exactly four wall hours

    tokens = [timestamp_token(moment) for moment in moments]

    assert len(set(tokens)) == len(moments)
    assert [parse_timestamp_token(token) for token in tokens] == moments
    valid = {token for token in every_wall_token(day, 4) if parse_timestamp_token(token) is not None}
    assert valid == set(tokens)


@pytest.mark.parametrize(
    "moment",
    [
        pytest.param(NOW, id="clock-now"),
        pytest.param(edt(2026, 10, 2, 17, 0, 0, 999_999), id="fractional-second"),
        pytest.param(est(2024, 2, 29, 23, 59, 59), id="leap-day"),
        pytest.param(ny(2026, 11, 1, 1, 30), id="fall-back-first"),
        pytest.param(ny(2026, 11, 1, 1, 30, fold=1), id="fall-back-second"),
        pytest.param(utc(2026, 3, 8, 7), id="first-second-after-gap"),
    ],
)
def test_tokens_from_a_clock_parse_back_to_the_clock_second(moment):
    parsed = parse_timestamp_token(timestamp_token(moment))

    assert parsed == to_eastern(moment).replace(microsecond=0)
    assert parsed <= moment < parsed + SECOND


# --- eastern_midnight ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "text", "length"),
    [
        pytest.param(date(2026, 10, 2), "2026-10-02T00:00:00-04:00", timedelta(hours=24), id="edt-day"),
        pytest.param(date(2026, 12, 4), "2026-12-04T00:00:00-05:00", timedelta(hours=24), id="est-day"),
        pytest.param(
            date(2026, 3, 7), "2026-03-07T00:00:00-05:00", timedelta(hours=24), id="day-before-spring"
        ),
        pytest.param(date(2026, 3, 8), "2026-03-08T00:00:00-05:00", timedelta(hours=23), id="spring-forward"),
        pytest.param(
            date(2026, 3, 9), "2026-03-09T00:00:00-04:00", timedelta(hours=24), id="day-after-spring"
        ),
        pytest.param(
            date(2026, 10, 31), "2026-10-31T00:00:00-04:00", timedelta(hours=24), id="day-before-fall"
        ),
        pytest.param(date(2026, 11, 1), "2026-11-01T00:00:00-04:00", timedelta(hours=25), id="fall-back"),
        pytest.param(
            date(2026, 11, 2), "2026-11-02T00:00:00-05:00", timedelta(hours=24), id="day-after-fall"
        ),
    ],
)
def test_eastern_midnight_starts_the_new_york_day(day, text, length):
    midnight = eastern_midnight(day)

    assert_eastern(midnight, text)
    assert eastern_midnight(day + timedelta(days=1)) - midnight == length
    assert to_eastern(midnight - MICROSECOND).date() == day - timedelta(days=1)


def test_eastern_midnight_refuses_a_day_outside_the_edt_est_era():
    assert_eastern(eastern_midnight(date(1883, 11, 19)), "1883-11-19T00:00:00-05:00")
    with pytest.raises(ValueError, match=f"^1943-06-01 {ERA}$"):
        eastern_midnight(date(1943, 6, 1))
    with pytest.raises(ValueError, match=f"^1883-11-18 {ERA}$"):
        eastern_midnight(date(1883, 11, 18))


# --- epoch milliseconds -------------------------------------------------------------------------

MIDNIGHT_MS = 1_791_172_800_000  # 2026-10-05T00:00:00-04:00


@pytest.mark.parametrize(
    ("moment", "milliseconds"),
    [
        pytest.param(utc(1970, 1, 1), 0, id="epoch"),
        pytest.param(utc(1970, 1, 1, 0, 0, 0, 999), 0, id="999-microseconds-round-down"),
        pytest.param(utc(1970, 1, 1, 0, 0, 0, 1_000), 1, id="one-millisecond"),
        pytest.param(utc(1969, 12, 31, 23, 59, 59, 999_999), -1, id="before-the-epoch-rounds-down"),
        pytest.param(utc(1969, 12, 31, 23, 59, 59, 999_000), -1, id="one-millisecond-before"),
        pytest.param(edt(2026, 10, 5), MIDNIGHT_MS, id="new-york-midnight"),
        pytest.param(utc(2026, 10, 5, 4), MIDNIGHT_MS, id="same-instant-in-utc"),
        pytest.param(ny(2026, 10, 5), MIDNIGHT_MS, id="same-instant-zoneinfo"),
        pytest.param(edt(2026, 10, 6, 5, 9, 17, 44_999), MIDNIGHT_MS + 104_957_044, id="sub-millisecond"),
        pytest.param(ny(2026, 11, 1, 1, 30), 1_793_511_000_000, id="fall-back-first"),
        pytest.param(ny(2026, 11, 1, 1, 30, fold=1), 1_793_514_600_000, id="fall-back-second"),
    ],
)
def test_epoch_ms_counts_whole_milliseconds_since_the_unix_epoch(moment, milliseconds):
    value = epoch_ms(moment)

    assert type(value) is int
    assert value == milliseconds


def test_fall_back_readings_are_one_hour_apart_in_epoch_milliseconds():
    assert epoch_ms(ny(2026, 11, 1, 1, 30, fold=1)) - epoch_ms(ny(2026, 11, 1, 1, 30)) == 3_600_000
    assert epoch_ms(eastern_midnight(date(2026, 11, 2))) - epoch_ms(eastern_midnight(date(2026, 11, 1))) == (
        25 * 3_600_000
    )


@pytest.mark.parametrize(
    ("milliseconds", "text"),
    [
        pytest.param(0, "1969-12-31T19:00:00-05:00", id="epoch"),
        pytest.param(-1, "1969-12-31T18:59:59.999000-05:00", id="before-the-epoch"),
        pytest.param(MIDNIGHT_MS, "2026-10-05T00:00:00-04:00", id="new-york-midnight"),
        pytest.param(MIDNIGHT_MS + 104_957_044, "2026-10-06T05:09:17.044000-04:00", id="milliseconds"),
        pytest.param(1_793_511_000_000, "2026-11-01T01:30:00-04:00", id="fall-back-first"),
        pytest.param(1_793_514_600_000, "2026-11-01T01:30:00-05:00", id="fall-back-second"),
        pytest.param(-2_717_650_800_000, "1883-11-18T12:00:00-05:00", id="first-est-instant"),
        pytest.param(253_402_300_799_999, "9999-12-31T18:59:59.999000-05:00", id="last-representable"),
    ],
)
def test_from_epoch_ms_is_the_new_york_instant(milliseconds, text):
    instant = from_epoch_ms(milliseconds)

    assert_eastern(instant, text)
    assert epoch_ms(instant) == milliseconds


def test_from_epoch_ms_refuses_instants_outside_the_supported_range():
    with pytest.raises(ValueError, match=f"^timestamp {ERA}$"):
        from_epoch_ms(-2_717_650_800_001)
    for milliseconds in (253_402_300_800_000, 10**20, -(10**20)):
        with pytest.raises(OverflowError):
            from_epoch_ms(milliseconds)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="bool"),
        pytest.param(1.0, id="float"),
        pytest.param(Decimal(1), id="decimal"),
        pytest.param("1791172800000", id="string"),
        pytest.param(None, id="none"),
    ],
)
def test_from_epoch_ms_takes_only_an_int(value):
    with pytest.raises(ValueError, match="^epoch milliseconds must be an int$"):
        from_epoch_ms(value)


# --- host time zone -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "zone",
    [
        # POSIX TZ strings count hours west of UTC: "EAST-14" is UTC+14.
        pytest.param("EAST-14", id="host-plus14"),
        pytest.param("WEST+12", id="host-minus12"),
        pytest.param("UTC0", id="host-utc"),
    ],
)
def test_new_york_time_does_not_depend_on_the_host_time_zone(host_time_zone, zone):
    host_time_zone(zone)

    assert et_isoformat(utc(2026, 11, 1, 6, 30)) == "2026-11-01T01:30:00-05:00"
    assert et_display(utc(2026, 10, 6, 9, 9, 17)) == "2026-10-06 05:09:17 EDT"
    assert timestamp_token(ny(2026, 11, 1, 1, 30)) == "20261101T013000EDT"
    assert parse_timestamp_token("20261101T013000EST") == utc(2026, 11, 1, 6, 30)
    assert parse_timestamp_token("20260308T023000EST") is None
    assert eastern_midnight(date(2026, 10, 5)).isoformat() == "2026-10-05T00:00:00-04:00"
    assert from_epoch_ms(MIDNIGHT_MS).isoformat() == "2026-10-05T00:00:00-04:00"
    assert epoch_ms(datetime.fromtimestamp(MIDNIGHT_MS / 1000).astimezone()) == MIDNIGHT_MS
