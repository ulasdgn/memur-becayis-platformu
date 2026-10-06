"""Streamlit demo akışlarını gerçek widget etkileşimleriyle denetler.

Bu testler gerçek kullanıcı kimlik doğrulaması veya WebSocket güvenliği kanıtı
değildir; oturuma özel demonstrasyonun görünür davranışını sınar.
"""
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
        self.assert_healthy()

    def assert_healthy(self):
        self.assertEqual([error.message for error in self.app.exception], [])

    def navigate(self, page):
        self.app.radio(key="page").set_value(page).run()
        self.assert_healthy()

    def contact_buttons(self):
        return [button for button in self.app.button
                if (button.key or "").startswith("contact-")]

    def enabled_accept_button(self):
        return next(button for button in self.app.button
                    if (button.key or "").startswith("accept-") and not button.disabled)

    def open_direct_matches(self):
        self.navigate("Eşleşmeler")
        self.app.radio(key="match-mode").set_value("İkili").run()
        self.assert_healthy()

    def accept_own_direct_match(self):
        self.open_direct_matches()
        button = self.enabled_accept_button()
        match_id = button.key.removeprefix("accept-")
        button.click().run()
        self.assert_healthy()
        return match_id

    def active_conversation(self):
        conversations = self.app.session_state["conversations"]
        self.assertEqual(len(conversations), 1)
        return next(iter(conversations.values()))

    def test_initial_page_renders_seed_ads_and_disables_own_contact(self):
        keys = {button.key for button in self.contact_buttons()}
        self.assertTrue({"contact-health-a", "contact-health-b", "contact-health-c"}.issubset(keys))
        self.assertTrue(self.app.button(key="contact-health-a").disabled)
        self.assertFalse(self.app.button(key="contact-health-b").disabled)
        self.assertEqual(self.app.radio(key="page").value, "İlanlar")

    def test_navigation_between_all_five_pages_has_no_exception(self):
        for page in ("İlanlar", "Eşleşmeler", "İlan oluştur", "Mesajlar", "Rehber", "İlanlar"):
            with self.subTest(page=page):
                self.navigate(page)
                self.assertEqual(self.app.radio(key="page").value, page)

    def test_search_and_conflicting_catalog_filters_show_empty_state(self):
        self.app.text_input(key="search").set_value("bu-demoda-bulunmayan-rotaxyz").run()
        self.assert_healthy()
        self.assertEqual(self.contact_buttons(), [])
        self.assertTrue(any("ilan bulunamadı" in info.value for info in self.app.info))

        self.app.text_input(key="search").set_value("").run()
        self.app.selectbox(key="filter-institution").set_value("Adalet Bakanlığı")
        self.app.selectbox(key="filter-title").set_value("Hemşire").run()
        self.assert_healthy()
        self.assertEqual(self.contact_buttons(), [])
        self.assertTrue(any("ilan bulunamadı" in info.value for info in self.app.info))

    def test_create_ad_requires_at_least_one_target_and_preserves_records(self):
        self.navigate("İlan oluştur")
        original_count = len(self.app.session_state["ads"])
        self.app.multiselect(key="create-targets").set_value([]).run()
        self.app.button(key="publish-ad").click().run()
        self.assert_healthy()
        self.assertEqual(len(self.app.session_state["ads"]), original_count)
        self.assertFalse(any(ad["owner_id"] == "demo-visitor" for ad in self.app.session_state["ads"]))
        self.assertEqual(self.app.radio(key="page").value, "İlan oluştur")
        self.assertTrue(any("en az bir hedef" in error.value for error in self.app.error))

    def test_valid_ad_selects_visitor_and_displays_its_direct_match(self):
        self.navigate("İlan oluştur")
        original_count = len(self.app.session_state["ads"])
        self.app.text_input(key="create-alias").set_value("Test Rotası")
        self.app.multiselect(key="create-targets").set_value(["Ankara"]).run()
        self.app.button(key="publish-ad").click().run()
        self.assert_healthy()

        ads = self.app.session_state["ads"]
        visitor_ads = [ad for ad in ads if ad["owner_id"] == "demo-visitor"]
        self.assertEqual(len(ads), original_count + 1)
        self.assertEqual(len(visitor_ads), 1)
        self.assertEqual(visitor_ads[0]["pseudonym"], "Test Rotası")
        self.assertTrue(visitor_ads[0]["anonymous"])
        self.assertEqual(self.app.selectbox(key="actor_choice").value, "demo-visitor")
        self.assertEqual(self.app.radio(key="page").value, "Eşleşmeler")

        self.app.checkbox(key="match-mine").set_value(True)
        self.app.radio(key="match-mode").set_value("İkili").run()
        self.assert_healthy()
        self.assertTrue(any((button.key or "").startswith("accept-") and not button.disabled
                            for button in self.app.button))

    def test_listing_contact_opens_the_selected_peer_conversation(self):
        self.app.button(key="contact-health-c").click().run()
        self.assert_healthy()
        self.assertEqual(self.app.radio(key="page").value, "Mesajlar")
        self.assertEqual(self.app.selectbox(key="chat-contact-synthetic-owner-health-a").value, "health-c")
        self.assertEqual(self.active_conversation()[0]["sender"], "synthetic-owner-health-c")

    def test_match_contact_routes_to_the_next_participant(self):
        self.open_direct_matches()
        match_id = self.enabled_accept_button().key.removeprefix("accept-")
        self.app.button(key=f"match-chat-{match_id}").click().run()
        self.assert_healthy()
        self.assertEqual(self.app.radio(key="page").value, "Mesajlar")
        self.assertEqual(self.app.selectbox(key="chat-contact-synthetic-owner-health-a").value, "health-b")

    def test_normal_chat_adds_user_message_and_explicit_demo_reply(self):
        self.navigate("Mesajlar")
        before = len(self.active_conversation())
        text = "Merhaba, Ankara hedefiniz hâlâ güncel mi?"
        self.app.chat_input[0].set_value(text).run()
        self.assert_healthy()
        messages = self.active_conversation()
        self.assertEqual(len(messages), before + 2)
        self.assertEqual(messages[-2]["body"], text)
        self.assertEqual(messages[-2]["sender"], "synthetic-owner-health-a")
        self.assertTrue(messages[-1]["body"].startswith("Örnek yanıt:"))
        self.assertEqual(len(self.app.chat_message), len(messages))

    def test_sensitive_chat_is_rejected_without_appending_or_replying(self):
        self.navigate("Mesajlar")
        before = len(self.active_conversation())
        self.app.chat_input[0].set_value("Telefonum 0532 123 45 67").run()
        self.assert_healthy()
        self.assertEqual(len(self.active_conversation()), before)
        self.assertTrue(any("hassas veri" in error.value for error in self.app.error))
        self.assertFalse(any("0532" in message["body"] for message in self.active_conversation()))

    def test_own_acceptance_does_not_vote_for_other_participants(self):
        match_id = self.accept_own_direct_match()
        votes = self.app.session_state["decisions"][match_id]
        self.assertEqual(votes, {"health-a": "accepted"})
        self.assertTrue(any(button.key == f"simulate-{match_id}" for button in self.app.button))
        self.assertEqual(len(self.app.download_button), 0)

    def test_simulated_peer_acceptance_enables_pdf_download(self):
        match_id = self.accept_own_direct_match()
        self.app.button(key=f"simulate-{match_id}").click().run()
        self.assert_healthy()
        self.assertEqual(self.app.session_state["decisions"][match_id],
                         {"health-a": "accepted", "health-b": "accepted"})
        downloads = [button for button in self.app.download_button if button.key == f"pdf-{match_id}"]
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0].label, "Dilekçe taslağını PDF indir")
        self.assertTrue(downloads[0].proto.url.endswith(".pdf"))

    def test_nonparticipant_profile_cannot_accept_another_route(self):
        self.app.selectbox(key="actor_choice").set_value("synthetic-owner-health-secretary").run()
        self.open_direct_matches()
        buttons = [button for button in self.app.button if (button.key or "").startswith("accept-")]
        self.assertTrue(buttons)
        self.assertTrue(all(button.disabled for button in buttons))

    def test_three_way_demo_approvals_do_not_enable_official_petition(self):
        self.navigate("Eşleşmeler")
        self.app.radio(key="match-mode").set_value("Üçlü").run()
        button = self.enabled_accept_button()
        match_id = button.key.removeprefix("accept-")
        button.click().run()
        self.app.button(key=f"simulate-{match_id}").click().run()
        self.assert_healthy()
        self.assertEqual(len(self.app.session_state["decisions"][match_id]), 3)
        self.assertEqual(len(self.app.download_button), 0)
        self.assertTrue(any("resmî dilekçe üretmez" in caption.value for caption in self.app.caption))

    def test_saved_ads_are_isolated_between_demo_sessions(self):
        self.app.button(key="save-health-b").click().run()
        self.assert_healthy()
        self.assertIn("health-b", self.app.session_state["favorites"])
        other = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
        self.assertEqual([error.message for error in other.exception], [])
        self.assertEqual(other.session_state["favorites"], set())


if __name__ == "__main__":
    unittest.main()
