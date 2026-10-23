"""script/text.py: derived text of HTML, plain text and XML.

Quote normalisation and location are covered by ``test_quotes.py``. Everything here is
pure string work: nothing touches the filesystem or the network.
"""

import random
import unicodedata

import pytest

from market_state_research.fundamentals.script.text import (
    html_text,
    plain_text,
    windows_1252,
    xml_text,
)

LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}
INVISIBLE = {
    "soft-hyphen": "\u00ad",
    "zero-width-space": "\u200b",
    "zero-width-non-joiner": "\u200c",
    "zero-width-joiner": "\u200d",
    "word-joiner": "\u2060",
    "byte-order-mark": "\ufeff",
}
# Every character str.splitlines() ends a line at.
LINE_ENDS = {
    "crlf": "\r\n",
    "cr": "\r",
    "lf": "\n",
    "vertical-tab": "\v",
    "form-feed": "\f",
    "file-separator": "\x1c",
    "group-separator": "\x1d",
    "record-separator": "\x1e",
    "next-line": "\x85",
    "line-separator": "\u2028",
    "paragraph-separator": "\u2029",
}
# Whitespace inside a line that str.split() collapses.
SPACES = {
    "tab": "\t",
    "unit-separator": "\x1f",
    "no-break-space": "\u00a0",
    "ogham-space": "\u1680",
    "en-quad": "\u2000",
    "figure-space": "\u2007",
    "thin-space": "\u2009",
    "hair-space": "\u200a",
    "narrow-no-break-space": "\u202f",
    "medium-mathematical-space": "\u205f",
    "ideographic-space": "\u3000",
}

# Elements whose subtree derived text drops.
HIDDEN_TAGS = ["script", "style", "head", "title", "noscript", "template", "ix:header"]
# The block elements with an end tag (br and hr are void elements).
BLOCK_TAGS = (
    ["address", "article", "aside", "blockquote", "body", "caption", "center", "dd", "div", "dl", "dt"]
    + ["fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header"]
    + ["html", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "tfoot", "thead", "tr"]
    + ["ul"]
)


def assert_derived_shape(text: str) -> None:
    """Derived text: only " " and "\\n" as whitespace, trimmed non-empty lines, one final "\\n"."""
    assert all(character in " \n" for character in text if character.isspace())
    if text:
        assert text.endswith("\n")
        lines = text[:-1].split("\n")
        assert all(line and line == line.strip(" ") and "  " not in line for line in lines)
    for character in [*INVISIBLE.values(), *LIGATURES]:
        assert character not in text


# --------------------------------------------------------------------------- plain text


@pytest.mark.parametrize("end", list(LINE_ENDS.values()), ids=list(LINE_ENDS))
def test_plain_text_splits_lines_at_every_line_end(end):
    assert plain_text(f"first line{end}second line{end}") == "first line\nsecond line\n"


def test_plain_text_mixed_line_ends_never_leave_a_carriage_return():
    text = plain_text("one\r\ntwo\rthree\nfour\u2028five\r\n\r\n")
    assert text == "one\ntwo\nthree\nfour\nfive\n"
    assert "\r" not in text


@pytest.mark.parametrize("space", list(SPACES.values()), ids=list(SPACES))
def test_plain_text_collapses_unicode_spaces_inside_a_line(space):
    assert plain_text(f"{space}Q2{space}{space}2026 {space} revenue{space}") == "Q2 2026 revenue\n"


def test_plain_text_trims_lines_and_drops_empty_ones():
    assert (
        plain_text("  \n\n  Prepared   remarks \n \t \n\nfor the  call\n\n")
        == "Prepared remarks\nfor the call\n"
    )


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("", id="empty"),
        pytest.param(" \t\n\r\n\u2028\u00a0", id="whitespace"),
        pytest.param("\u00ad\u200b\n\ufeff", id="invisible-characters"),
    ],
)
def test_plain_text_without_text_is_empty(body):
    assert plain_text(body) == ""


@pytest.mark.parametrize("character", list(INVISIBLE.values()), ids=list(INVISIBLE))
def test_plain_text_removes_soft_hyphens_and_zero_width_characters(character):
    assert plain_text(f"manu{character}facturing{character} capacity {character}") == (
        "manufacturing capacity\n"
    )


@pytest.mark.parametrize(("ligature", "expansion"), list(LIGATURES.items()), ids=list(LIGATURES.values()))
def test_plain_text_expands_ligatures_as_nfkc_does(ligature, expansion):
    assert unicodedata.normalize("NFKC", ligature) == expansion
    assert plain_text(f"a{ligature}b") == f"a{expansion}b\n"


def test_plain_text_folds_nothing_else():
    original = "Intel’s “AI” PCs – 3rd quarter — café Ｑ２ ² ½ ŉ Straße"
    assert plain_text(original) == original + "\n"


def test_plain_text_is_deterministic_and_idempotent():
    body = "  Intel\u00a0Foundry\r\n\r\n\ufb01nance\u2028done "
    assert plain_text(body) == plain_text(body) == "Intel Foundry\nfinance\ndone\n"
    assert plain_text(plain_text(body)) == plain_text(body)


# --------------------------------------------------------------------------- HTML: hidden subtrees


@pytest.mark.parametrize("tag", HIDDEN_TAGS)
def test_html_drops_hidden_elements(tag):
    assert html_text(f"<p>before</p><{tag}>secret</{tag}><p>after</p>") == "before\nafter\n"


@pytest.mark.parametrize("tag", HIDDEN_TAGS)
def test_html_hidden_tags_match_in_any_case(tag):
    upper = tag.upper()
    assert html_text(f"<P>before</P><{upper}>secret <b>more</b></{upper}><P>after</P>") == "before\nafter\n"


@pytest.mark.parametrize(
    "attribute",
    [
        pytest.param('style="display:none"', id="compact"),
        pytest.param('style="DISPLAY: NONE"', id="upper-case"),
        pytest.param("style='Display :None'", id="mixed-case-single-quotes"),
        pytest.param('style="color: red; display :\tnone ; margin: 0"', id="among-declarations"),
        pytest.param('style="display\n:\n none !important"', id="line-breaks-important"),
        pytest.param("style=display:none", id="unquoted"),
        pytest.param('STYLE="display:none"', id="upper-case-attribute"),
        pytest.param('style="display&#58;none"', id="character-reference"),
        pytest.param('class="x" style="display:block" style="display:none"', id="second-style"),
    ],
)
def test_html_drops_elements_styled_display_none(attribute):
    assert html_text(f"<p>before</p><div {attribute}>secret<p>nested</p></div><p>after</p>") == (
        "before\nafter\n"
    )


@pytest.mark.parametrize(
    "attribute",
    [
        pytest.param('style="display:block"', id="display-block"),
        pytest.param('style="visibility:hidden"', id="visibility"),
        pytest.param('style="font-weight:bold"', id="other-style"),
        pytest.param("style", id="no-value"),
        pytest.param('style=""', id="empty-value"),
        pytest.param('data-style="display:none"', id="other-attribute"),
        pytest.param('title="display:none"', id="title-attribute"),
    ],
)
def test_html_keeps_elements_not_styled_display_none(attribute):
    assert html_text(f"<div {attribute}>shown</div>") == "shown\n"


def test_html_nested_hidden_subtrees_stay_hidden_until_the_outer_one_closes():
    body = (
        "<p>start</p>"
        '<div style="display:none">a<script>b</script>c<div style="display:none">d</div>e'
        "<template><p>f</p></template>g<span>h</span></div>"
        "<p>end</p>"
    )
    assert html_text(body) == "start\nend\n"


def test_html_closing_a_hidden_child_does_not_reveal_its_hidden_parent():
    assert (
        html_text("<head><title>Form 10-K</title>still head<style>p{}</style></head><body>x</body>") == "x\n"
    )


def test_html_inline_xbrl_header_is_hidden_and_inline_facts_are_text():
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">'
        "<head><title>intc-20251227</title></head><body>"
        '<div style="display:none"><ix:header><ix:hidden>'
        '<ix:nonNumeric name="dei:AmendmentFlag" contextRef="c-1">false</ix:nonNumeric>'
        "</ix:hidden><ix:resources>context</ix:resources></ix:header></div>"
        '<div><span>Registrant: </span><ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-1">'
        "INTEL CORPORATION</ix:nonNumeric></div>"
        '<div>Net revenue was $<ix:nonFraction name="us-gaap:Revenues" scale="6">53,101</ix:nonFraction>'
        " million.</div></body></html>"
    )
    assert html_text(body) == "Registrant: INTEL CORPORATION\nNet revenue was $53,101 million.\n"


def test_html_hidden_element_emits_no_line_break():
    # A hidden element generates no box: the words around it join as the page shows them.
    assert html_text('net<div style="display:none">hidden</div>work') == "network\n"
    assert html_text('<p>one</p><div style="display:none"><p>x</p></div><p>two</p>') == "one\ntwo\n"


def test_html_text_after_an_unclosed_hidden_element_is_hidden():
    assert html_text('<p>shown</p><div style="display:none">hidden<p>still hidden') == "shown\n"
    assert html_text("<p>shown</p><script>var x = 1;") == "shown\n"
    assert html_text("<p>shown</p><title>never closed") == "shown\n"


def test_html_script_and_style_content_is_raw_text():
    body = (
        '<script>if (a < b) { document.write("<p>fake</p>"); }</script><style>p::after{content:"x"}</style>ok'
    )
    assert html_text(body) == "ok\n"


def test_html_drops_comments_declarations_and_processing_instructions():
    body = "<!DOCTYPE html><?xml version='1.0'?><!-- a note --><![CDATA[raw]]><p>text</p><!-- unterminated"
    assert html_text(body) == "text\n"


# --------------------------------------------------------------------------- HTML: structure


def test_html_blocks_break_lines_and_inline_elements_do_not():
    body = (
        "<html><body><h1>Item 1. Business</h1><div>Total <b>net</b> <i>revenue</i>: "
        '<span>$53.1</span><a href="#n1">billion</a>.</div>'
        "<ul><li>Client Computing</li><li>Data Center and AI</li></ul>"
        "<p>One<span>word</span></p><section><article>nested</article></section></body></html>"
    )
    assert html_text(body) == (
        "Item 1. Business\nTotal net revenue: $53.1billion.\nClient Computing\nData Center and AI\n"
        "Oneword\nnested\n"
    )


@pytest.mark.parametrize("tag", BLOCK_TAGS)
def test_html_every_block_element_breaks_lines(tag):
    assert html_text(f"a<{tag}>b</{tag}>c") == "a\nb\nc\n"


@pytest.mark.parametrize("tag", ["span", "b", "i", "a", "em", "strong", "font", "sup", "ix:nonnumeric", "u"])
def test_html_inline_elements_join_text(tag):
    assert html_text(f"a<{tag}>b</{tag}>c") == "abc\n"


def test_html_table_cells_are_separated_by_a_space_and_rows_by_a_line():
    body = (
        "<table><thead><tr><th>Segment</th><th>Revenue</th></tr></thead>"
        "<tbody><tr><td>Client Computing Group</td><td>$</td><td>7,948</td></tr>"
        "<tr><td>Intel Foundry</td><td></td><td>4,417</td></tr></tbody></table>"
    )
    assert html_text(body) == "Segment Revenue\nClient Computing Group $ 7,948\nIntel Foundry 4,417\n"


def test_html_source_whitespace_is_a_single_space_never_a_line():
    body = "<p>line one\n   continues\there\r\nand\u2028here</p><pre>a\n\n  b</pre>"
    assert html_text(body) == "line one continues here and here\na b\n"


def test_html_void_elements_are_never_opened():
    body = '<p>a<br>b<img src="x.png" alt="logo">c<hr>d<input value="v">e<wbr>f</p>g'
    assert html_text(body) == "a\nbc\ndef\ng\n"
    # A void element's display:none hides nothing after it.
    assert html_text('<meta style="display:none">visible<link style="display:none">too') == "visibletoo\n"


VOID_TAGS = ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source")
VOID_TAGS += ("track", "wbr")


@pytest.mark.parametrize("tag", VOID_TAGS)
def test_html_a_hidden_void_element_hides_nothing_after_it(tag):
    """A void element has no content: styled display:none, it must not hide the rest of its parent
    (and a hidden ``br`` or ``hr`` breaks no line)."""
    assert html_text(f'<p>a<{tag} style="display:none">b</p>c') == "ab\nc\n"
    assert html_text(f'<p>a<{tag.upper()} STYLE="Display: None">b</p>c') == "ab\nc\n"


def test_html_self_closing_tags_are_never_opened():
    assert html_text('<div style="display:none"/>visible') == "visible\n"
    assert html_text("<script/>visible<title/>too") == "visibletoo\n"
    assert html_text("a<br/>b<hr />c<span/>d<p/>e") == "a\nb\ncd\ne\n"


def test_html_unmatched_end_tags_are_ignored():
    assert html_text("</div>a</p>b</span>c</script>d</br>e") == "abcde\n"
    assert html_text("<div>a</span>b</div>") == "ab\n"


def test_html_end_tag_closes_every_element_opened_inside_it():
    assert html_text('<div style="display:none"><span><b>hidden</div>visible') == "visible\n"
    assert html_text("<b><i>x</b>y</i>z") == "xyz\n"


def test_html_unclosed_elements_extend_to_the_end():
    assert html_text("<p>one<p>two<div>three<td>four") == "one\ntwo\nthree four\n"


def test_html_tag_names_are_case_insensitive():
    assert html_text("<DIV>a</div><P>b</P><Td>c</tD><TD>d</td>") == "a\nb\nc d\n"


# --------------------------------------------------------------------------- HTML: characters


@pytest.mark.parametrize(
    ("reference", "character"),
    [
        pytest.param("&amp;", "&", id="amp"),
        pytest.param("&lt;", "<", id="lt"),
        pytest.param("&gt;", ">", id="gt"),
        pytest.param("&quot;", '"', id="quot"),
        pytest.param("&#39;", "'", id="decimal-apostrophe"),
        pytest.param("&rsquo;", "\u2019", id="rsquo"),
        pytest.param("&#8217;", "\u2019", id="decimal-rsquo"),
        pytest.param("&#x2019;", "\u2019", id="hex-rsquo"),
        pytest.param("&ndash;", "\u2013", id="ndash"),
        pytest.param("&mdash;", "\u2014", id="mdash"),
        pytest.param("&copy;", "\u00a9", id="copy"),
        pytest.param("&reg;", "\u00ae", id="reg"),
        pytest.param("&#x1F600;", "\U0001f600", id="astral"),
        pytest.param("&amp", "&", id="no-semicolon"),
    ],
)
def test_html_character_references_become_their_characters(reference, character):
    assert html_text(f"<p>x{reference}y</p>") == f"x{character}y\n"


# The bytes 0x80-0x9F as windows-1252 reads them; the five it leaves undefined stay as Latin-1 gives them.
WINDOWS_1252 = "€\x81‚ƒ„…†‡ˆ‰Š‹Œ\x8dŽ\x8f\x90‘’“”•–—˜™š›œ\x9džŸ"


def test_windows_1252_reads_latin_1_text_as_a_browser_does():
    latin_1 = bytes(range(0x80, 0xA0)).decode("latin-1")
    assert windows_1252(latin_1) == WINDOWS_1252
    assert len(WINDOWS_1252) == 32 and WINDOWS_1252[0x0D] == "\x8d"
    # Exactly the C1 controls change: ASCII, Latin-1's letters and everything beyond are kept.
    kept = "".join(map(chr, [*range(0x80), *range(0xA0, 0x100)])) + "’–…中\U0001f600"
    assert windows_1252(kept) == kept
    # As the numeric references of those bytes already read.
    assert html_text("<p>Intel&#146;s foundry &#150; wafer supply&#133;</p>") == (
        html_text(windows_1252("<p>Intel\x92s foundry \x96 wafer supply\x85</p>"))
    )


def test_html_text_that_only_looks_like_a_reference_is_kept():
    assert html_text("<p>AT&T &bogus; 5 &lt 6 & 7</p>") == "AT&T &bogus; 5 < 6 & 7\n"


@pytest.mark.parametrize(
    "space",
    ["&nbsp;", "&#160;", "&#xA0;", "\u00a0", "&ensp;", "&emsp;", "&thinsp;", "&#x202F;", "&#x3000;", "\t"],
)
def test_html_no_break_and_unicode_spaces_are_ordinary_spaces(space):
    assert html_text(f"<p>Q2{space}{space}2026{space}</p>") == "Q2 2026\n"


@pytest.mark.parametrize(
    "invisible", ["&shy;", "&#173;", "&#8203;", "&zwnj;", "&zwj;", "&#x2060;", "&#xFEFF;", "\u00ad", "\u200b"]
)
def test_html_soft_hyphens_and_zero_width_characters_are_removed(invisible):
    assert html_text(f"<p>manu{invisible}facturing {invisible}capacity</p>") == "manufacturing capacity\n"


def test_html_leading_byte_order_mark_is_removed():
    assert html_text("\ufeff<html><body>text</body></html>") == "text\n"


@pytest.mark.parametrize(("ligature", "expansion"), list(LIGATURES.items()), ids=list(LIGATURES.values()))
def test_html_ligatures_are_expanded(ligature, expansion):
    reference = f"&#x{ord(ligature):X};"
    assert html_text(f"<p>a{ligature}b a{reference}b</p>") == f"a{expansion}b a{expansion}b\n"


# --------------------------------------------------------------------------- HTML: robustness


@pytest.mark.parametrize(
    ("body", "text"),
    [
        pytest.param("", "", id="empty"),
        pytest.param("plain words", "plain words\n", id="no-markup"),
        pytest.param("<", "<\n", id="lone-open"),
        pytest.param("a < b > c", "a < b > c\n", id="comparison"),
        pytest.param("</>x", "x\n", id="empty-end-tag"),
        pytest.param("<p", "", id="unterminated-start-tag"),
        pytest.param("x<div style=", "x\n", id="unterminated-attribute"),
        pytest.param("x<!--", "x\n", id="unterminated-comment"),
        pytest.param("x<![CDATA[", "x\n", id="unterminated-cdata"),
        pytest.param("x&#", "x&#\n", id="unterminated-numeric-reference"),
        pytest.param("x&#x", "x&#x\n", id="unterminated-hex-reference"),
        pytest.param("<a href='x>text", "", id="unterminated-quote"),
        pytest.param("</ div>x", "x\n", id="space-in-end-tag"),
        pytest.param("<p>\x00</p>", "\x00\n", id="nul"),
        pytest.param("<<<>>>", "<<<>>>\n", id="brackets"),
    ],
)
def test_html_malformed_markup_never_raises(body, text):
    assert html_text(body) == text


def test_html_random_markup_never_raises_and_keeps_the_derived_shape():
    pieces = (
        ["<", ">", "</", "/>", "<!", "<!--", "-->", "<?", "<![CDATA[", "]]>", "&", "&#", "&#x", ";", "&amp"]
        + ["<p", '<div style="display:none"', "</div", "<script>", "</script>", "<title>", "<textarea>"]
        + ["<plaintext>", '"', "'", "=", " ", "\n", "\r", "a", "\u00e9", "\u00ad", "\u2028", "\x00", "<br"]
        + ["<td>", "<ix:header>", "</ix:header>", "<head>", "<!DOCTYPE", "x", "<style", "</style>"]
        + ['<a b="&#1;">', "\ufb01", "\u00a0"]
    )
    generator = random.Random(20261008)
    for _ in range(3000):
        body = "".join(generator.choice(pieces) for _ in range(generator.randint(0, 40)))
        text = html_text(body)
        assert_derived_shape(text)
        assert html_text(body) == text


def test_html_text_is_deterministic_and_keeps_no_state_between_calls():
    body = '<html><body><p>Intel&nbsp;Foundry</p><div style="display:none">x</div><p>ﬁrst</p></body></html>'
    first = html_text(body)
    assert first == "Intel Foundry\nfirst\n"
    assert html_text('<div style="display:none">unclosed') == ""
    assert html_text(body) == first  # the unclosed element of the previous call hides nothing
    assert html_text("visible") == "visible\n"


@pytest.mark.parametrize(
    "body",
    [
        "<html><head><title>t</title></head><body><p>a&nbsp;b</p><table><tr><td>1</td><td>2</td></tr></table>"
        "</body></html>",
        "<div>\ufeffline\u2028one\r\nline\ttwo&shy;</div><br><br><br><p>  </p><p>\u3000end\u00a0</p>",
        '<p style="display:none">x</p>',
        "&#x2028;&#x85;&#xB;&#xC;",
    ],
)
def test_html_output_has_only_spaces_and_line_feeds_and_one_final_line_feed(body):
    assert_derived_shape(html_text(body))


# --------------------------------------------------------------------------- XML

# A Schedule 13G amendment in EDGAR's XML form, cut to a few elements (the CIKs are synthetic).
SCHEDULE_13G = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g" xmlns:com="http://www.sec.gov/edgar/common">
  <headerData>
    <submissionType>SCHEDULE 13G/A</submissionType>
    <filerInfo><filer><filerCredentials><cik>0001234567</cik></filerCredentials></filer></filerInfo>
  </headerData>
  <formData>
    <coverPageHeader>
      <securitiesClassTitle>Common Stock, par value $0.001 per share</securitiesClassTitle>
      <issuerInfo><issuerCik>0000050863</issuerCik><issuerName>INTEL CORP</issuerName></issuerInfo>
    </coverPageHeader>
    <coverPageHeaderReportingPersonDetails>
      <reportingPersonName>Example Holdings LLC</reportingPersonName>
      <aggregateAmountOwned>291000000</aggregateAmountOwned>
      <classPercent>6.7</classPercent>
      <com:typeOfReportingPerson>IA</com:typeOfReportingPerson>
    </coverPageHeaderReportingPersonDetails>
  </formData>
</edgarSubmission>
"""


def test_xml_text_is_a_line_per_element_holding_text_named_without_its_namespace():
    assert xml_text(SCHEDULE_13G) == (
        "submissionType: SCHEDULE 13G/A\n"
        "cik: 0001234567\n"
        "securitiesClassTitle: Common Stock, par value $0.001 per share\n"
        "issuerCik: 0000050863\n"
        "issuerName: INTEL CORP\n"
        "reportingPersonName: Example Holdings LLC\n"
        "aggregateAmountOwned: 291000000\n"
        "classPercent: 6.7\n"
        "typeOfReportingPerson: IA\n"
    )


def test_xml_text_collapses_whitespace_and_drops_elements_without_text():
    body = "<root><a>  one \n\t two\r\n</a><b/><c>   </c><d></d><e>\u00a0</e></root>".encode()
    assert xml_text(body) == "a: one two\n"


def test_xml_text_reads_an_elements_text_before_its_children_in_document_order():
    assert xml_text(b"<root>Item 4<a>Ownership</a><b><c>6.7</c></b></root>") == (
        "root: Item 4\na: Ownership\nc: 6.7\n"
    )


def test_xml_text_keeps_the_text_after_a_child_element_as_its_parents():
    assert xml_text(b"<p>Owned <b>6.7%</b> of the class</p>") == "p: Owned\nb: 6.7%\np: of the class\n"


def test_xml_text_reads_references_and_character_data_as_text():
    body = b"<root><a>R&amp;D &lt;b&gt; &#8217;s</a><b><![CDATA[x < y & z]]></b></root>"
    assert xml_text(body) == "a: R&D <b> \u2019s\nb: x < y & z\n"


def test_xml_text_drops_comments_and_processing_instructions():
    assert xml_text(b"<root><!-- a note --><?render now?><a>kept</a></root>") == "a: kept\n"


def test_xml_text_applies_the_line_normalisation():
    body = "<root><a>manu\u00adfacturing \ufb01rst\u200b</a></root>".encode()
    assert xml_text(body) == "a: manufacturing first\n"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"<root/>", id="empty-root"),
        pytest.param(b"<root>\n  <a/>\n  <b> </b>\n</root>", id="only-whitespace"),
    ],
)
def test_xml_text_of_a_document_without_text_is_empty(body):
    assert xml_text(body) == ""


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b'<?xml version="1.0"?><!DOCTYPE root SYSTEM "root.dtd"><root>x</root>', id="doctype"),
        pytest.param(b"<!doctype root><root>x</root>", id="doctype-lowercase"),
        pytest.param(b'<!DOCTYPE root [<!ENTITY e "expanded">]><root>&e;</root>', id="entity"),
        pytest.param(b"<root><![CDATA[<!ENTITY]]></root>", id="declaration-anywhere-in-the-bytes"),
    ],
)
def test_xml_text_refuses_a_document_type_or_entity_declaration(body):
    with pytest.raises(ValueError) as caught:
        xml_text(body)
    assert str(caught.value) == "the XML document declares a document type or an entity"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        pytest.param(b"", "no element found: line 1, column 0", id="empty"),
        pytest.param(b"<root>", "no element found: line 1, column 6", id="unclosed"),
        pytest.param(b"<root></a>", "mismatched tag: line 1, column 8", id="mismatched"),
        pytest.param(b"<a/><b/>", "junk after document element: line 1, column 4", id="two-roots"),
        pytest.param(b"plain words", "syntax error: line 1, column 0", id="not-xml"),
    ],
)
def test_xml_text_refuses_xml_that_is_not_well_formed(body, message):
    with pytest.raises(ValueError) as caught:
        xml_text(body)
    assert str(caught.value) == f"the XML document is not well-formed: {message}"


def test_xml_text_has_the_derived_shape_and_is_deterministic():
    text = xml_text(SCHEDULE_13G)
    assert_derived_shape(text)
    assert xml_text(SCHEDULE_13G) == text
