"""Eğitim demosu: gerçek mevzuat motoru veya kurum onay sistemi değildir.

Kurum/unvan/istihdam eşitliği yalnızca teknik aday elemesidir. Bütün önerilerin
hukuki durumu ``unknown`` kalır; %100 sadece yönlü yer tercihlerini ifade eder.
Üçlü rotalar resmi olarak izin verilmiş bir işlem gibi sunulmamalıdır.
Kullanıcı, ilan ve görev yeri verilerinin tamamı sentetiktir.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import unicodedata
from uuid import uuid4


LOCATIONS = {
    "İstanbul": ["Kadıköy", "Üsküdar", "Kağıthane", "Fatih", "Bakırköy"],
    "Ankara": ["Çankaya", "Keçiören", "Yenimahalle", "Altındağ"],
    "İzmir": ["Bornova", "Karşıyaka", "Konak", "Buca"],
    "Bursa": ["Nilüfer", "Osmangazi", "Yıldırım"],
    "Antalya": ["Muratpaşa", "Kepez", "Konyaaltı"],
    "Adana": ["Seyhan", "Çukurova", "Yüreğir"],
    "Konya": ["Selçuklu", "Meram", "Karatay"],
    "Samsun": ["Atakum", "İlkadım", "Canik"],
}
INSTITUTIONS = ["Sağlık Bakanlığı", "Millî Eğitim Bakanlığı", "Adalet Bakanlığı"]
TITLES = ["Hemşire", "Tıbbi Sekreter", "Öğretmen", "Zabıt Katibi", "İnfaz Koruma Memuru"]
EMPLOYMENT_TYPES = ["4/A Kadrolu", "4/B Sözleşmeli"]
STATUSES = {"ACTIVE", "PAUSED", "CLOSED"}
_REGIME = "3+1 durumu doğrulanmadı"


def _utc_datetime(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Tarih saat dilimi içeren ISO 8601 biçiminde olmalıdır.")
    return value.astimezone(timezone.utc)


def validate_ad(ad):
    """Hata mesajlarını döndürür; boş liste biçimsel doğrulamanın geçtiğini belirtir.

    Bu doğrulama mevzuat değerlendirmesi yapmaz. Kimlik, istihdam ve belge
    doğrulaması bir web demosunda yalnızca yer tutucudur.
    """
    if not isinstance(ad, dict):
        return ["İlan bir nesne olmalıdır."]
    errors = []
    for field in ("id", "owner_id", "institution", "title", "employment", "pseudonym"):
        if not isinstance(ad.get(field), str) or not ad[field].strip():
            errors.append(f"{field} alanı zorunludur.")
    if type(ad.get("version")) is not int or ad["version"] < 1:
        errors.append("version pozitif tamsayı olmalıdır.")
    if not isinstance(ad.get("status"), str) or ad["status"] not in STATUSES:
        errors.append("İlan durumu ACTIVE, PAUSED veya CLOSED olmalıdır.")
    for field in ("anonymous", "verified"):
        if type(ad.get(field)) is not bool:
            errors.append(f"{field} doğru/yanlış değeri olmalıdır.")
    province = ad.get("current_province")
    if not isinstance(province, str) or province not in LOCATIONS:
        errors.append("Mevcut il demo konum kataloğunda bulunmalıdır.")
    elif ad.get("current_district") not in LOCATIONS[province]:
        errors.append("Mevcut ilçe seçilen ile ait olmalıdır.")
    targets = ad.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append("En az bir hedef yer seçilmelidir.")
    else:
        for target in targets:
            if not isinstance(target, dict) or not isinstance(target.get("province"), str) or target["province"] not in LOCATIONS:
                errors.append("Hedef il demo konum kataloğunda bulunmalıdır.")
                continue
            if target.get("district") is not None and target["district"] not in LOCATIONS[target["province"]]:
                errors.append("Hedef ilçe seçilen ile ait olmalıdır.")
            priority = target.get("priority", 1)
            if type(priority) is not int or priority < 1:
                errors.append("Hedef önceliği pozitif tamsayı olmalıdır.")
    try:
        if not ad.get("expires_at"):
            raise ValueError("missing")
        _utc_datetime(ad["expires_at"])
    except (ValueError, TypeError, OverflowError):
        errors.append("İlan bitiş tarihi saat dilimi içermelidir.")
    if not isinstance(ad.get("note", ""), str):
        errors.append("İlan notu metin olmalıdır.")
    return errors


def is_active_ad(ad, *, now=None):
    """Bitiş anına ulaşan, bozuk tarihli ve kapalı ilanları dışarıda bırakır."""
    if not isinstance(ad, dict) or ad.get("status") != "ACTIVE":
        return False
    try:
        if not ad.get("expires_at"):
            return False
        return _utc_datetime(ad["expires_at"]) > _utc_datetime(now)
    except (ValueError, TypeError, OverflowError):
        return False


def wants(source, target):
    """A -> B: A, B'nin mevcut il/ilçesine gitmek istiyor. None ilçe wildcard."""
    return any(
        preference.get("province") == target.get("current_province")
        and (preference.get("district") is None
             or preference["district"] == target.get("current_district"))
        for preference in source.get("targets", [])
        if isinstance(preference, dict)
    )


def canonical_route(route):
    """Rotasyonları birleştirir; üçlü döngünün yönünü tersine çevirmez."""
    route = tuple(route)
    if len(route) < 2 or any(not isinstance(ad_id, str) or not ad_id for ad_id in route) or len(set(route)) != len(route):
        raise ValueError("Rotada en az iki farklı ilan bulunmalıdır.")
    return min(route[index:] + route[:index] for index in range(len(route)))


def _technical_compatible(source, target):
    return (
        source["owner_id"] != target["owner_id"]
        and all(source[field] == target[field] for field in ("institution", "title", "employment"))
    )


def discover_matches(ads, *, now=None):
    """2'li ve 3'lü koşullu öneriler; hiçbir sonuç hukuken onaylanmış sayılmaz.

    Sonuç: {id, kind, route, preference_score, legal_status, requires_review,
            source_versions}. Kaynak sürümleri onay anında yeniden denetlenir.
    Kenar oluşturma O(V²), üçlü keşif yoğun grafikte O(V³). Demo ölçeğindedir.
    """
    now = _utc_datetime(now)
    by_id = {}
    for ad in ads:
        ad_id = ad.get("id") if isinstance(ad, dict) else None
        if not isinstance(ad_id, str) or not ad_id:
            continue
        if ad_id in by_id:
            raise ValueError("Aynı ilan kimliği birden fazla kez kullanılamaz.")
        by_id[ad_id] = ad
    candidates = {
        ad_id: ad for ad_id, ad in by_id.items()
        if not validate_ad(ad) and is_active_ad(ad, now=now)
    }
    adj = {ad_id: set() for ad_id in candidates}
    for a_id, a in candidates.items():
        for b_id, b in candidates.items():
            if a_id != b_id and _technical_compatible(a, b) and wants(a, b):
                adj[a_id].add(b_id)
    found = {}

    def emit(raw_route):
        route = canonical_route(raw_route)
        if route in found:
            return
        if len({candidates[ad_id]["owner_id"] for ad_id in route}) != len(route):
            return
        versions = {ad_id: candidates[ad_id]["version"] for ad_id in route}
        signature = json.dumps({"route": route, "versions": versions}, ensure_ascii=False, sort_keys=True)
        found[route] = {
            "id": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20],
            "kind": len(route), "route": list(route), "preference_score": 100,
            "legal_status": "unknown", "requires_review": True,
            "source_versions": versions,
        }

    for a_id, neighbours in adj.items():
        for b_id in neighbours:
            if a_id in adj[b_id]:
                emit([a_id, b_id])
            for c_id in adj[b_id]:
                if c_id not in (a_id, b_id) and a_id in adj[c_id]:
                    emit([a_id, b_id, c_id])
    return sorted(found.values(), key=lambda match: (match["kind"], match["route"]))


def source_versions_current(match, ads, *, now=None):
    """Kaynak ilanların hala aktif, aynı sürümde ve aynı rotada olduğunu denetler."""
    now = _utc_datetime(now)
    route = match.get("route", [])
    if match.get("kind") != len(route) or len(route) not in (2, 3) or len(set(route)) != len(route):
        return False
    by_id = {ad.get("id"): ad for ad in ads if isinstance(ad, dict)}
    versions = match.get("source_versions", {})
    if set(versions) != set(route):
        return False
    for ad_id in route:
        ad = by_id.get(ad_id)
        if ad is None or validate_ad(ad) or not is_active_ad(ad, now=now) or ad["version"] != versions[ad_id]:
            return False
    if len({by_id[ad_id]["owner_id"] for ad_id in route}) != len(route):
        return False
    return all(
        _technical_compatible(by_id[a_id], by_id[route[(index + 1) % len(route)]])
        and wants(by_id[a_id], by_id[route[(index + 1) % len(route)]])
        for index, a_id in enumerate(route)
    )


def revise_ad(ad, changes):
    """Yeni bir kopya ve artırılmış version döndürür; kaynak nesneyi değiştirmez."""
    if any(field in changes for field in ("id", "owner_id", "version")):
        raise ValueError("İlan kimliği, sahibi veya sürümü doğrudan değiştirilemez.")
    revised = deepcopy(ad)
    revised.update(deepcopy(changes))
    revised["version"] = ad["version"] + 1
    errors = validate_ad(revised)
    if errors:
        raise ValueError(" ".join(errors))
    return revised


def create_user_ad(*, owner_id, pseudonym, institution, title, employment,
                   current_province, current_district, targets, regime="Belirtilmedi",
                   anonymous=True, verified=False, note="", expires_at=None):
    """Demo ilanı oluşturur; verified seçeneği gerçek bir belge doğrulaması değildir."""
    ad = {
        "id": f"ad-{uuid4().hex[:12]}", "owner_id": owner_id, "pseudonym": pseudonym,
        "institution": institution, "title": title, "employment": employment,
        "regime": regime, "current_province": current_province, "current_district": current_district,
        "targets": deepcopy(targets), "anonymous": anonymous, "verified": verified,
        "status": "ACTIVE", "version": 1,
        "expires_at": expires_at or (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
        "note": note,
    }
    errors = validate_ad(ad)
    if errors:
        raise ValueError(" ".join(errors))
    return ad


def normalize_text(text):
    text = unicodedata.normalize("NFKD", str(text).casefold())
    return "".join(character for character in text if not unicodedata.combining(character)).replace("ı", "i")


def filter_ads(ads, institution=None, title=None, employment=None,
               current_province=None, target_province=None, query="", *, now=None):
    """Aktif ilanları filtreler; alan modeli döner. Kamusal gösterim için public_ad kullanın."""
    now = _utc_datetime(now)
    result = []
    for ad in ads:
        if validate_ad(ad) or not is_active_ad(ad, now=now):
            continue
        filters = {"institution": institution, "title": title, "employment": employment,
                   "current_province": current_province}
        if any(value and ad.get(field) != value for field, value in filters.items()):
            continue
        if target_province and not any(target["province"] == target_province for target in ad["targets"]):
            continue
        if query:
            values = [str(ad.get(field, "")) for field in (
                "pseudonym", "institution", "title", "employment", "regime", "current_province", "current_district", "note")]
            values.extend(f"{target['province']} {target.get('district') or ''}" for target in ad["targets"])
            if normalize_text(query) not in normalize_text(" ".join(values)):
                continue
        result.append(deepcopy(ad))
    return result


_PUBLIC_FIELDS = (
    "id", "pseudonym", "institution", "title", "employment", "regime",
    "current_province", "current_district", "targets", "anonymous", "verified",
    "status", "version", "expires_at", "note",
)


def public_ad(ad):
    """İzin verilen alanları çıkarır; owner/name/unit/telefon/TCKN hiçbir zaman taşınmaz.

    id, kullanıcı kimliği değildir: ilan rotalarını bağlayan opak referanstır.
    Serbest metin kullanıcıların kimlik açıklamasına izin verebilir; arayüz ayrıca
    hassas içerik uyarısı vermelidir. Bu çıktı otomatik anonimleştirme garantisi değildir.
    """
    projection = {field: deepcopy(ad[field]) for field in _PUBLIC_FIELDS if field in ad}
    projection["targets"] = [
        {field: deepcopy(target[field]) for field in ("province", "district", "priority") if field in target}
        for target in ad.get("targets", []) if isinstance(target, dict)
    ]
    return projection


def is_sensitive_message(text):
    """Temel demo uyarısı; kapsamlı spam/küfür/kişisel veri tespiti garantisi vermez."""
    text = str(text)
    for candidate in re.findall(r"(?<!\w)\+?\d(?:[\d\s().-]{8,}\d)(?!\w)", text):
        if 10 <= len(re.sub(r"\D", "", candidate)) <= 13:
            return True
    normalized = normalize_text(text)
    words = set(re.findall(r"\w+", normalized))
    if words.intersection({"salak", "aptal", "serefsiz", "gerizekali", "orospu", "siktir"}):
        return True
    return any(pattern in normalized for pattern in (
        "kapora", "iban", "garanti becayis", "garanti tayin", "hemen para", "https://", "http://", "www.",
    ))


def _seed_ad(ad_id, province, district, targets, *, pseudonym, institution="Sağlık Bakanlığı",
             title="Hemşire", employment="4/B Sözleşmeli", anonymous=True, verified=False):
    return {
        "id": ad_id, "owner_id": f"synthetic-owner-{ad_id}", "pseudonym": pseudonym,
        "institution": institution, "title": title, "employment": employment,
        "regime": _REGIME if employment == "4/B Sözleşmeli" else "Kadrolu · koşullar doğrulanmadı",
        "current_province": province, "current_district": district,
        "targets": [{"province": target[0], "district": target[1], "priority": index + 1}
                    for index, target in enumerate(targets)],
        "anonymous": anonymous, "verified": verified, "status": "ACTIVE", "version": 1,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=180)).isoformat(),
        "note": "Sentetik demo ilanıdır. Kurum ve mevzuat koşulları ayrıca incelenmelidir.",
    }


SEED_ADS = [
    # a<->b doğrudan; a->b->c->a üçlü yönlü rota. b'nin ikinci hedefi İzmir.
    _seed_ad("health-a", "İstanbul", "Kadıköy", [("Ankara", "Çankaya")], pseudonym="Mavi Rota", verified=True),
    _seed_ad("health-b", "Ankara", "Çankaya", [("İstanbul", "Kadıköy"), ("İzmir", "Bornova")], pseudonym="Başkent Rota"),
    _seed_ad("health-c", "İzmir", "Bornova", [("İstanbul", None)], pseudonym="Ege Rota", verified=True),
    _seed_ad("health-d", "Bursa", "Nilüfer", [("İzmir", None)], pseudonym="Yeşil Rota"),
    _seed_ad("health-e", "Ankara", "Keçiören", [("İstanbul", None)], pseudonym="Kuzey Rota", employment="4/A Kadrolu"),
    _seed_ad("justice-a", "İstanbul", "Kağıthane", [("Ankara", "Çankaya")], pseudonym="Adalet Rota 1",
             institution="Adalet Bakanlığı", title="Zabıt Katibi"),
    _seed_ad("justice-b", "Ankara", "Çankaya", [("İstanbul", None)], pseudonym="Adalet Rota 2",
             institution="Adalet Bakanlığı", title="Zabıt Katibi", verified=True),
    _seed_ad("education-a", "İzmir", "Karşıyaka", [("Bursa", "Nilüfer")], pseudonym="Eğitim Rota 1",
             institution="Millî Eğitim Bakanlığı", title="Öğretmen", employment="4/A Kadrolu"),
    _seed_ad("education-b", "Bursa", "Nilüfer", [("İzmir", None)], pseudonym="Eğitim Rota 2",
             institution="Millî Eğitim Bakanlığı", title="Öğretmen", employment="4/A Kadrolu", anonymous=False),
    _seed_ad("health-secretary", "İstanbul", "Üsküdar", [("Antalya", "Muratpaşa")], pseudonym="Akdeniz Rota", title="Tıbbi Sekreter"),
]
