"""An insider's Form 4, read strictly from the XML EDGAR keeps of it.

Pure. A Form 4 reports an insider's changes in their holdings of an issuer's securities.
EDGAR lists its primary document as a rendering (``xslF345X06/form4.xml``) of an XML file
in the filing's folder (``form4.xml``), which ``fetch`` writes as served
(``filings.rendered_document``). The subset read, verified on Intel's Form 4
0000050863-26-000177 (schema ``X0609``):

- ``ownershipDocument`` with ``documentType`` ``4`` and ``periodOfReport``
  (``YYYY-MM-DD``, the earliest transaction);
- ``issuer/issuerCik``: whose securities are reported, ten digits. An issuer may file a
  Form 4 of its own as the owner of another issuer's shares, which its submissions list
  too: such a form is another issuer's;
- per ``reportingOwner``: ``reportingOwnerId/rptOwnerCik`` (ten digits) and
  ``rptOwnerName``, and ``reportingOwnerRelationship`` (``isDirector``, ``isOfficer``,
  ``isTenPercentOwner``, each ``1``, ``0``, ``true`` or ``false`` when present, and
  ``officerTitle``);
- per ``nonDerivativeTable/nonDerivativeTransaction``: ``transactionDate/value``,
  ``transactionCoding/transactionCode`` (one letter), and in ``transactionAmounts``
  ``transactionShares/value``, ``transactionPricePerShare/value`` (a decimal, empty or
  absent) and ``transactionAcquiredDisposedCode/value`` (``A`` or ``D``).

Every other element is ignored; a document type or entity declaration is refused before
parsing, so no entity is expanded. Every problem is one ``ValueError`` line naming the
element and the rule, never a value read. ``officers_selling`` gives the distinct officers
of the issuer who report an open-market or private sale (code ``S``) or a disposition to the
issuer (code ``D``) among a season's forms.
"""

import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final

SALE_CODES: Final = ("S", "D")
_CIK = re.compile(r"[0-9]{10}", re.ASCII)
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_CODE = re.compile(r"[A-Z]", re.ASCII)
_FLAGS: Final = {"1": True, "true": True, "0": False, "false": False}
MAX_NAME: Final = 200


@dataclass(frozen=True)
class Owner:
    """One reporting owner: CIK, name and relationship to the issuer."""

    cik: str
    name: str
    director: bool
    officer: bool
    ten_percent: bool
    title: str


@dataclass(frozen=True)
class Transaction:
    """One non-derivative transaction: its date, code, shares, price (None when not given) and
    whether the shares were acquired (``A``) or disposed of (``D``)."""

    day: date
    code: str
    shares: Decimal
    price: Decimal | None
    acquired: bool


@dataclass(frozen=True)
class Form4:
    """A Form 4 read strictly: the period it reports, the issuer's CIK, its owners and its
    non-derivative transactions."""

    period: date
    issuer: str
    owners: tuple[Owner, ...]
    transactions: tuple[Transaction, ...]

    @property
    def sells(self) -> bool:
        """Whether a transaction is a sale (``S``) or a disposition to the issuer (``D``)."""
        return any(transaction.code in SALE_CODES for transaction in self.transactions)


def _text(element: ElementTree.Element | None) -> str:
    return "" if element is None else " ".join((element.text or "").split())


def _required(parent: ElementTree.Element, path: str, where: str) -> str:
    found = parent.find(path)
    if found is None:
        raise ValueError(f"{where}: {path} is missing")
    return _text(found)


def _day(text: str, where: str) -> date:
    if not _DAY.fullmatch(text):
        raise ValueError(f"{where} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{where} is not a date that exists") from None


def _decimal(text: str, where: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{where} must be a decimal number") from None
    if not value.is_finite() or value < 0:
        raise ValueError(f"{where} must be a decimal number not below 0")
    return value


def _flag(relationship: ElementTree.Element | None, name: str, where: str) -> bool:
    text = _text(None if relationship is None else relationship.find(name))
    if not text:
        return False
    if text.lower() not in _FLAGS:
        raise ValueError(f"{where}: {name} must be 1, 0, true or false")
    return _FLAGS[text.lower()]


def _owner(element: ElementTree.Element, number: int) -> Owner:
    where = f"Form 4: reportingOwner {number}"
    cik = _required(element, "reportingOwnerId/rptOwnerCik", where)
    if not _CIK.fullmatch(cik):
        raise ValueError(f"{where}: rptOwnerCik must be ten digits")
    name = _required(element, "reportingOwnerId/rptOwnerName", where)
    if not 0 < len(name) <= MAX_NAME or not name.isprintable():
        raise ValueError(f"{where}: rptOwnerName must be 1 to {MAX_NAME} printable characters")
    relationship = element.find("reportingOwnerRelationship")
    title = _text(None if relationship is None else relationship.find("officerTitle"))
    if len(title) > MAX_NAME or not title.isprintable():
        raise ValueError(f"{where}: officerTitle must be at most {MAX_NAME} printable characters")
    return Owner(
        cik=cik,
        name=name,
        director=_flag(relationship, "isDirector", where),
        officer=_flag(relationship, "isOfficer", where),
        ten_percent=_flag(relationship, "isTenPercentOwner", where),
        title=title,
    )


def _transaction(element: ElementTree.Element, number: int) -> Transaction:
    where = f"Form 4: nonDerivativeTransaction {number}"
    day = _day(_required(element, "transactionDate/value", where), f"{where}: transactionDate")
    code = _required(element, "transactionCoding/transactionCode", where)
    if not _CODE.fullmatch(code):
        raise ValueError(f"{where}: transactionCode must be one capital letter")
    amounts = element.find("transactionAmounts")
    if amounts is None:
        raise ValueError(f"{where}: transactionAmounts is missing")
    shares = _decimal(_required(amounts, "transactionShares/value", where), f"{where}: transactionShares")
    price_text = _text(amounts.find("transactionPricePerShare/value"))
    price = _decimal(price_text, f"{where}: transactionPricePerShare") if price_text else None
    direction = _required(amounts, "transactionAcquiredDisposedCode/value", where)
    if direction not in ("A", "D"):
        raise ValueError(f"{where}: transactionAcquiredDisposedCode must be A or D")
    return Transaction(day, code, shares, price, direction == "A")


def parse_form4(data: bytes) -> Form4:
    """The Form 4 XML ``data`` read as the strict subset of the module docstring."""
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("Form 4: the XML declares a document type or an entity")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError(f"Form 4: the XML is not well-formed: {error}") from None
    if root.tag != "ownershipDocument":
        raise ValueError("Form 4: the root element must be ownershipDocument")
    if _required(root, "documentType", "Form 4") != "4":
        raise ValueError("Form 4: documentType must be 4")
    period = _day(_required(root, "periodOfReport", "Form 4"), "Form 4: periodOfReport")
    issuer = _required(root, "issuer/issuerCik", "Form 4")
    if not _CIK.fullmatch(issuer):
        raise ValueError("Form 4: issuer/issuerCik must be ten digits")
    owners = tuple(
        _owner(element, number) for number, element in enumerate(root.findall("reportingOwner"), 1)
    )
    if not owners:
        raise ValueError("Form 4: no reportingOwner")
    transactions = tuple(
        _transaction(element, number)
        for number, element in enumerate(root.findall("nonDerivativeTable/nonDerivativeTransaction"), 1)
    )
    return Form4(period, issuer, owners, transactions)


@dataclass(frozen=True)
class Seller:
    """An officer of the issuer who reports a sale or a disposition in a season's Form 4s."""

    cik: str
    name: str
    title: str
    accessions: tuple[str, ...]


def officers_selling(forms: Iterable[tuple[str, Form4]], issuer: str) -> tuple[Seller, ...]:
    """The distinct officers of ``issuer`` (by CIK) reporting a transaction with code ``S`` or ``D``
    among ``forms`` (accession, form), in CIK order; a form of another issuer is left out."""
    found: dict[str, tuple[Owner, list[str]]] = {}
    for accession, form in forms:
        if form.issuer != issuer or not form.sells:
            continue
        for owner in form.owners:
            if owner.officer:
                held = found.setdefault(owner.cik, (owner, []))
                if accession not in held[1]:
                    held[1].append(accession)
    return tuple(
        Seller(cik, owner.name, owner.title, tuple(accessions))
        for cik, (owner, accessions) in sorted(found.items())
    )
