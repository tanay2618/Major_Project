import gzip
import os
import zlib

import pytest

from verification import config, crossmatch, decision, qr_decoder, signature, verhoeff
from verification.ocr import CardFields, OcrLine, parse_card_text
from verification.qr_decoder import QrData, QrDecodeError
from verification.signature import SignatureOutcome

from . import synth


# ----------------------------------------------------------------- Verhoeff
@pytest.mark.parametrize("n", ["2363", "1234" + "51"[:0] + "5" + "1"])  # known-valid vectors
def test_verhoeff_known_valid(n):
    assert verhoeff.validate("2363") is True          # 236 -> check digit 3 (published example)
    assert verhoeff.validate("123451") is True        # 12345 -> check digit 1 (published example)


def test_verhoeff_generate_matches_published_examples():
    assert verhoeff.generate_check_digit("236") == "3"
    assert verhoeff.generate_check_digit("12345") == "1"


def test_verhoeff_detects_single_digit_errors_and_swaps():
    good = synth.make_aadhaar_number()
    assert verhoeff.validate(good)
    for i in range(12):
        for d in "0123456789":
            if d != good[i]:
                assert not verhoeff.validate(good[:i] + d + good[i + 1:])  # every 1-digit typo caught
    swapped = good[:3] + good[4] + good[3] + good[5:]
    if good[3] != good[4]:
        assert not verhoeff.validate(swapped)


def test_aadhaar_number_rules():
    good = synth.make_aadhaar_number()
    assert verhoeff.is_valid_aadhaar_number(good)
    assert verhoeff.is_valid_aadhaar_number(f"{good[:4]} {good[4:8]} {good[8:]}")
    assert not verhoeff.is_valid_aadhaar_number(good[:-1])           # 11 digits
    assert not verhoeff.is_valid_aadhaar_number("0" + good[1:])      # cannot start with 0
    assert not verhoeff.is_valid_aadhaar_number("abc")


# --------------------------------------------------------------- Secure QR parse
@pytest.mark.parametrize("versioned", [True, False])
def test_secure_qr_round_trip(versioned):
    key = synth.new_key()
    number = synth.make_aadhaar_number()
    text = synth.make_secure_qr_text(key, number=number, versioned=versioned)
    qr = qr_decoder.parse_secure_qr(text)
    assert qr.qr_type == "secure"
    assert qr.version == ("V2" if versioned else None)
    assert qr.fields == {"name": "Asha Mehta", "dob": "15-08-1990", "gender": "F",
                         "last4": number[-4:], "pincode": "411001"}
    assert len(qr.signature) == 256
    assert qr.note is None


def test_secure_qr_longer_than_pythons_4300_digit_int_limit():
    """Real cards can exceed 4300 digits; int(text) would have rejected them."""
    key = synth.new_key()
    text = synth.make_secure_qr_text(key, photo=os.urandom(2200))
    assert 4400 < len(text) <= 7089  # above the int limit, within real QR capacity
    qr = qr_decoder.parse_secure_qr(text)
    assert qr.fields["name"] == "Asha Mehta" and len(qr.signature) == 256


def test_secure_qr_too_many_digits_refused():
    with pytest.raises(QrDecodeError):
        qr_decoder.parse_secure_qr("7" * 9000)


def test_secure_qr_photo_with_ff_bytes_does_not_break_fields():
    key = synth.new_key()
    qr = qr_decoder.parse_secure_qr(synth.make_secure_qr_text(key, photo=b"\xff" * 500 + b"\x00\xff\xff"))
    assert qr.fields["name"] == "Asha Mehta"


def test_secure_qr_utf8_name():
    key = synth.new_key()
    qr = qr_decoder.parse_secure_qr(synth.make_secure_qr_text(key, name="Zoë Müller"))
    assert qr.fields["name"] == "Zoë Müller"


def test_secure_qr_garbage_is_rejected_cleanly():
    with pytest.raises(QrDecodeError):
        qr_decoder.parse_secure_qr("1" * 500)                      # not gzip
    with pytest.raises(QrDecodeError):
        qr_decoder.parse_secure_qr(synth.bytes_to_digits(gzip.compress(b"short")))


def test_secure_qr_decompression_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(config, "MAX_DECOMPRESSED_QR_BYTES", 10_000)
    bomb = gzip.compress(b"\x00" * 5_000_000)
    with pytest.raises(QrDecodeError):
        qr_decoder.parse_secure_qr(synth.bytes_to_digits(bomb))


def test_old_qr_parsed_and_full_number_not_kept():
    number = synth.make_aadhaar_number()
    qr = qr_decoder.parse_old_qr(synth.make_old_qr_xml(number=number))
    assert qr.qr_type == "old"
    assert qr.fields["last4"] == number[-4:]
    assert number not in repr(qr)                                   # full uid never retained
    assert qr.fields["dob"] == "15-08-1990"
    assert qr.signature is None


def test_old_qr_entity_bomb_rejected():
    evil = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
            '<PrintLetterBarcodeData name="&b;"/>')
    with pytest.raises(QrDecodeError):
        qr_decoder.parse_old_qr(evil)


def test_classify():
    assert qr_decoder.classify("<?xml version='1.0'?><PrintLetterBarcodeData/>") == "old"
    assert qr_decoder.classify("1" * 300) == "secure"
    assert qr_decoder.classify("https://example.com") == "unknown"


# ------------------------------------------------------------------ signature
@pytest.fixture()
def certdir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UIDAI_CERT_DIR", tmp_path)
    return tmp_path


def _qr(key, **kw):
    return qr_decoder.parse_secure_qr(synth.make_secure_qr_text(key, **kw))


def test_signature_valid(certdir):
    key = synth.new_key()
    synth.write_cert(key, certdir / "uidai_test.cer")
    qr = _qr(key)
    out = signature.verify_secure_qr(qr.signed_data, qr.signature)
    assert out.valid is True and "uidai_test.cer" in out.reason and "Test UIDAI" in out.issuer


def test_signature_detects_any_edit(certdir):
    key = synth.new_key()
    synth.write_cert(key, certdir / "uidai_test.cer")
    qr = _qr(key)
    edited = bytearray(qr.signed_data)
    edited[30] ^= 0x01                                   # flip one bit in the signed data
    assert signature.verify_secure_qr(bytes(edited), qr.signature).valid is False


def test_signature_from_other_key_is_forged(certdir):
    synth.write_cert(synth.new_key(), certdir / "uidai_test.cer")   # installed cert
    attacker_qr = _qr(synth.new_key())                              # signed by someone else
    assert signature.verify_secure_qr(attacker_qr.signed_data, attacker_qr.signature).valid is False


def test_signature_cannot_be_checked_without_certificates(certdir):
    qr = _qr(synth.new_key())
    out = signature.verify_secure_qr(qr.signed_data, qr.signature)
    assert out.valid is None and "certs" in out.reason


def test_signature_tries_every_certificate(certdir):
    old, new = synth.new_key(), synth.new_key()
    synth.write_cert(new, certdir / "a_new.cer")
    synth.write_cert(old, certdir / "b_old.cer", expired=True)
    qr = _qr(old)
    out = signature.verify_secure_qr(qr.signed_data, qr.signature)
    assert out.valid is True and "older UIDAI key" in out.reason     # expired cert still accepted, with a note


def test_signature_ignores_junk_files(certdir):
    (certdir / "notes.txt").write_text("hello")
    (certdir / "broken.cer").write_bytes(b"not a certificate")
    key = synth.new_key()
    synth.write_cert(key, certdir / "ok.cer")
    qr = _qr(key)
    assert signature.verify_secure_qr(qr.signed_data, qr.signature).valid is True


# ------------------------------------------------------------- OCR text parsing
def L(text, y, conf=0.97, x=100):
    return OcrLine(text, conf, x, y, x + 600, y + 40)


def test_parse_full_card():
    lines = [L("Government of India", 50), L("Asha Mehta", 200), L("DOB: 15/08/1990", 260),
             L("Female", 320), L("7823 4567 1239", 500), L("VID : 9123 4567 8901 2345", 600)]
    c = parse_card_text(lines)
    assert (c.name, c.dob, c.gender, c.number, c.last4) == ("Asha Mehta", "15-08-1990", "F", "782345671239", "1239")
    assert c.number_masked is False and c.avg_conf > 0.9


def test_parse_ignores_vid_when_number_missing():
    c = parse_card_text([L("Asha Mehta", 200), L("DOB: 15/08/1990", 260), L("VID : 9123 4567 8901 2345", 600)])
    assert c.number is None and c.last4 is None


def test_parse_number_split_into_three_pieces_on_one_row():
    pieces = [OcrLine("7823", 0.9, 100, 500, 300, 540), OcrLine("4567", 0.9, 380, 502, 580, 542),
              OcrLine("1239", 0.9, 660, 498, 860, 538)]
    c = parse_card_text([L("Asha Mehta", 200), L("DOB: 15/08/1990", 260)] + pieces)
    assert c.number == "782345671239" and c.last4 == "1239"


def test_parse_pieces_on_different_rows_are_not_joined():
    pieces = [OcrLine("7823", 0.9, 100, 500, 300, 540), OcrLine("4567", 0.9, 100, 700, 300, 740),
              OcrLine("1239", 0.9, 100, 900, 300, 940)]
    assert parse_card_text(pieces).number is None


def test_parse_masked_number():
    c = parse_card_text([L("Asha Mehta", 200), L("DOB: 15/08/1990", 260), L("XXXX XXXX 1239", 500)])
    assert c.last4 == "1239" and c.number is None and c.number_masked is True


def test_parse_year_of_birth_only():
    c = parse_card_text([L("Asha Mehta", 200), L("Year of Birth : 1990", 260), L("Female", 320)])
    assert c.dob == "1990"


def test_parse_name_skips_garbage_hindi_line_and_headers():
    lines = [L("Government of India", 50), L("आशा मेहता", 150, 0.6), L("Asha Mehta", 210), L("DOB: 15/08/1990", 270)]
    assert parse_card_text(lines).name == "Asha Mehta"


def test_parse_female_not_confused_with_male():
    assert parse_card_text([L("FEMALE", 100)]).gender == "F"
    assert parse_card_text([L("MALE", 100)]).gender == "M"


def test_parse_rejects_impossible_dates_and_issue_dates():
    c = parse_card_text([L("Asha Mehta", 200), L("DOB: 31/02/1990", 260), L("Aadhaar issued: 12/03/2019", 400)])
    assert c.dob is None


def test_parse_empty():
    c = parse_card_text([])
    assert c.line_count == 0 and c.name is None


# ---------------------------------------------------------------- cross-match
NUM = synth.make_aadhaar_number()          # valid checksum
BAD_NUM = NUM[:-1] + str((int(NUM[-1]) + 1) % 10)   # same number, wrong last digit
QR = {"name": "Asha Mehta", "dob": "15-08-1990", "gender": "F", "last4": NUM[-4:], "pincode": "411001"}


def card(**kw):
    base = dict(name="Asha Mehta", name_conf=0.97, dob="15-08-1990", dob_conf=0.97, gender="F",
                gender_conf=0.97, number=NUM, last4=NUM[-4:], number_conf=0.97,
                avg_conf=0.95, line_count=8)
    base.update(kw)
    return CardFields(**base)


def status(res, key):
    return next(f.status for f in res.fields if f.key == key)


def test_crossmatch_all_match():
    r = crossmatch.compare(card(), QR)
    assert r.mismatch_count == 0 and r.verhoeff_valid is True
    assert [status(r, k) for k in ("Name", "DOB", "Gender", "Aadhaar (last 4)", "Aadhaar checksum")] == ["match"] * 5
    assert status(r, "Pincode") == "not_checked"        # card did not print one


def test_crossmatch_confident_disagreement_is_mismatch():
    r = crossmatch.compare(card(name="Rohan Verma", dob="16-08-1990"), QR)
    assert status(r, "Name") == "mismatch" and status(r, "DOB") == "mismatch" and r.mismatch_count == 2


def test_crossmatch_low_confidence_disagreement_is_only_partial():
    r = crossmatch.compare(card(dob="16-08-1990", dob_conf=0.55), QR)
    assert status(r, "DOB") == "partial" and r.mismatch_count == 0


def test_crossmatch_name_tolerates_case_punctuation_and_order():
    assert status(crossmatch.compare(card(name="MEHTA, ASHA."), QR), "Name") == "match"


def test_crossmatch_missing_printed_value_is_not_checked_never_mismatch():
    r = crossmatch.compare(card(name=None, dob=None, gender=None), QR)
    assert [status(r, k) for k in ("Name", "DOB", "Gender")] == ["not_checked"] * 3 and r.mismatch_count == 0


def test_crossmatch_bad_checksum():
    r = crossmatch.compare(card(number=BAD_NUM, last4=BAD_NUM[-4:]), QR)
    assert status(r, "Aadhaar checksum") == "mismatch" and status(r, "Aadhaar (last 4)") == "mismatch"
    assert r.verhoeff_valid is False


def test_crossmatch_year_only_card_matches_on_year():
    assert status(crossmatch.compare(card(dob="1990"), QR), "DOB") == "match"
    assert status(crossmatch.compare(card(dob="1991"), QR), "DOB") == "mismatch"


def test_crossmatch_masked_number_skips_checksum():
    r = crossmatch.compare(card(number=None, number_masked=True), QR)
    assert status(r, "Aadhaar checksum") == "not_checked" and status(r, "Aadhaar (last 4)") == "match"


def test_crossmatch_unreadable_text_flag():
    assert crossmatch.compare(card(avg_conf=0.2), QR).readable is False
    assert crossmatch.compare(CardFields(), QR).readable is False


# ------------------------------------------------------------------- decision
SEC = QrData("secure", dict(QR), b"x", b"y")
OLD = QrData("old", dict(QR))
OK = SignatureOutcome(True, "UIDAI", "ok")
BAD = SignatureOutcome(False, None, "bad")
NOCERT = SignatureOutcome(None, None, "no certificate")


@pytest.mark.parametrize("label,quality,qr,sig,cross,outcome", [
    ("low quality image", False, SEC, OK, crossmatch.compare(card(), QR), "low_quality"),
    ("no qr", True, None, None, crossmatch.compare(card(), {}), "manual_review"),
    ("ocr unreadable", True, SEC, OK, crossmatch.compare(card(avg_conf=0.1), QR), "low_quality"),
    ("bad signature", True, SEC, BAD, crossmatch.compare(card(), QR), "forged"),
    ("bad signature beats matching fields", True, SEC, BAD, crossmatch.compare(card(), QR), "forged"),
    ("old qr, all match", True, OLD, SignatureOutcome(None, None, "n/a"), crossmatch.compare(card(), QR), "likely_authentic"),
    ("old qr, mismatch", True, OLD, SignatureOutcome(None, None, "n/a"), crossmatch.compare(card(name="Rohan Verma"), QR), "tampered"),
    ("no certificate installed", True, SEC, NOCERT, crossmatch.compare(card(), QR), "manual_review"),
    ("valid sig, name edited", True, SEC, OK, crossmatch.compare(card(name="Rohan Verma"), QR), "tampered"),
    ("valid sig, bad checksum", True, SEC, OK, crossmatch.compare(card(number=BAD_NUM, last4=NUM[-4:]), QR), "tampered"),
    ("valid sig, shaky OCR", True, SEC, OK, crossmatch.compare(card(dob="16-08-1990", dob_conf=0.5), QR), "manual_review"),
    ("valid sig, too little readable", True, SEC, OK, crossmatch.compare(card(name=None, dob=None, number=None, last4=None), QR), "manual_review"),
    ("valid sig, all match", True, SEC, OK, crossmatch.compare(card(), QR), "verified"),
])
def test_decision_table(label, quality, qr, sig, cross, outcome):
    d = decision.decide(quality, qr, sig, cross)
    assert d.outcome == outcome, f"{label}: got {d.outcome} ({d.reasons})"
    assert d.reasons
    if outcome == "low_quality":
        assert d.risk_score is None
    if outcome == "forged":
        assert d.risk_score >= 90


def test_decision_secure_qr_with_unparseable_fields_goes_to_review():
    qr = QrData("secure", None, b"x", b"y", note="unusual")
    assert decision.decide(True, qr, OK, crossmatch.compare(card(), {})).outcome == "manual_review"


# ------------------------------------------- old unsigned QR: the 3 core fields
NOSIG = SignatureOutcome(None, None, "n/a")
OLD_QR = {"name": QR["name"], "last4": QR["last4"], "pincode": "421202"}  # what a DigiLocker QR holds


def test_old_qr_core_fields_match_is_likely_authentic():
    cross = crossmatch.compare(card(six_digit_tokens=["421202"]), OLD_QR)
    d = decision.decide(True, QrData("old", dict(OLD_QR)), NOSIG, cross)
    assert d.outcome == "likely_authentic" and d.risk_score < 40
    assert "not cryptographic proof" in " ".join(d.reasons)


def test_old_qr_pincode_not_on_page_stays_manual_review():
    cross = crossmatch.compare(card(), OLD_QR)
    assert decision.decide(True, QrData("old", dict(OLD_QR)), NOSIG, cross).outcome == "manual_review"


def test_old_qr_core_match_but_other_field_disagrees_is_tampered():
    qr = dict(OLD_QR, dob="15-08-1990")
    cross = crossmatch.compare(card(six_digit_tokens=["421202"], dob="16-08-1991", dob_conf=0.95), qr)
    assert decision.decide(True, QrData("old", qr), NOSIG, cross).outcome == "tampered"


def test_old_qr_wrong_pincode_is_not_likely_authentic():
    cross = crossmatch.compare(card(six_digit_tokens=["400001"]), OLD_QR)
    assert decision.decide(True, QrData("old", dict(OLD_QR)), NOSIG, cross).outcome == "manual_review"


def test_secure_qr_never_returns_likely_authentic():
    cross = crossmatch.compare(card(six_digit_tokens=["421202"]), OLD_QR)
    assert decision.decide(True, QrData("secure", dict(OLD_QR), b"x", b"y"), OK, cross).outcome != "likely_authentic"


def test_old_qr_front_side_without_pincode_uses_dob_gender_checksum():
    qr = dict(QR)  # name, dob, gender, last4 ... but no pincode on the card front
    cross = crossmatch.compare(card(), qr)
    d = decision.decide(True, QrData("old", qr), NOSIG, cross)
    assert d.outcome == "likely_authentic", d.reasons


def test_old_qr_name_and_last4_alone_are_not_enough():
    qr = {"name": QR["name"], "last4": QR["last4"]}
    d = decision.decide(True, QrData("old", qr), NOSIG, crossmatch.compare(card(), qr))
    assert d.outcome == "manual_review"
