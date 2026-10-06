"""Streamlit başlangıç demosu. Tüm kayıtlar ziyaretçinin oturumuna özeldir."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from becayis.domain import (
    EMPLOYMENT_TYPES, INSTITUTIONS, LOCATIONS, SEED_ADS, TITLES,
    create_user_ad, discover_matches, filter_ads, is_sensitive_message,
    public_ad, revise_ad, source_versions_current,
)
from becayis.pdf_export import make_petition_pdf

ROOT = Path(__file__).resolve().parent
PAGES = ["İlanlar", "Eşleşmeler", "İlan oluştur", "Mesajlar", "Rehber"]
st.set_page_config(page_title="Memur Becayiş | Demo", page_icon="↔", layout="wide")
st.markdown(f"<style>{(ROOT / 'assets/style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def initialize():
    defaults = {
        "ads": deepcopy(SEED_ADS), "favorites": set(), "decisions": {},
        "conversations": {}, "contact_ad_id": None, "flash": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "pending_page" in st.session_state:
        st.session_state["page"] = st.session_state.pop("pending_page")
    if "pending_actor" in st.session_state:
        st.session_state["actor_choice"] = st.session_state.pop("pending_actor")
    if "pending_contact" in st.session_state:
        owner = st.session_state.get("actor_choice", SEED_ADS[0]["owner_id"])
        st.session_state[f"chat-contact-{owner}"] = st.session_state.pop("pending_contact")


def go(page, contact=None):
    st.session_state.pending_page = page
    if contact:
        st.session_state.contact_ad_id = contact
        st.session_state.pending_contact = contact
    st.rerun()


def section(title, description, count=None):
    tag = f'<span class="section-count">{escape(str(count))}</span>' if count is not None else ""
    st.markdown(f'<div class="section-lead"><div><h2>{escape(title)}</h2><p>{escape(description)}</p></div>{tag}</div>', unsafe_allow_html=True)


def find_ad(ad_id):
    return next((ad for ad in st.session_state.ads if ad["id"] == ad_id), None)


def actor_ad():
    return next(ad for ad in st.session_state.ads if ad["owner_id"] == st.session_state.actor_choice)


def target_text(ad):
    return ", ".join(t["province"] + (f" / {t['district']}" if t.get("district") else "") for t in ad["targets"])


def show_ad_card(ad):
    data = public_ad(ad)
    with st.container(border=True):
        badges = '<span class="chip teal">Örnek doğrulama rozeti</span>' if data["verified"] else ""
        privacy = "Ad ve kesin birim gizli" if data["anonymous"] else "Örnek açık profil"
        initial = escape(data["pseudonym"][0])
        st.markdown(f'''
        <div class="ad-top"><div class="avatar">{initial}</div><div>
        <div class="ad-name">{escape(data['pseudonym'])}</div><div class="ad-sub">{escape(privacy)} · sentetik ilan</div></div></div>
        <div class="chips"><span class="chip">{escape(data['institution'])}</span><span class="chip">{escape(data['title'])}</span><span class="chip">{escape(data['employment'])}</span>{badges}</div>
        <div class="route-box"><div><small>Mevcut görev yeri</small><strong>{escape(data['current_province'])}</strong><div class="district">{escape(data['current_district'])}</div></div><div class="route-arrow">→</div><div><small>Gitmek istediği</small><strong>{escape(data['targets'][0]['province'])}</strong><div class="district">{escape(target_text(data))}</div></div></div>
        <div class="note">{escape(data.get('note', ''))}</div>''', unsafe_allow_html=True)
        a, b = st.columns([3, 1])
        own = data["id"] == actor_ad()["id"]
        with a:
            if st.button("Sohbet senaryosunu aç", key=f"contact-{data['id']}", disabled=own, use_container_width=True):
                go("Mesajlar", data["id"])
        with b:
            saved = data["id"] in st.session_state.favorites
            if st.button("Kaydedildi" if saved else "Kaydet", key=f"save-{data['id']}", use_container_width=True):
                if saved:
                    st.session_state.favorites.remove(data["id"])
                else:
                    st.session_state.favorites.add(data["id"])
                st.rerun()


def listing_page():
    st.markdown('''<div class="hero"><div class="eyebrow">Birlikte yeni bir başlangıç</div><h1>Yeni görevinize giden yolu<br>birlikte bulun.</h1><p>Kurumunuza ve unvanınıza uygun ilanları keşfedin. Karşılıklı yer tercihlerini görün, olası rotaları değerlendirin.</p><div class="hero-tags"><span>↔ İkili eşleştirme</span><span>△ Üçlü rota keşfi</span><span>◉ Ad ve birim gizliliği</span></div></div>''', unsafe_allow_html=True)
    matches = discover_matches(st.session_state.ads)
    values = [(len(filter_ads(st.session_state.ads)), "Örnek aktif ilan"), (sum(m["kind"] == 2 for m in matches), "İkili öneri"), (sum(m["kind"] == 3 for m in matches), "Üçlü rota"), (len(st.session_state.favorites), "Kaydettiğiniz ilan")]
    st.markdown('<div class="stats-grid">' + ''.join(f'<div class="stat"><strong>{n}</strong><span>{label}</span></div>' for n, label in values) + '</div>', unsafe_allow_html=True)
    query = st.text_input("İlanlarda ara", placeholder="İl, ilçe, unvan veya ilan notu…", key="search")
    with st.expander("Arama filtreleri", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            institution = st.selectbox("Kurum", ["Tümü"] + INSTITUTIONS, key="filter-institution")
            current = st.selectbox("Mevcut il", ["Tümü"] + list(LOCATIONS), key="filter-current")
        with c2:
            title = st.selectbox("Unvan / branş", ["Tümü"] + TITLES, key="filter-title")
            target = st.selectbox("Hedef il", ["Tümü"] + list(LOCATIONS), key="filter-target")
        with c3:
            employment = st.selectbox("İstihdam türü", ["Tümü"] + EMPLOYMENT_TYPES, key="filter-employment")
            only_saved = st.checkbox("Yalnız kaydettiklerim", key="filter-saved")
    none_if_all = lambda value: None if value == "Tümü" else value
    ads = filter_ads(st.session_state.ads, institution=none_if_all(institution), title=none_if_all(title), employment=none_if_all(employment), current_province=none_if_all(current), target_province=none_if_all(target), query=query)
    if only_saved:
        ads = [ad for ad in ads if ad["id"] in st.session_state.favorites]
    section("İlanları keşfedin", "Yer tercihleriniz için açık bir başlangıç.", f"{len(ads)} ilan")
    if not ads:
        st.info("Bu filtrelerle ilan bulunamadı. Filtreleri genişletebilir veya kendi ilanınızı oluşturabilirsiniz.")
    columns = st.columns(2)
    for index, ad in enumerate(ads):
        with columns[index % 2]:
            show_ad_card(ad)


def matches_page():
    section("Olası becayiş rotaları", "Yer tercihi uyumu ile mevzuat değerlendirmesi ayrı gösterilir.")
    mode = st.radio("Öneri türü", ["Tüm öneriler", "İkili", "Üçlü"], horizontal=True, key="match-mode")
    mine = st.checkbox("Yalnız seçili demo profilimin önerileri", value=False, key="match-mine")
    actor = actor_ad()
    matches = discover_matches(st.session_state.ads)
    if mode != "Tüm öneriler":
        matches = [m for m in matches if m["kind"] == (2 if mode == "İkili" else 3)]
    if mine:
        matches = [m for m in matches if actor["id"] in m["route"]]
    if not matches:
        st.info("Bu profil ve öneri türü için kapalı döngü bulunamadı.")
    for match in matches:
        with st.container(border=True):
            members = [find_ad(ad_id) for ad_id in match["route"]]
            title = "İkili karşılıklı tercih" if match["kind"] == 2 else "Üçlü kapalı rota"
            st.markdown(f'<div class="match-head"><div><strong>{title}</strong><div class="note">{escape(members[0]["institution"])} · {escape(members[0]["title"])}</div></div><div class="score">%100<small>Yer tercihi uyumu</small></div></div>', unsafe_allow_html=True)
            route = ''.join(f'<div class="cycle-stop">{escape(ad["current_province"])}<small>{escape(ad["pseudonym"])}</small></div><span>→</span>' for ad in members)
            st.markdown(f'<div class="cycle-route">{route}<div class="cycle-stop">{escape(members[0]["current_province"])}</div></div><div class="legal-note">Mevzuat durumu: inceleme gerekli. Bu öneri kurum onayı değildir.</div>', unsafe_allow_html=True)
            with st.expander("Rota ayrıntıları ve taraf kararları"):
                votes = st.session_state.decisions.setdefault(match["id"], {})
                for i, ad in enumerate(members):
                    destination = members[(i + 1) % len(members)]
                    state = "Kabul etti (demo)" if votes.get(ad["id"]) == "accepted" else "Bekliyor"
                    st.write(f"{ad['pseudonym']}: {ad['current_province']} → {destination['current_province']} · {state}")
                participates = actor["id"] in match["route"]
                if st.button("Bu öneriyi kabul et", key=f"accept-{match['id']}", disabled=not participates):
                    if source_versions_current(match, st.session_state.ads):
                        votes[actor["id"]] = "accepted"
                        st.session_state.flash = "Seçili demo profilinin kararı kaydedildi. Diğer tarafların kararı ayrı tutulur."
                        st.rerun()
                    else:
                        st.error("Kaynak ilan değişti. Güncel öneriyi yeniden değerlendirin.")
                if not participates:
                    st.caption("Kabul akışını denemek için yan menüden bu rotadaki bir demo profilini seçin.")
                if participates and votes.get(actor["id"]) == "accepted":
                    if st.button("Diğer tarafların örnek onaylarını ekle", key=f"simulate-{match['id']}"):
                        if source_versions_current(match, st.session_state.ads):
                            for ad in members:
                                votes[ad["id"]] = "accepted"
                            st.rerun()
                    st.caption("Bu düğme yalnız demo senaryosunu ilerletir; gerçek kişiler adına onay vermez.")
                all_accepted = all(votes.get(ad["id"]) == "accepted" for ad in members)
                if match["kind"] == 2 and participates and all_accepted:
                    applicant = actor
                    partner = next(ad for ad in members if ad["id"] != actor["id"])
                    st.success("Örnek taraf kararları tamamlandı. Başvuru taslağını inceleyebilirsiniz.")
                    name = st.text_input("Taslakta kullanılacak örnek ad", value="Demo Kullanıcısı", max_chars=150, key=f"pdf-name-{match['id']}")
                    pdf = make_petition_pdf({**applicant, "notes": applicant.get("note", "")}, partner, name.strip() or "Demo Kullanıcısı")
                    st.download_button("Dilekçe taslağını PDF indir", data=pdf, file_name="becayis-talep-taslagi.pdf", mime="application/pdf", key=f"pdf-{match['id']}")
                    st.caption("Taslak indirilir; herhangi bir kuruma gönderim yapılmaz.")
                elif match["kind"] == 3:
                    st.caption("Üçlü rotanın uygulanabilirliği ayrıca kurum incelemesi gerektirir. Demo bu rota için resmî dilekçe üretmez.")
            if participates:
                next_id = match["route"][(match["route"].index(actor["id"]) + 1) % len(match["route"])]
                if st.button("Sohbet senaryosunu aç", key=f"match-chat-{match['id']}"):
                    go("Mesajlar", next_id)


def create_page():
    section("Kendi rotanızı oluşturun", "Demo için örnek bilgi kullanın. İlanınız yalnız bu tarayıcı oturumunda saklanır.")
    own = next((ad for ad in st.session_state.ads if ad["owner_id"] == "demo-visitor"), None)
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            alias = st.text_input("Görünen takma ad", value=own["pseudonym"] if own else "Benim Rotam", max_chars=60, key="create-alias")
            institution = st.selectbox("Bağlı kurum", INSTITUTIONS, key="create-institution")
            title = st.selectbox("Unvan / branş", TITLES, key="create-title")
            employment = st.selectbox("İstihdam türü", EMPLOYMENT_TYPES, index=1, key="create-employment")
            regime = st.selectbox("Personel rejimi / aşaması", ["İnceleme gerekiyor", "3+1 sözleşmeli aşama", "Kadroya geçiş sonrası", "Genel / kurum özel rejimi"], key="create-regime")
        with c2:
            province = st.selectbox("Mevcut görev ili", list(LOCATIONS), key="create-province")
            district = st.selectbox("Mevcut görev ilçesi", LOCATIONS[province], key="create-district")
            targets = st.multiselect("Hedef iller (seçim sırası önceliktir)", list(LOCATIONS), default=["Ankara"], key="create-targets")
            target_district = None
            if targets:
                selected = st.selectbox("İlk hedefin ilçesi", ["İlin tüm ilçeleri"] + LOCATIONS[targets[0]], key="create-target-district")
                target_district = None if selected == "İlin tüm ilçeleri" else selected
            anonymous = st.checkbox("Ad ve kesin birimi gizle", value=True, key="create-anonymous")
        with st.expander("Ek personel bilgileri (örnek beyan)"):
            service_class = st.selectbox("Hizmet sınıfı", ["Bilinmiyor / uygulanamaz", "Sağlık ve Yardımcı Sağlık Hizmetleri", "Genel İdare Hizmetleri", "Eğitim ve Öğretim Hizmetleri"], key="create-service")
            unit = st.text_input("Örnek görev birimi (kartlarda gösterilmez)", max_chars=150, key="create-unit")
            grade = step = None
            if employment == "4/A Kadrolu":
                grade = st.number_input("Derece", min_value=1, max_value=15, value=8, key="create-grade")
                step = st.number_input("Kademe", min_value=1, max_value=9, value=1, key="create-step")
            st.caption("Bu bilgiler demo beyanıdır; süre ve kurum koşulları hukuken doğrulanmaz.")
        note = st.text_area("İlan notu (isteğe bağlı)", placeholder="Tercihiniz hakkında kısa bir not…", max_chars=1000, key="create-note")
        if st.button("İlanı güncelle" if own else "İlanı yayınla", type="primary", key="publish-ad"):
            if not alias.strip() or not targets:
                st.error("Takma ad ve en az bir hedef il gereklidir.")
            elif is_sensitive_message(note) or is_sensitive_message(alias):
                st.error("Notunuzda veya takma adınızda hassas bilgi/spam örüntüsü bulundu. Demo için örnek ve kişisel veri içermeyen metin kullanın.")
            else:
                preferences = [{"province": p, "district": target_district if i == 0 else None, "priority": i + 1} for i, p in enumerate(targets)]
                changes = dict(pseudonym=alias.strip(), institution=institution, title=title, employment=employment, regime=regime, current_province=province, current_district=district, targets=preferences, anonymous=anonymous, note=note.strip(), verified=False)
                if own:
                    created = revise_ad(own, changes)
                    st.session_state.ads = [created if ad["id"] == own["id"] else ad for ad in st.session_state.ads]
                else:
                    created = create_user_ad(owner_id="demo-visitor", **changes)
                    st.session_state.ads.append(created)
                created.update(unit=unit, service_class=service_class, grade=grade, step=step)
                st.session_state.pending_actor = "demo-visitor"
                st.session_state.pending_page = "Eşleşmeler"
                st.session_state.flash = "Demo ilanınız yayınlandı. Eşleşmeler güncel tercihlerinizle hesaplandı."
                st.rerun()


def messages_page():
    section("Sohbet senaryosu", "İletişim akışını örnek bir konuşma üzerinde deneyin.")
    actor = actor_ad()
    contacts = [ad for ad in st.session_state.ads if ad["owner_id"] != actor["owner_id"]]
    ids = [ad["id"] for ad in contacts]
    if not ids:
        st.info("Örnek konuşma için başka bir ilan bulunamadı.")
        return
    selected = st.session_state.contact_ad_id
    default_index = ids.index(selected) if selected in ids else 0
    contact_labels = {ad["id"]: f"{ad['pseudonym']} · {ad['current_province']}" for ad in contacts}
    contact_key = f"chat-contact-{actor['owner_id']}"
    contact_id = st.selectbox("Örnek konuşma", ids, index=None if contact_key in st.session_state else default_index, format_func=contact_labels.__getitem__, key=contact_key)
    peer = find_ad(contact_id)
    key = "|".join(sorted([actor["owner_id"], peer["owner_id"]]))
    conversation = st.session_state.conversations.setdefault(key, [{"sender": peer["owner_id"], "body": "Merhaba! Yer tercihlerini ve kurum koşullarını birlikte değerlendirebiliriz.", "time": "Örnek mesaj"}])
    st.caption("Karşı taraf örnek yanıt üretir. Mesajlar gerçek bir kişiye gönderilmez; yalnız bu oturumda tutulur.")
    for message in conversation:
        role = "user" if message["sender"] == actor["owner_id"] else "assistant"
        with st.chat_message(role):
            st.write(message["body"])
            st.caption(message["time"])
    body = st.chat_input("Kişisel bilgi içermeyen bir örnek mesaj yazın", max_chars=1000, key=f"chat-input-{key}")
    if body:
        if is_sensitive_message(body):
            st.error("Demo filtresi hassas veri veya spam örüntüsü algıladı. Telefon/TCKN/ödeme bilgisi paylaşmadan yeniden yazın.")
        else:
            stamp = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%H:%M")
            conversation.append({"sender": actor["owner_id"], "body": body, "time": stamp})
            conversation.append({"sender": peer["owner_id"], "body": "Örnek yanıt: Tercihlerimizi karşılaştırdıktan sonra personel rejimi ve kurum koşullarını ayrıca kontrol edelim.", "time": stamp})
            st.rerun()


def guide_page():
    section("Becayiş rehberi", "Başvuru hazırlığı ve demo kapsamı için kısa bir yol haritası.")
    with st.container(border=True):
        st.subheader("Bir öneriyi nasıl değerlendirmelisiniz?")
        st.write("1. Kurum, unvan/branş, statü ve personel rejiminizi doğru belirleyin.")
        st.write("2. Yer tercihlerini ve önerilen gidiş yönünü kontrol edin.")
        st.write("3. Kurumun güncel mevzuatını, hizmet süresini ve başvuru koşullarını inceleyin.")
        st.write("4. Taraflar ayrı ayrı karar versin; gereken başvuru şablonunu kurumdan doğrulayın.")
        st.write("5. Yetkili kurum kararını başvuru sürecinde takip edin.")
        st.info("%100, yalnız yer tercihlerinin önerilen rotayla karşılandığını gösterir. Üçlü rota ayrıca kurum incelemesi gerektirir.")
        st.markdown("[657 sayılı Kanun kaynak metni](https://www.mevzuat.gov.tr/MevzuatMetin/1.5.657.pdf) · [7433 sayılı Kanun / TBMM](https://cdn.tbmm.gov.tr/KKBSPublicFile/D27/Y6/T2/KanunMetni/a987b87d-998e-4ebd-8ed3-4cc34673c986.html)")
    with st.expander("Bu sürümde neler çalışıyor?", expanded=True):
        st.write("İlan filtreleme ve kaydetme, oturum içinde ilan oluşturma/güncelleme, ikili/üçlü döngü bulma, örnek taraf kararları, sohbet senaryosu ve Türkçe PDF taslağı indirme.")
        st.write("Veriler sentetiktir ve ziyaretçilerin oturumları birbirinden ayrıdır. Sayfa yenilendiğinde/oturum kapandığında oluşturduğunuz demo kayıtları kaybolabilir.")
    with st.expander("Üretim sürümünde tamamlanacak modüller"):
        st.write("Gerçek kayıt ve oturum yönetimi, SMS OTP, PostgreSQL kalıcılığı, görev belgesi inceleme, WebSocket ile çok kullanıcılı sohbet, push bildirimleri, kurum bazlı incelenmiş kural motoru ve moderasyon.")
        st.write("Planlanan üretim mimarisi: Next.js + NestJS + PostgreSQL. Bu Streamlit sürümü sunum ve kullanıcı akışı prototipidir.")
    st.download_button("PostgreSQL başlangıç şemasını indir", (ROOT / "docs/core-schema.sql").read_bytes(), file_name="core-schema.sql", mime="text/plain")


initialize()
with st.sidebar:
    st.markdown("### ↔ Memur Becayiş")
    st.caption("Örnek profil seçerek farklı kullanıcı akışlarını deneyin.")
    by_owner = {ad["owner_id"]: ad for ad in st.session_state.ads}
    st.selectbox("Demo profili", list(by_owner), format_func=lambda owner: f"{by_owner[owner]['pseudonym']} · {by_owner[owner]['current_province']}", key="actor_choice")
    selected_actor = actor_ad()
    st.write(selected_actor["institution"])
    st.caption(f"{selected_actor['title']} · {selected_actor['employment']}")
    st.divider()
    st.caption("Gerçek giriş yapılmaz. Profil seçimi yalnız demo senaryosudur.")
    if st.button("Demoyu sıfırla", key="reset-demo", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.markdown('<div class="brand"><div class="brand-symbol">↔</div><div><div class="brand-name">Memur Becayiş</div><div class="brand-sub">Karşılıklı yer değiştirme platformu</div></div><div class="demo-pill">Başlangıç demosu</div></div>', unsafe_allow_html=True)
page = st.radio("Gezinme", PAGES, horizontal=True, label_visibility="collapsed", key="page")
st.caption("Sentetik veriler · Oturuma özel kayıtlar · Mevzuat sonucu kurum incelemesi gerektirir")
if st.session_state.flash:
    st.success(st.session_state.pop("flash"))
    st.session_state.flash = None

{"İlanlar": listing_page, "Eşleşmeler": matches_page, "İlan oluştur": create_page, "Mesajlar": messages_page, "Rehber": guide_page}[page]()
st.markdown('<div class="footer">Memur Becayiş · Üniversite bitirme projesi başlangıç demosu<br>İlanlar ve kişiler örnektir. Kurum onayı, gerçek doğrulama ve çok kullanıcılı iletişim sonraki sürüm kapsamındadır.</div>', unsafe_allow_html=True)
