"""PDF behavior tests; install pypdf in a dev environment for text assertions."""

from io import BytesIO
import unittest

from becayis.pdf_export import make_petition_pdf

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


APPLICANT = {
    "institution": "Sağlık Bakanlığı",
    "title": "Tıbbi Sekreter",
    "employment": "4/B Sözleşmeli",
    "current_province": "İstanbul",
    "current_district": "Üsküdar",
}
PARTNER = {
    **APPLICANT,
    "current_province": "Ankara",
    "current_district": "Çankaya",
}


class PetitionPdfTests(unittest.TestCase):
    def test_returns_complete_pdf_bytes(self):
        pdf = make_petition_pdf(APPLICANT, PARTNER)
        self.assertIsInstance(pdf, bytes)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf[-100:])
        self.assertGreater(len(pdf), 10_000)  # Embedded Unicode font.

    @unittest.skipIf(PdfReader is None, "pypdf is an optional development dependency")
    def test_unicode_and_demo_warning_are_present_on_one_page(self):
        reader = PdfReader(BytesIO(make_petition_pdf(APPLICANT, PARTNER, "Çağrı Şen")))
        self.assertEqual(len(reader.pages), 1)
        text = " ".join(reader.pages[0].extract_text().split())
        for expected in (
            "Karşılıklı Yer Değiştirme Talep Taslağı",
            "DEMO", "BAŞVURU TASLAĞI", "Çağrı Şen", "İstanbul / Üsküdar",
            "Ankara / Çankaya", "kurum onayını doğrulamış sayılmaz",
        ):
            self.assertIn(expected, text)
        self.assertIn("DEMO", reader.metadata.title)

    @unittest.skipIf(PdfReader is None, "pypdf is an optional development dependency")
    def test_markup_is_literal_and_unknown_private_fields_are_excluded(self):
        ad = {
            **APPLICANT,
            "institution": "Sağlık <b>Bakanlığı</b> & Kurum",
            "notes": '<link href="https://example.com">tıkla</link> <script>örnek</script>',
            "tc_identity_no": "12345678901",
            "phone": "05550001122",
            "hidden_unit": "Gizli Birim XYZ",
        }
        reader = PdfReader(BytesIO(make_petition_pdf(ad, PARTNER, "<b>Çağrı</b>")))
        text = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn("<b>Bakanlığı</b> & Kurum", text)
        self.assertIn("<b>Çağrı</b>", text)
        self.assertIn("<script>örnek</script>", text)
        for private_value in ("12345678901", "05550001122", "Gizli Birim XYZ"):
            self.assertNotIn(private_value, text)
        # Escaped link markup must not become an active PDF link annotation.
        for page in reader.pages:
            self.assertFalse(page.get("/Annots"))

    @unittest.skipIf(PdfReader is None, "pypdf is an optional development dependency")
    def test_long_notes_paginate_without_losing_end_text(self):
        ad = {
            **APPLICANT,
            "notes": ("Görev yeri tercihim hakkında açıklama. " * 220) + "SON KAYIT ÇĞİÖŞÜ",
        }
        reader = PdfReader(BytesIO(make_petition_pdf(ad, PARTNER)))
        self.assertGreater(len(reader.pages), 1)
        text = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn("SON KAYIT ÇĞİÖŞÜ", text)
        for page in reader.pages:
            self.assertIn("DEMO - Kullanıcı önizlemesi için taslak", page.extract_text())

    def test_name_over_limit_is_rejected_instead_of_truncated(self):
        with self.assertRaises(ValueError):
            make_petition_pdf(APPLICANT, PARTNER, "x" * 151)

    def test_nested_field_values_are_rejected(self):
        with self.assertRaises(ValueError):
            make_petition_pdf({**APPLICANT, "title": {"unexpected": "value"}}, PARTNER)

    def test_notes_over_limit_are_rejected(self):
        with self.assertRaises(ValueError):
            make_petition_pdf({**APPLICANT, "notes": "x" * 20_001}, PARTNER)

    def test_control_characters_are_rejected(self):
        with self.assertRaises(ValueError):
            make_petition_pdf(APPLICANT, PARTNER, "Ad\x00Soyad")


if __name__ == "__main__":
    unittest.main()
