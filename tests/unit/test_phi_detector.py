"""Unit tests for 3-layer PHI detection (regex layer)."""
import pytest

from backend.services.phi_detector import PHIDetector


@pytest.fixture
def detector():
    return PHIDetector()


class TestRegexScan:
    def test_detects_medicare_id(self, detector):
        text = "Member Medicare ID: 12345678901 effective Jan 2024."
        hits = detector._regex_scan(text)
        types = {h["phi_type"] for h in hits}
        assert "MEDICARE_ID" in types

    def test_detects_ssn(self, detector):
        text = "Provider SSN is 123-45-6789 on file."
        hits = detector._regex_scan(text)
        types = {h["phi_type"] for h in hits}
        assert "SSN" in types

    def test_detects_mrn(self, detector):
        text = "Patient MRN: 0012345678 admitted on 03/15/2024."
        hits = detector._regex_scan(text)
        types = {h["phi_type"] for h in hits}
        assert "MRN" in types

    def test_detects_dob(self, detector):
        text = "Date of Birth: 03/15/1985 recorded in chart."
        hits = detector._regex_scan(text)
        types = {h["phi_type"] for h in hits}
        assert "DOB" in types

    def test_detects_npi(self, detector):
        text = "Provider NPI: 1234567890 is active."
        hits = detector._regex_scan(text)
        types = {h["phi_type"] for h in hits}
        assert "NPI" in types

    def test_detects_phone(self, detector):
        text = "Contact: (555) 123-4567 for inquiries."
        hits = detector._regex_scan(text)
        types = {h["phi_type"] for h in hits}
        assert "PHONE" in types

    def test_detects_email(self, detector):
        text = "Send to dr.smith@hospital.org for review."
        hits = detector._regex_scan(text)
        types = {h["phi_type"] for h in hits}
        assert "EMAIL" in types

    def test_no_false_positives_on_clean_text(self, detector):
        text = "This agreement covers general terms and conditions for healthcare services."
        hits = detector._regex_scan(text)
        assert len(hits) == 0

    def test_captures_context(self, detector):
        text = "X" * 100 + "SSN 123-45-6789" + "Y" * 100
        hits = detector._regex_scan(text)
        assert len(hits) > 0
        ctx = hits[0]["context"]
        assert len(ctx) <= 114  # match + 50 chars each side


class TestMasking:
    def test_mask_short_value(self, detector):
        assert detector._mask_value("AB") == "**"

    def test_mask_ssn(self, detector):
        masked = detector._mask_value("123-45-6789")
        assert masked[0] == "1"
        assert masked[-1] == "9"
        assert "*" in masked
        assert len(masked) == 11

    def test_mask_preserves_length(self, detector):
        val = "test@example.com"
        masked = detector._mask_value(val)
        assert len(masked) == len(val)
