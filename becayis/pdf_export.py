"""Produce a previewable demo petition; never certify transfer eligibility."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


_FONT_NAME = "BecayisNotoSans"
_FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NotoSans-Regular.ttf"
_FONT_LOCK = Lock()
_FIELD_LIMIT = 240
_NAME_LIMIT = 150
_NOTES_LIMIT = 20_000


def _register_font() -> str:
    """Register once, including concurrent Streamlit sessions, from a stable path."""
    with _FONT_LOCK:
        if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            if not _FONT_PATH.is_file():
                raise RuntimeError("PDF için gerekli Noto Sans font dosyası bulunamadı.")
            pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_FONT_PATH)))
    return _FONT_NAME


def _text(value: object, *, label: str, limit: int, default: str = "Belirtilmedi") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{label} bir metin olmalıdır.")
    if len(value) > limit:
        raise ValueError(f"{label} en fazla {limit} karakter olabilir.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError(f"{label} geçersiz kontrol karakteri içeriyor.")
    return value.strip() or default


def _fields(ad: dict, label: str) -> dict[str, str]:
    if not isinstance(ad, dict):
        raise ValueError(f"{label} ilanı bir sözlük olmalıdır.")
    # The whitelist intentionally excludes identity numbers, phone and hidden units.
    fields = ("institution", "title", "employment", "current_province", "current_district")
    return {
        key: " ".join(_text(ad.get(key), label=key, limit=_FIELD_LIMIT).split())
        for key in fields
    }


def make_petition_pdf(
    applicant_ad: dict,
    partner_ad: dict,
    applicant_name: str = "Demo Kullanıcısı",
) -> bytes:
    """Return an A4 draft in memory, using only known public demo fields.

    Inputs must be strings. Names/catalog fields are bounded, notes are limited to
    20,000 characters and paginate without truncation. All user text is XML-escaped
    before ReportLab sees it, so markup and links become literal text. The output
    carries demo markings and does not imply institution approval or eligibility.
    """
    applicant = _fields(applicant_ad, "Başvuran")
    partner = _fields(partner_ad, "Diğer katılımcı")
    name = " ".join(
        _text(applicant_name, label="Ad soyad", limit=_NAME_LIMIT, default="Demo Kullanıcısı").split()
    )
    notes = _text(applicant_ad.get("notes"), label="Açıklama", limit=_NOTES_LIMIT, default="")
    font_name = _register_font()

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=24 * mm,
        title="DEMO - Karşılıklı Yer Değiştirme Talep Taslağı",
        author="Memur Becayiş Platformu - Demo",
        subject="Kullanıcı önizlemesi için başvuru taslağı; resmî başvuru değildir.",
        creator="Memur Becayiş Platformu demo PDF oluşturucu",
    )
    body = ParagraphStyle(
        "BecayisBody",
        fontName=font_name,
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#273449"),
        spaceAfter=10,
        splitLongWords=True,
    )
    title = ParagraphStyle(
        "BecayisTitle", parent=body, alignment=TA_CENTER, fontSize=16, leading=22, spaceAfter=14
    )
    notice = ParagraphStyle(
        "BecayisNotice", parent=body, alignment=TA_CENTER, fontSize=11, leading=17,
        textColor=colors.HexColor("#9A3412"), backColor=colors.HexColor("#FFF1E5"),
        borderPadding=9, spaceAfter=16,
    )
    caption = ParagraphStyle(
        "BecayisCaption", parent=body, fontSize=9, leading=14,
        textColor=colors.HexColor("#546176"),
    )

    story = [
        Paragraph("DEMO — BAŞVURU TASLAĞI", notice),
        Paragraph("Karşılıklı Yer Değiştirme Talep Taslağı", title),
        Paragraph(escape(applicant["institution"]) + "<br/>İlgili Birim / Yetkili Makama", body),
        Paragraph("Konu: Karşılıklı yer değişikliği talebinin değerlendirilmesi", body),
    ]

    current = f"{applicant['current_province']} / {applicant['current_district']}"
    target = f"{partner['current_province']} / {partner['current_district']}"
    petition = (
        f"{current} görev yerinde, {applicant['title']} unvanıyla ve "
        f"{applicant['employment']} istihdam türünde çalıştığımı beyan ederek, "
        f"{target} görev yerindeki diğer katılımcı ile karşılıklı yer değişikliği "
        "talebimin tabi olduğum personel rejimi ve kurumunuzun ilgili usulleri "
        "çerçevesinde değerlendirilmesini arz ederim."
    )
    story.append(Paragraph(escape(petition), body))
    story.append(Paragraph(
        "Diğer katılımcının beyanı: " + escape(
            f"{partner['institution']} - {partner['title']} - {partner['employment']}"
        ), caption,
    ))
    if notes:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Başvuranın açıklaması", body))
        for paragraph in notes.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if paragraph.strip():
                story.append(Paragraph(escape(paragraph.strip()), body))
            else:
                story.append(Spacer(1, 3 * mm))

    story.extend([
        Spacer(1, 4 * mm),
        Paragraph("Ad soyad: " + escape(name), body),
        Paragraph("Tarih: ...............<br/>İmza: ...............", body),
        Spacer(1, 3 * mm),
        Paragraph(
            "Bu belge örnek ve varsayımsal bir başvuru taslağıdır. Kullanıcı tarafından "
            "önizlenmeli ve ilgili kurumun güncel şartlarına göre düzenlenmelidir. "
            "Platform; beyanları, mevzuat şartlarını veya kurum onayını doğrulamış sayılmaz. "
            "Bu çıktı kuruma gönderilmemiştir.",
            caption,
        ),
    ])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#546176"))
        canvas.drawString(22 * mm, 13 * mm, "DEMO - Kullanıcı önizlemesi için taslak")
        canvas.drawRightString(A4[0] - 22 * mm, 13 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
