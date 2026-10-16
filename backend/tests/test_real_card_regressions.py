"""
Regression tests for bugs found by running a REAL card photo through the pipeline:

* The card's old-format QR holds ADDRESS data only (no dob/gender) with a masked uid
  ("xxxxxxxx1234") and a `pincode` attribute (not `pc`). It was parsed as having no last-4 and
  no pincode.
* The side with the address printed no name, but the OCR picked an address line as the "name",
  which the cross-match then called a confident mismatch -> a genuine card was flagged "tampered".
* The photo was taken sideways; the QR reports the rotation so the OCR can straighten the page.
All values below are invented.
"""
import cv2
import numpy as np
import pytest

from verification import crossmatch, decision, ocr, qr_decoder
from verification.ocr import OcrLine
from verification.qr_decoder import QrData
from verification.signature import SignatureOutcome

from . import synth

MASKED_OLD_QR = (
    '<?xml version="1.0" encoding="UTF-8"?><PrintLetterBarcodeData uid="xxxxxxxx5057" name="Test Person" '
    'building="C/301 Example CHS" street="Sample Road" landmark="Near Park" locality="Some Nagar" '
    'vtcName="Townville" districtName="Thane" stateName="Maharashtra" pincode="421202"/>'
)


def _line(text, y, conf=0.95, x=10):
    return OcrLine(text, conf, x, y, x + 8 * len(text), y + 20)


# ------------------------------------------------------------- QR parsing
def test_old_qr_masked_uid_keeps_last4_and_reads_pincode_attribute():
    qr = qr_decoder.parse_old_qr(MASKED_OLD_QR)
    assert qr.fields["last4"] == "5057"
    assert qr.fields["pincode"] == "421202"
    assert qr.fields["dob"] is None and qr.fields["gender"] is None  # address-only QR
    assert qr.fields["name"] == "Test Person"


@pytest.mark.parametrize("uid,expected", [("123412341234", "1234"), ("XXXXXXXX9876", "9876"), ("garbage", None), ("12345", None)])
def test_old_qr_uid_variants(uid, expected):
    xml = f'<?xml version="1.0"?><PrintLetterBarcodeData uid="{uid}" name="A B" pincode="411001"/>'
    assert qr_decoder.parse_old_qr(xml).fields["last4"] == expected


def test_old_qr_pincode_must_be_six_digits():
    xml = '<?xml version="1.0"?><PrintLetterBarcodeData uid="xxxxxxxx5057" pincode="12"/>'
    assert qr_decoder.parse_old_qr(xml).fields["pincode"] is None


# ------------------------------------------------------------- rotation
@pytest.fixture(scope="module")
def card_png():
    key = synth.new_key()
    return synth.render_card(synth.make_secure_qr_text(key))


@pytest.mark.parametrize("op,expected_rotation", [
    (None, 0),
    (cv2.ROTATE_90_CLOCKWISE, 90),            # a card photographed sideways (like the real one)
    (cv2.ROTATE_90_COUNTERCLOCKWISE, 270),
    (cv2.ROTATE_180, 180),
])
def test_qr_reports_rotation_and_rotate_upright_restores_the_page(card_png, op, expected_rotation):
    original = cv2.imdecode(np.frombuffer(card_png, np.uint8), cv2.IMREAD_COLOR)
    turned = original if op is None else cv2.rotate(original, op)
    page = cv2.imencode(".png", turned)[1].tobytes()

    qr, problem = qr_decoder.decode_pages([page])
    assert qr is not None and problem is None
    assert qr.rotation == expected_rotation

    restored = cv2.imdecode(np.frombuffer(ocr.rotate_upright(page, qr.rotation), np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(restored, original)  # lossless: exactly upright again


def test_snap_rotation_ignores_small_tilts():
    snap = qr_decoder._snap_rotation
    assert snap(0) == 0 and snap(90) == 90 and snap(-90) == 270 and snap(180) == 180
    assert snap(8) == 0 and snap(95) == 90
    assert snap(45) == 0  # ambiguous: leave alone


def test_rotate_upright_zero_is_a_no_op():
    data = b"not even an image"
    assert ocr.rotate_upright(data, 0) is data


# ------------------------------------------------------------- OCR parsing: address side
ADDRESS_SIDE = [
    _line("Unique Identification Authority of India", 10),
    _line("Address:", 60),
    _line("C/301 YOG SANKUL CHS LTD,", 100),
    _line("MAHATMA PHULE ROAD,", 130),
    _line("WEST, DOMBIVALI, Thane,", 160),
    _line("Maharashtra, 421202", 190),
    _line("XXXX XXXX 5057", 300, x=200),
]


def test_address_side_yields_no_name():
    card = ocr.parse_card_text(ADDRESS_SIDE)
    assert card.name is None                      # the bug: an address line used to become the "name"
    assert card.last4 == "5057" and card.number_masked
    assert "421202" in card.six_digit_tokens


def test_front_side_still_finds_the_name():
    lines = [
        _line("Government of India", 10),
        _line("Asha Mehta", 100),
        _line("DOB: 15/08/1990", 140),
        _line("FEMALE", 180),
        _line("7823 4567 1231", 300),
    ]
    card = ocr.parse_card_text(lines)
    assert card.name == "Asha Mehta" and card.dob == "15-08-1990" and card.gender == "F"


# ------------------------------------------------------------- cross-match + decision on the address side
def _qr():
    return QrData("old", qr_decoder.parse_old_qr(MASKED_OLD_QR).fields, note="old")


def test_address_side_crossmatch_matches_last4_and_pincode_and_checks_nothing_else():
    cross = crossmatch.compare(ocr.parse_card_text(ADDRESS_SIDE), _qr().fields)
    by = {f.key: f.status for f in cross.fields}
    assert by["Aadhaar (last 4)"] == "match"
    assert by["Pincode"] == "match"
    assert by["Name"] == by["DOB"] == by["Gender"] == "not_checked"
    assert cross.mismatch_count == 0


def test_genuine_old_qr_address_side_goes_to_manual_review_not_tampered():
    cross = crossmatch.compare(ocr.parse_card_text(ADDRESS_SIDE), _qr().fields)
    res = decision.decide(True, _qr(), SignatureOutcome(None, None, "n/a"), cross)
    assert res.outcome == "manual_review"


def test_pincode_not_on_page_is_not_a_mismatch():
    lines = [l for l in ADDRESS_SIDE if "421202" not in l.text] + [_line("Maharashtra", 190)]
    cross = crossmatch.compare(ocr.parse_card_text(lines), _qr().fields)
    assert {f.key: f.status for f in cross.fields}["Pincode"] == "not_checked"


def test_different_pincode_is_partial_never_mismatch():
    lines = [l for l in ADDRESS_SIDE if "421202" not in l.text] + [_line("Maharashtra, 400001", 190)]
    cross = crossmatch.compare(ocr.parse_card_text(lines), _qr().fields)
    assert {f.key: f.status for f in cross.fields}["Pincode"] == "partial"
    assert cross.mismatch_count == 0


def test_ocr_falls_back_to_rapid_when_paddle_cannot_start(monkeypatch):
    from tests import synth

    def boom():
        raise RuntimeError("simulated PaddleOCR crash")

    monkeypatch.setattr(ocr.config, "OCR_ENGINE", "paddle")
    monkeypatch.setattr(ocr, "_load_paddle", boom)
    monkeypatch.setattr(ocr, "_engine", None)
    monkeypatch.setattr(ocr, "_engine_kind", None)
    lines = ocr.run_ocr(synth.render_card(synth.make_old_qr_xml()))
    assert lines and ocr._engine_kind == "rapid"


def test_ocr_switches_to_rapid_when_paddle_crashes_while_reading(monkeypatch):
    from tests import synth

    class Broken:
        def predict(self, img):
            raise RuntimeError("simulated oneDNN crash")

    monkeypatch.setattr(ocr, "_engine", Broken())
    monkeypatch.setattr(ocr, "_engine_kind", "paddle3")
    lines = ocr.run_ocr(synth.render_card(synth.make_old_qr_xml()))
    assert lines and ocr._engine_kind == "rapid"


def test_name_with_spaces_dropped_by_ocr_still_matches():
    card = ocr.CardFields(name="TanayAtmaramBandekar", name_conf=0.9, line_count=10, avg_conf=0.9)
    cross = crossmatch.compare(card, {"name": "Tanay Atmaram Bandekar"})
    f = {x.key: x for x in cross.fields}["Name"]
    assert f.status == "match" and f.similarity == 100


def test_genuinely_different_name_still_mismatches():
    card = ocr.CardFields(name="Rahul Sharma", name_conf=0.95, line_count=10, avg_conf=0.9)
    cross = crossmatch.compare(card, {"name": "Tanay Atmaram Bandekar"})
    assert {x.key: x for x in cross.fields}["Name"].status == "mismatch"


def _small_qr_photo(seed=0, side=100, blur=0.9, noise=10):
    """A dense QR only ~100px wide in a 567x377 noisy, blurry JPEG, like a downsized card photo."""
    import io
    import cv2
    import numpy as np
    import segno
    from tests import synth

    rng = np.random.default_rng(seed)
    buf = io.BytesIO()
    segno.make(synth.make_old_qr_xml(), error="L").save(buf, kind="png", scale=1, border=2)
    code = cv2.imdecode(np.frombuffer(buf.getvalue(), np.uint8), cv2.IMREAD_GRAYSCALE)
    code = cv2.resize(code, (side, side), interpolation=cv2.INTER_AREA)
    c = np.full((377, 567), 200, np.float32) + np.linspace(-30, 30, 567)[None, :]
    c[120:120 + side, 420:420 + side] = code
    c = cv2.GaussianBlur(c, (0, 0), blur) + rng.normal(0, noise, c.shape)
    c = np.clip(c, 0, 255).astype(np.uint8)
    cv2.putText(c, "GOVERNMENT OF INDIA", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 40, 2)
    return cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 55])[1].tobytes()


def test_small_qr_in_large_photo_is_found_via_zoomed_tiles():
    from verification import qr_decoder
    found = qr_decoder.read_qr(_small_qr_photo(seed=1))
    assert found is not None and "PrintLetterBarcodeData" in found[0]


def test_whole_image_pass_alone_misses_it(monkeypatch):
    """Guards the test above: without the zoomed tiles this photo is NOT readable."""
    from verification import qr_decoder
    monkeypatch.setattr(qr_decoder, "_tiles", lambda gray: iter(()))
    assert qr_decoder.read_qr(_small_qr_photo(seed=1)) is None


def _lines(*rows):
    return [ocr.OcrLine(text, 0.9, 0, y * 40, 400, y * 40 + 30) for y, text in enumerate(rows)]


def test_older_card_name_is_not_the_fathers_name():
    card = ocr.parse_card_text(_lines(
        "GOVERNMENT OFINDIA", "Asha Mehta", "Father :Ramesh Mehta", "Year of Birth:2008", "Female", "372264540039"))
    assert card.name == "Asha Mehta" and card.dob == "2008" and card.gender == "F"


def test_relation_prefix_variants_are_skipped():
    for rel in ("S/O: Ramesh Mehta", "D/O Ramesh Mehta", "C/O: Ramesh Mehta", "FatherRamesh Mehta", "Husband: Ramesh Mehta"):
        card = ocr.parse_card_text(_lines("Asha Mehta", rel, "DOB: 15/08/1990", "Female", "7823 4567 1239"))
        assert card.name == "Asha Mehta", rel
