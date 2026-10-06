"""Örnek alan davranışlarını denetler; gerçek mevzuat doğrulaması yapmaz."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from becayis.domain import (
    SEED_ADS, canonical_route, create_user_ad, discover_matches, filter_ads,
    is_sensitive_message, public_ad, revise_ad, source_versions_current, validate_ad, wants,
)

NOW = datetime(2026, 10, 6, 9, tzinfo=timezone.utc)
LATER = (NOW + timedelta(days=180)).isoformat()


def fixtures():
    ads = deepcopy(SEED_ADS[:3])
    for ad in ads:
        ad["expires_at"] = LATER
    return ads


class DomainTests(unittest.TestCase):
    def test_seed_catalog_is_valid_and_has_direct_and_three_way_matches(self):
        self.assertEqual(len(SEED_ADS), 10)
        self.assertTrue(all(not validate_ad(ad) for ad in SEED_ADS))
        ads = fixtures()
        matches = discover_matches(ads, now=NOW)
        self.assertEqual([match["kind"] for match in matches], [2, 3])
        self.assertTrue(all(match["legal_status"] == "unknown" and match["requires_review"] for match in matches))
        self.assertTrue(all(match["preference_score"] == 100 for match in matches))

    def test_district_wildcard_and_specific_district(self):
        a, b, _ = fixtures()
        a["targets"] = [{"province": "Ankara", "district": None, "priority": 1}]
        self.assertTrue(wants(a, b))
        a["targets"][0]["district"] = "Keçiören"
        self.assertFalse(wants(a, b))
        a["targets"][0]["district"] = "Çankaya"
        self.assertTrue(wants(a, b))

    def test_one_way_and_missing_cycle_closure_do_not_match(self):
        a, b, c = fixtures()
        b["targets"] = [{"province": "İzmir", "district": None, "priority": 1}]
        self.assertEqual(discover_matches([a, b], now=NOW), [])
        c["targets"] = [{"province": "Bursa", "district": None, "priority": 1}]
        self.assertEqual(discover_matches([a, b, c], now=NOW), [])

    def test_reverse_three_way_routes_are_distinct_and_rotations_deduplicate(self):
        ads = fixtures()
        for ad in ads:
            ad["targets"] = [{"province": other["current_province"], "district": None, "priority": 1}
                             for other in ads if other["id"] != ad["id"]]
        matches = discover_matches(ads, now=NOW)
        triples = [match for match in matches if match["kind"] == 3]
        self.assertEqual(len(triples), 2)
        self.assertNotEqual(triples[0]["id"], triples[1]["id"])
        self.assertEqual(canonical_route(["b", "c", "a"]), ("a", "b", "c"))
        self.assertEqual(canonical_route(["c", "b", "a"]), ("a", "c", "b"))
        self.assertEqual(matches, discover_matches(list(reversed(ads)), now=NOW))

    def test_duplicate_preferences_do_not_duplicate_matches(self):
        ads = fixtures()
        ads[0]["targets"] *= 3
        self.assertEqual(len(discover_matches(ads, now=NOW)), 2)

    def test_same_owner_and_technical_mismatch_are_excluded(self):
        for field in ("owner_id", "institution", "title", "employment"):
            ads = fixtures()[:2]
            ads[1][field] = ads[0][field] if field == "owner_id" else "different"
            self.assertEqual(discover_matches(ads, now=NOW), [])
        ads = fixtures()
        ads[2]["owner_id"] = ads[0]["owner_id"]
        self.assertFalse(any(match["kind"] == 3 for match in discover_matches(ads, now=NOW)))

    def test_closed_expired_boundary_and_invalid_expiry_are_excluded(self):
        for changes in ({"status": "CLOSED"}, {"status": "PAUSED"},
                        {"expires_at": NOW.isoformat()}, {"expires_at": "invalid"}):
            ads = fixtures()[:2]
            ads[1].update(changes)
            self.assertEqual(discover_matches(ads, now=NOW), [])

    def test_filters_search_public_fields_and_preserve_input(self):
        ads = fixtures()
        original = deepcopy(ads)
        selected = filter_ads(ads, institution="Sağlık Bakanlığı", title="Hemşire",
                              employment="4/B Sözleşmeli", current_province="İstanbul",
                              target_province="Ankara", query="İSTANBUL", now=NOW)
        self.assertEqual([ad["id"] for ad in selected], ["health-a"])
        selected[0]["note"] = "changed"
        self.assertEqual(ads, original)
        ads[0]["private_unit"] = "gizli-birim-kodu"
        self.assertEqual(filter_ads(ads, query="gizli-birim-kodu", now=NOW), [])

    def test_public_projection_hides_identity_and_private_unit(self):
        ad = fixtures()[0]
        ad.update({"full_name": "Sentetik İsim", "private_unit": "Sentetik Birim",
                   "phone": "05320000000", "tc_identity": "12345678901"})
        ad["targets"][0]["private_unit"] = "Hedef birim de gizlidir"
        projection = public_ad(ad)
        for field in ("owner_id", "full_name", "private_unit", "phone", "tc_identity"):
            self.assertNotIn(field, projection)
        self.assertEqual(projection["id"], ad["id"])
        self.assertNotIn("private_unit", projection["targets"][0])
        projection["targets"][0]["province"] = "İzmir"
        self.assertEqual(ad["targets"][0]["province"], "Ankara")

    def test_revision_invalidates_old_snapshot_and_keeps_original(self):
        ads = fixtures()[:2]
        match = discover_matches(ads, now=NOW)[0]
        self.assertTrue(source_versions_current(match, ads, now=NOW))
        changed = revise_ad(ads[0], {"note": "Yeni not"})
        self.assertEqual(changed["version"], 2)
        self.assertEqual(ads[0]["version"], 1)
        self.assertFalse(source_versions_current(match, [changed, ads[1]], now=NOW))
        self.assertNotEqual(match["id"], discover_matches([changed, ads[1]], now=NOW)[0]["id"])
        ads[1]["status"] = "CLOSED"
        self.assertFalse(source_versions_current(match, ads, now=NOW))

    def test_sensitive_content_warns_and_ordinary_message_passes(self):
        for text in ("TC 12345678901", "Telefonum 0532 123 45 67", "+90 (532) 123-45-67",
                     "Sen aptalsın, salak", "IBAN gönder kapora yatır", "https://fake.invalid"):
            self.assertTrue(is_sensitive_message(text), text)
        self.assertFalse(is_sensitive_message("Merhaba, Ankara hedefiniz hâlâ güncel mi?"))

    def test_create_and_validation_reject_invalid_data_and_immutable_id(self):
        seed = fixtures()[0]
        ad = create_user_ad(owner_id="demo-user", pseudonym="Yeni Rota",
                            institution=seed["institution"], title=seed["title"], employment=seed["employment"],
                            current_province="İstanbul", current_district="Kadıköy",
                            targets=seed["targets"], expires_at=LATER)
        self.assertEqual(validate_ad(ad), [])
        self.assertEqual(ad["version"], 1)
        with self.assertRaises(ValueError):
            revise_ad(ad, {"id": "other"})
        with self.assertRaises(ValueError):
            revise_ad(ad, {"current_district": "Çankaya"})
        with self.assertRaises(ValueError):
            discover_matches([ad, deepcopy(ad)], now=NOW)


if __name__ == "__main__":
    unittest.main()
