"""script/form4.py: an insider's Form 4 read strictly from its XML, and the officers selling.

Documents are built here in the shape of EDGAR's ownership XML (schema X0609), with the
elements the reader ignores (addresses, holdings, derivative transactions, footnotes and
signatures) beside those it reads. The owners and their CIKs are synthetic. Every refused
document raises one ``ValueError`` line naming the element and the rule, never a value read
(``PRIVATE`` stands in for one). Nothing here writes a file or uses the network.
"""

import traceback
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from market_state_research.fundamentals.script.form4 import (
    Form4,
    Owner,
    Seller,
    Transaction,
    officers_selling,
    parse_form4,
)

PRIVATE = "private-value"  # stands in for a document value that must never be echoed
ISSUER = "0000050863"
OTHER_ISSUER = "0001234567"  # a company whose shares the issuer reports as an owner
CFO = ("0001000001", "Doe Jane", "EVP and Chief Financial Officer")
CEO = ("0001000002", "Roe Richard", "Chief Executive Officer")
DIRECTOR = ("0001000003", "Poe Alex")
NOT_DECLARED = "Form 4: the XML declares a document type or an entity"


def element(tag: str, text: str | None) -> str:
    """``<tag>text</tag>``, or nothing when ``text`` is None."""
    return "" if text is None else f"<{tag}>{text}</{tag}>"


def relationship(
    director: str | None = "0",
    officer: str | None = "1",
    ten_percent: str | None = "0",
    title: str | None = CFO[2],
) -> str:
    return (
        "<reportingOwnerRelationship>"
        f"{element('isDirector', director)}{element('isOfficer', officer)}"
        f"{element('isTenPercentOwner', ten_percent)}<isOther>0</isOther>{element('officerTitle', title)}"
        "</reportingOwnerRelationship>"
    )


OFFICER = relationship()
DIRECTOR_ONLY = relationship(director="1", officer="0", title=None)


def owner(cik: str | None = CFO[0], name: str | None = CFO[1], related: str = OFFICER) -> str:
    """A ``reportingOwner``; ``related`` is its relationship element (empty: none)."""
    return (
        "<reportingOwner>"
        f"<reportingOwnerId>{element('rptOwnerCik', cik)}{element('rptOwnerName', name)}</reportingOwnerId>"
        "<reportingOwnerAddress><rptOwnerStreet1>2200 Mission College Blvd.</rptOwnerStreet1>"
        "<rptOwnerCity>Santa Clara</rptOwnerCity><rptOwnerState>CA</rptOwnerState></reportingOwnerAddress>"
        f"{related}"
        "</reportingOwner>"
    )


def value(tag: str, text: str | None) -> str:
    """``<tag><value>text</value></tag>``, or nothing when ``text`` is None."""
    return "" if text is None else f"<{tag}><value>{text}</value></{tag}>"


def transaction(
    code: str | None = "S",
    shares: str | None = "25000",
    price: str | None = "21.35",
    direction: str | None = "D",
    day: str | None = "2026-07-28",
    *,
    price_element: str | None = None,
) -> str:
    """A ``nonDerivativeTransaction``; ``price_element`` replaces the price element whole."""
    coding = (
        ""
        if code is None
        else "<transactionCoding><transactionFormType>4</transactionFormType>"
        f"<transactionCode>{code}</transactionCode><equitySwapInvolved>0</equitySwapInvolved></transactionCoding>"
    )
    price_part = value("transactionPricePerShare", price) if price_element is None else price_element
    return (
        "<nonDerivativeTransaction>"
        "<securityTitle><value>Common Stock</value></securityTitle>"
        f"{value('transactionDate', day)}{coding}"
        "<transactionAmounts>"
        f"{value('transactionShares', shares)}{price_part}"
        f"{value('transactionAcquiredDisposedCode', direction)}"
        "</transactionAmounts>"
        "<postTransactionAmounts><sharesOwnedFollowingTransaction><value>310000</value>"
        "</sharesOwnedFollowingTransaction></postTransactionAmounts>"
        "<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>"
        "</nonDerivativeTransaction>"
    )


HOLDING = (
    "<nonDerivativeHolding><securityTitle><value>Common Stock</value></securityTitle>"
    "<postTransactionAmounts><sharesOwnedFollowingTransaction><value>1200</value>"
    "</sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeHolding>"
)
DERIVATIVE = (
    "<derivativeTable><derivativeTransaction>"
    "<securityTitle><value>Restricted Stock Units</value></securityTitle>"
    "<transactionDate><value>2026-07-28</value></transactionDate>"
    "<transactionCoding><transactionFormType>4</transactionFormType><transactionCode>M</transactionCode>"
    "</transactionCoding><transactionAmounts><transactionShares><value>40000</value></transactionShares>"
    "<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>"
    "</derivativeTransaction></derivativeTable>"
)


def form4_xml(
    owners: Sequence[str] = (owner(),),
    transactions: Sequence[str] = (transaction(),),
    *,
    document_type: str | None = "4",
    period: str | None = "2026-07-28",
    issuer: str | None = ISSUER,
    root: str = "ownershipDocument",
) -> bytes:
    """A Form 4 in EDGAR's XML: the reporting ``owners`` and the non-derivative ``transactions``."""
    return (
        '<?xml version="1.0"?>\n'
        f"<{root}><schemaVersion>X0609</schemaVersion>"
        f"{element('documentType', document_type)}{element('periodOfReport', period)}"
        "<notSubjectToSection16>0</notSubjectToSection16>"
        f"<issuer>{element('issuerCik', issuer)}<issuerName>INTEL CORP</issuerName>"
        "<issuerTradingSymbol>INTC</issuerTradingSymbol></issuer>"
        f"{''.join(owners)}"
        f"<nonDerivativeTable>{''.join(transactions)}{HOLDING}</nonDerivativeTable>{DERIVATIVE}"
        '<footnotes><footnote id="F1">The price reported is a weighted average price.</footnote></footnotes>'
        "<ownerSignature><signatureName>/s/ Jane Doe</signatureName>"
        "<signatureDate>2026-07-30</signatureDate></ownerSignature>"
        f"</{root}>"
    ).encode()


def full_traceback(error: BaseException) -> str:
    return "".join(traceback.format_exception(error))


def failure(data: bytes) -> str:
    """The one-line message ``parse_form4`` refuses ``data`` with; it never echoes ``PRIVATE``."""
    with pytest.raises(ValueError) as caught:
        parse_form4(data)
    message = str(caught.value)
    assert "\n" not in message
    assert PRIVATE not in full_traceback(caught.value)
    return message


# --------------------------------------------------------------------------- reading


def test_a_form_4_is_read_as_the_strict_subset_of_its_xml():
    assert parse_form4(form4_xml()) == Form4(
        date(2026, 7, 28),
        ISSUER,
        (Owner(CFO[0], CFO[1], False, True, False, CFO[2]),),
        (Transaction(date(2026, 7, 28), "S", Decimal(25_000), Decimal("21.35"), False),),
    )


def test_a_joint_form_reads_every_owner_and_transaction_in_order():
    form = parse_form4(
        form4_xml(
            (owner(), owner(CEO[0], CEO[1], relationship(director="1", title=CEO[2]))),
            (
                transaction(),
                transaction("F", "1200.5", "21.10", "D", "2026-07-29"),
                transaction("P", "10", None, "A"),
            ),
        )
    )

    assert form.owners == (
        Owner(CFO[0], CFO[1], False, True, False, CFO[2]),
        Owner(CEO[0], CEO[1], True, True, False, CEO[2]),
    )
    assert form.transactions == (
        Transaction(date(2026, 7, 28), "S", Decimal(25_000), Decimal("21.35"), False),
        Transaction(date(2026, 7, 29), "F", Decimal("1200.5"), Decimal("21.10"), False),
        Transaction(date(2026, 7, 28), "P", Decimal(10), None, True),
    )


@pytest.mark.parametrize(
    ("written", "flag"),
    [
        pytest.param("1", True, id="one"),
        pytest.param("0", False, id="zero"),
        pytest.param("true", True, id="true"),
        pytest.param("false", False, id="false"),
        pytest.param("TRUE", True, id="true-capitals"),
        pytest.param("False", False, id="false-capital"),
        pytest.param(" 1 ", True, id="spaces"),
        pytest.param("", False, id="empty"),
        pytest.param(None, False, id="absent"),
    ],
)
def test_a_relationship_flag_is_1_0_true_or_false_and_absent_or_empty_is_false(written, flag):
    related = relationship(director=written, officer=written, ten_percent=written)

    (found,) = parse_form4(form4_xml((owner(related=related),))).owners

    assert (found.director, found.officer, found.ten_percent) == (flag, flag, flag)


def test_an_owner_without_a_relationship_is_no_director_officer_or_holder_of_ten_percent():
    (found,) = parse_form4(form4_xml((owner(DIRECTOR[0], DIRECTOR[1], ""),))).owners

    assert found == Owner(DIRECTOR[0], DIRECTOR[1], False, False, False, "")


def test_text_is_read_with_its_whitespace_collapsed():
    spaced = owner(
        f" {CFO[0]}\n", "  Doe \n Jane ", relationship(title=" EVP  and\tChief Financial Officer ")
    )

    form = parse_form4(
        form4_xml((spaced,), (transaction(" S ", " 25000 ", " 21.35 ", " D ", " 2026-07-28 "),))
    )

    assert form.owners == (Owner(CFO[0], CFO[1], False, True, False, CFO[2]),)
    assert form.transactions == (
        Transaction(date(2026, 7, 28), "S", Decimal(25_000), Decimal("21.35"), False),
    )


@pytest.mark.parametrize(
    "price",
    [
        pytest.param("", id="absent"),
        pytest.param("<transactionPricePerShare><value></value></transactionPricePerShare>", id="empty"),
        pytest.param(
            '<transactionPricePerShare><footnoteId id="F1"/></transactionPricePerShare>', id="footnote-only"
        ),
    ],
)
def test_a_price_is_optional(price):
    (found,) = parse_form4(form4_xml(transactions=(transaction(price_element=price),))).transactions

    assert found.price is None


def test_derivative_transactions_and_holdings_are_not_read():
    form = parse_form4(form4_xml(transactions=()))

    assert form.transactions == ()
    assert form.sells is False


@pytest.mark.parametrize(
    ("codes", "sells"),
    [
        pytest.param(("S",), True, id="sale"),
        pytest.param(("D",), True, id="disposition-to-the-issuer"),
        pytest.param(("P", "S"), True, id="purchase-and-sale"),
        pytest.param(("P",), False, id="purchase"),
        pytest.param(("M", "F"), False, id="exercise-and-tax-withholding"),
        pytest.param(("A", "G"), False, id="grant-and-gift"),
        pytest.param((), False, id="none"),
    ],
)
def test_a_form_sells_when_a_transaction_is_a_sale_or_a_disposition_to_the_issuer(codes, sells):
    form = parse_form4(form4_xml(transactions=tuple(transaction(code) for code in codes)))

    assert form.sells is sells


# --------------------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            b'<?xml version="1.0"?>\n<!DOCTYPE ownershipDocument SYSTEM "form4.dtd">\n' + form4_xml()[22:],
            id="doctype",
        ),
        pytest.param(b"<!doctype ownershipDocument>" + form4_xml()[22:], id="doctype-lowercase"),
        pytest.param(
            b'<!DOCTYPE lol [<!ENTITY lol "'
            + PRIVATE.encode()
            + b'">]><ownershipDocument>&lol;</ownershipDocument>',
            id="entity",
        ),
        pytest.param(
            form4_xml((owner(name="<![CDATA[<!ENTITY]]>"),)), id="declaration-anywhere-in-the-bytes"
        ),
    ],
)
def test_a_document_type_or_entity_declaration_is_refused_before_parsing(data):
    assert failure(data) == NOT_DECLARED


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(b"", "no element found: line 1, column 0", id="empty"),
        pytest.param(b"<ownershipDocument>", "no element found: line 1, column 19", id="unclosed"),
        pytest.param(b"<ownershipDocument></issuer>", "mismatched tag: line 1, column 21", id="mismatched"),
        pytest.param(PRIVATE.encode(), "syntax error: line 1, column 0", id="text"),
    ],
)
def test_xml_that_is_not_well_formed_is_refused(data, message):
    assert failure(data) == f"Form 4: the XML is not well-formed: {message}"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(
            form4_xml(root="edgarSubmission"), "Form 4: the root element must be ownershipDocument", id="root"
        ),
        pytest.param(form4_xml(document_type=None), "Form 4: documentType is missing", id="no-document-type"),
        pytest.param(form4_xml(document_type="4/A"), "Form 4: documentType must be 4", id="amendment"),
        pytest.param(
            form4_xml(document_type=PRIVATE), "Form 4: documentType must be 4", id="other-document-type"
        ),
        pytest.param(form4_xml(period=None), "Form 4: periodOfReport is missing", id="no-period"),
        pytest.param(
            form4_xml(period="07/28/2026"),
            "Form 4: periodOfReport must be a YYYY-MM-DD date",
            id="period-format",
        ),
        pytest.param(
            form4_xml(period=PRIVATE), "Form 4: periodOfReport must be a YYYY-MM-DD date", id="period-text"
        ),
        pytest.param(
            form4_xml(period="2026-02-30"),
            "Form 4: periodOfReport is not a date that exists",
            id="period-no-day",
        ),
        pytest.param(form4_xml(issuer=None), "Form 4: issuer/issuerCik is missing", id="no-issuer"),
        pytest.param(
            form4_xml(issuer="50863"), "Form 4: issuer/issuerCik must be ten digits", id="issuer-short"
        ),
        pytest.param(
            form4_xml(issuer=PRIVATE), "Form 4: issuer/issuerCik must be ten digits", id="issuer-text"
        ),
        pytest.param(form4_xml(owners=()), "Form 4: no reportingOwner", id="no-owner"),
        pytest.param(
            form4_xml((owner(cik=None),)),
            "Form 4: reportingOwner 1: reportingOwnerId/rptOwnerCik is missing",
            id="no-owner-cik",
        ),
        pytest.param(
            form4_xml((owner(), owner(cik=PRIVATE))),
            "Form 4: reportingOwner 2: rptOwnerCik must be ten digits",
            id="second-owner-cik",
        ),
        pytest.param(
            form4_xml((owner(name=None),)),
            "Form 4: reportingOwner 1: reportingOwnerId/rptOwnerName is missing",
            id="no-owner-name",
        ),
        pytest.param(
            form4_xml((owner(name=" "),)),
            "Form 4: reportingOwner 1: rptOwnerName must be 1 to 200 printable characters",
            id="blank-owner-name",
        ),
        pytest.param(
            form4_xml((owner(name="x" * 201),)),
            "Form 4: reportingOwner 1: rptOwnerName must be 1 to 200 printable characters",
            id="long-owner-name",
        ),
        pytest.param(
            form4_xml((owner(related=relationship(title="x" * 201)),)),
            "Form 4: reportingOwner 1: officerTitle must be at most 200 printable characters",
            id="long-title",
        ),
        pytest.param(
            form4_xml((owner(related=relationship(director="yes")),)),
            "Form 4: reportingOwner 1: isDirector must be 1, 0, true or false",
            id="director-flag",
        ),
        pytest.param(
            form4_xml((owner(related=relationship(officer=PRIVATE)),)),
            "Form 4: reportingOwner 1: isOfficer must be 1, 0, true or false",
            id="officer-flag",
        ),
        pytest.param(
            form4_xml((owner(related=relationship(ten_percent="2")),)),
            "Form 4: reportingOwner 1: isTenPercentOwner must be 1, 0, true or false",
            id="ten-percent-flag",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(day=None),)),
            "Form 4: nonDerivativeTransaction 1: transactionDate/value is missing",
            id="no-date",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(), transaction(day=PRIVATE))),
            "Form 4: nonDerivativeTransaction 2: transactionDate must be a YYYY-MM-DD date",
            id="second-date",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(day="2026-13-01"),)),
            "Form 4: nonDerivativeTransaction 1: transactionDate is not a date that exists",
            id="date-no-day",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(code=None),)),
            "Form 4: nonDerivativeTransaction 1: transactionCoding/transactionCode is missing",
            id="no-code",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(code="s"),)),
            "Form 4: nonDerivativeTransaction 1: transactionCode must be one capital letter",
            id="code-lowercase",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(code="SD"),)),
            "Form 4: nonDerivativeTransaction 1: transactionCode must be one capital letter",
            id="code-two-letters",
        ),
        pytest.param(
            form4_xml(
                transactions=(
                    "<nonDerivativeTransaction><transactionDate><value>2026-07-28</value></transactionDate>"
                    "<transactionCoding><transactionCode>S</transactionCode></transactionCoding>"
                    "</nonDerivativeTransaction>",
                )
            ),
            "Form 4: nonDerivativeTransaction 1: transactionAmounts is missing",
            id="no-amounts",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(shares=None),)),
            "Form 4: nonDerivativeTransaction 1: transactionShares/value is missing",
            id="no-shares",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(shares=PRIVATE),)),
            "Form 4: nonDerivativeTransaction 1: transactionShares must be a decimal number",
            id="shares-text",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(shares="-5"),)),
            "Form 4: nonDerivativeTransaction 1: transactionShares must be a decimal number not below 0",
            id="shares-negative",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(shares="NaN"),)),
            "Form 4: nonDerivativeTransaction 1: transactionShares must be a decimal number not below 0",
            id="shares-nan",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(price="Infinity"),)),
            "Form 4: nonDerivativeTransaction 1: transactionPricePerShare must be a decimal number not "
            "below 0",
            id="price-infinite",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(price=PRIVATE),)),
            "Form 4: nonDerivativeTransaction 1: transactionPricePerShare must be a decimal number",
            id="price-text",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(direction=None),)),
            "Form 4: nonDerivativeTransaction 1: transactionAcquiredDisposedCode/value is missing",
            id="no-direction",
        ),
        pytest.param(
            form4_xml(transactions=(transaction(direction=PRIVATE),)),
            "Form 4: nonDerivativeTransaction 1: transactionAcquiredDisposedCode must be A or D",
            id="direction-text",
        ),
    ],
)
def test_a_document_breaking_the_subset_is_refused_naming_the_element(data, message):
    assert failure(data) == message


# --------------------------------------------------------------------------- officers selling


def form(*owners: str, codes: Sequence[str] = ("S",), issuer: str = ISSUER) -> Form4:
    return parse_form4(form4_xml(owners, tuple(transaction(code) for code in codes), issuer=issuer))


CFO_OWNER = owner()
CEO_OWNER = owner(CEO[0], CEO[1], relationship(title=CEO[2]))
DIRECTOR_OWNER = owner(DIRECTOR[0], DIRECTOR[1], DIRECTOR_ONLY)
HOLDER_OWNER = owner(
    "0001000004", "Example Holdings LLC", relationship(officer="0", ten_percent="1", title=None)
)


def test_officers_selling_are_the_distinct_officers_in_cik_order():
    forms = [
        ("0000050863-26-000180", form(CEO_OWNER)),
        ("0000050863-26-000177", form(CFO_OWNER)),
        ("0000050863-26-000181", form(CEO_OWNER, codes=("D",))),
    ]

    assert officers_selling(forms, ISSUER) == (
        Seller(CFO[0], CFO[1], CFO[2], ("0000050863-26-000177",)),
        Seller(CEO[0], CEO[1], CEO[2], ("0000050863-26-000180", "0000050863-26-000181")),
    )


def test_an_accession_is_named_once_per_officer():
    forms = [("0000050863-26-000177", form(CFO_OWNER)), ("0000050863-26-000177", form(CFO_OWNER))]

    assert officers_selling(forms, ISSUER) == (Seller(CFO[0], CFO[1], CFO[2], ("0000050863-26-000177",)),)


def test_directors_and_holders_who_are_no_officers_are_left_out():
    forms = [
        ("0000050863-26-000182", form(DIRECTOR_OWNER)),
        ("0000050863-26-000183", form(HOLDER_OWNER)),
        ("0000050863-26-000184", form(DIRECTOR_OWNER, CFO_OWNER)),
    ]

    assert officers_selling(forms, ISSUER) == (Seller(CFO[0], CFO[1], CFO[2], ("0000050863-26-000184",)),)


@pytest.mark.parametrize(
    ("codes", "counted"),
    [
        pytest.param(("S",), True, id="sale"),
        pytest.param(("D",), True, id="disposition-to-the-issuer"),
        pytest.param(("M", "S"), True, id="exercise-and-sale"),
        pytest.param(("F",), False, id="tax-withholding"),
        pytest.param(("P",), False, id="purchase"),
        pytest.param(("A", "M", "G"), False, id="grant-exercise-gift"),
        pytest.param((), False, id="no-transaction"),
    ],
)
def test_only_a_sale_or_a_disposition_to_the_issuer_counts(codes, counted):
    sellers = officers_selling([("0000050863-26-000177", form(CFO_OWNER, codes=codes))], ISSUER)

    assert len(sellers) == (1 if counted else 0)


def test_a_form_of_another_issuer_is_left_out():
    forms = [
        ("0000050863-26-000190", form(CFO_OWNER, issuer=OTHER_ISSUER)),
        ("0000050863-26-000177", form(CEO_OWNER)),
    ]

    assert officers_selling(forms, ISSUER) == (Seller(CEO[0], CEO[1], CEO[2], ("0000050863-26-000177",)),)
    assert officers_selling(forms, OTHER_ISSUER) == (
        Seller(CFO[0], CFO[1], CFO[2], ("0000050863-26-000190",)),
    )


def test_no_form_no_seller():
    assert officers_selling([], ISSUER) == ()
