-- Memur Becayis Platformu: PostgreSQL 15+ baslangic cekirdegi.
-- Bos bir veritabaninda bir kez calistirilacak migration; seed veri icermez.
-- UUID uretimi gen_random_uuid() ile yapilir; ek extension gerektirmez.
-- Bu dosya taslak bir cekirdektir; canli PostgreSQL uzerinde dogrulanmamistir.
--
-- ERISIM VE IMMUTABILITY SOZLESMESI
-- Veritabanina yalniz backend servis rolu erisir. Users/private profile tablolarini
-- tarayicidan dogrudan sorgulamak veya SELECT * ile public DTO uretmek yasaktir.
-- profile_revisions, ad_revisions, ad_targets ve rulesets uygulama tarafinda
-- append-only kullanilir. Bu dosyada immutability trigger'i bulunmaz: SQL tek
-- basina UPDATE/DELETE'i engellemez. Uretimde rol yetkileri ve/veya basit guard
-- trigger'lariyla bu sozlesme ayrica zorlanmalidir. Bir revision ve tum hedefleri
-- tek transaction'da olusturulur; commit edilmis revision'a hedef eklenmez.
-- Revisions degistirilmez; yeni revision ve current pointer yazilir.
--
-- KATALOG KIMLIKLERI HUKUKI UYGUNLUK KANITI DEGILDIR.
-- 3+1 gibi atama duzenleri employment_type'tan ayridir. Kurallar kurum/duzen/
-- yururluk tarihi bazinda incelenmis ruleset ile degerlendirilir; unknown sonucu
-- kendiliginden passes_rules yapilmaz. Kurum karari platform skorundan ayridir.

BEGIN;

CREATE SCHEMA becayis;
SET LOCAL search_path = becayis, public;

CREATE TYPE account_state AS ENUM ('pending', 'active', 'suspended', 'deleted');
CREATE TYPE ad_state AS ENUM ('draft', 'active', 'paused', 'withdrawn', 'completed', 'archived');
CREATE TYPE match_state AS ENUM (
    'suggested', 'negotiating', 'accepted', 'submitted',
    'completed', 'rejected', 'expired', 'stale', 'cancelled'
);
CREATE TYPE legal_eligibility_state AS ENUM ('unknown', 'passes_rules', 'fails_rules');
CREATE TYPE participant_decision AS ENUM ('pending', 'accepted', 'declined');
CREATE TYPE conversation_kind AS ENUM ('direct', 'match_group');
CREATE TYPE conversation_state AS ENUM ('pending', 'open', 'closed');
CREATE TYPE membership_state AS ENUM ('invited', 'active', 'left');

-- Kurum agaci: bakanlik/kurum ile gorev birimi ayni kavram degildir.
CREATE TABLE institutions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code                varchar(64) NOT NULL UNIQUE,
    name                text NOT NULL,
    parent_id           uuid REFERENCES institutions(id),
    is_active           boolean NOT NULL DEFAULT true,
    CHECK (parent_id IS NULL OR parent_id <> id)
);

-- Bir unvanin farkli branslari ayri, kontrol edilen katalog kodlari alir.
-- Gorunen adlar yerine id ve kurumun kurallarindaki equivalence bilgisi kullanilir.
CREATE TABLE titles (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code                varchar(64) NOT NULL UNIQUE,
    name                text NOT NULL,
    branch_code         varchar(64),
    branch_name         text,
    is_active           boolean NOT NULL DEFAULT true
);

CREATE TABLE service_classes (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code                varchar(64) NOT NULL UNIQUE,
    name                text NOT NULL,
    is_active           boolean NOT NULL DEFAULT true
);

CREATE TABLE personnel_regimes (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code                varchar(64) NOT NULL UNIQUE,
    name                text NOT NULL,
    employment_type     varchar(16) NOT NULL,
    appointment_scheme  varchar(64) NOT NULL,
    description         text,
    is_active           boolean NOT NULL DEFAULT true,
    UNIQUE (id, employment_type),
    CHECK (employment_type IN ('4A', '4B', 'OTHER'))
);

CREATE TABLE provinces (
    id                  smallint PRIMARY KEY,
    name                text NOT NULL UNIQUE,
    CHECK (id BETWEEN 1 AND 81)
);

CREATE TABLE districts (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    province_id         smallint NOT NULL REFERENCES provinces(id),
    name                text NOT NULL,
    UNIQUE (id, province_id),
    UNIQUE (province_id, name)
);
CREATE INDEX districts_province_idx ON districts(province_id);

CREATE TABLE units (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id      uuid NOT NULL REFERENCES institutions(id),
    province_id         smallint NOT NULL REFERENCES provinces(id),
    district_id         bigint NOT NULL,
    code                varchar(128) NOT NULL,
    name                text NOT NULL,
    is_active           boolean NOT NULL DEFAULT true,
    UNIQUE (institution_id, code),
    UNIQUE (id, institution_id, province_id, district_id),
    FOREIGN KEY (district_id, province_id)
        REFERENCES districts(id, province_id)
);
CREATE INDEX units_location_idx ON units(institution_id, province_id, district_id);

-- TAMAMI OZEL: email, telefon, legal_name, parola hash ve pointer public DTO'ya
-- eklenmez. Public kimlik yalniz kontrollu takma ad/ilan projeksiyonundan uretilir.
-- TC kimlik numarasi bu cekirdekte toplanmaz.
CREATE TABLE users (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email                       text,
    phone_e164                  varchar(16),
    password_hash               text,
    legal_name                  text,
    pseudonym                   varchar(80) NOT NULL,
    email_verified_at           timestamptz,
    phone_verified_at           timestamptz,
    state                       account_state NOT NULL DEFAULT 'pending',
    current_profile_revision_id uuid,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    deleted_at                  timestamptz,
    CHECK (email IS NOT NULL OR phone_e164 IS NOT NULL),
    CHECK (email IS NULL OR length(btrim(email)) > 0),
    CHECK (phone_e164 IS NULL OR phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
    CHECK (length(btrim(pseudonym)) > 0),
    CHECK ((state = 'deleted') = (deleted_at IS NOT NULL))
);
CREATE UNIQUE INDEX users_email_uq ON users(lower(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX users_phone_uq ON users(phone_e164) WHERE phone_e164 IS NOT NULL;

-- Append-only servis sozlesmesi; user_id + revision_no surumunu tanimlar.
-- service_class hizmet sinifidir; service_branch_code hizmet koludur.
-- Hizmet sinifi, derece/kademe uygulanmiyorsa veya bilinmiyorsa NULL kalir.
-- fixed_post = NULL bilinmiyor anlamindadir; false varsayilmaz.
-- Bilgiler beyan edilen fact snapshot'idir; belge dogrulama sonucu ayri tutulur.
-- Kurumda, birimde ve kadroda gecen sureler ilk ise giris tarihinden turetilmez;
-- ilgili sureyi ruleset, ayri tarih alanlarindan ve beyan edilen regime_phase'ten okur.
CREATE TABLE profile_revisions (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 uuid NOT NULL REFERENCES users(id),
    revision_no             integer NOT NULL CHECK (revision_no > 0),
    institution_id          uuid NOT NULL REFERENCES institutions(id),
    title_id                uuid NOT NULL REFERENCES titles(id),
    employment_type         varchar(16) NOT NULL,
    personnel_regime_id     uuid NOT NULL,
    service_class_id        uuid REFERENCES service_classes(id),
    service_branch_code     varchar(64),
    grade                   smallint CHECK (grade IS NULL OR grade > 0),
    step                    smallint CHECK (step IS NULL OR step > 0),
    province_id             smallint NOT NULL REFERENCES provinces(id),
    district_id             bigint NOT NULL,
    unit_id                 uuid,
    service_started_on      date,
    appointment_started_on  date,
    institution_started_on  date,
    current_unit_started_on date,
    permanent_appointment_on date,
    regime_phase            varchar(64),
    fixed_post              boolean,
    facts_as_of             date NOT NULL DEFAULT current_date,
    created_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, revision_no),
    UNIQUE (id, user_id),
    FOREIGN KEY (personnel_regime_id, employment_type)
        REFERENCES personnel_regimes(id, employment_type),
    FOREIGN KEY (district_id, province_id)
        REFERENCES districts(id, province_id),
    FOREIGN KEY (unit_id, institution_id, province_id, district_id)
        REFERENCES units(id, institution_id, province_id, district_id),
    CHECK (service_started_on IS NULL OR service_started_on <= facts_as_of),
    CHECK (appointment_started_on IS NULL OR appointment_started_on <= facts_as_of),
    CHECK (institution_started_on IS NULL OR institution_started_on <= facts_as_of),
    CHECK (current_unit_started_on IS NULL OR current_unit_started_on <= facts_as_of),
    CHECK (permanent_appointment_on IS NULL OR permanent_appointment_on <= facts_as_of)
);
CREATE INDEX profile_revisions_candidate_idx
    ON profile_revisions(institution_id, title_id, employment_type, personnel_regime_id,
                         province_id, district_id);

-- Composite FK, baska kullanicinin profilinin current pointer olmasini engeller.
ALTER TABLE users ADD CONSTRAINT users_current_profile_fk
    FOREIGN KEY (current_profile_revision_id, id)
    REFERENCES profile_revisions(id, user_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE ads (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL REFERENCES users(id),
    state               ad_state NOT NULL DEFAULT 'draft',
    current_version     integer CHECK (current_version IS NULL OR current_version > 0),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz,
    UNIQUE (id, user_id),
    CHECK (state <> 'active' OR current_version IS NOT NULL)
);
CREATE UNIQUE INDEX ads_one_active_per_user_uq ON ads(user_id) WHERE state = 'active';
CREATE INDEX ads_state_updated_idx ON ads(state, updated_at DESC);
-- now() index predicate'i kullanilmaz; worker suresi dolan ilan state'ini degistirir.
CREATE INDEX ads_active_expiry_idx ON ads(expires_at) WHERE state = 'active';

CREATE TABLE ad_revisions (
    ad_id                   uuid NOT NULL,
    version                 integer NOT NULL CHECK (version > 0),
    user_id                 uuid NOT NULL,
    profile_revision_id     uuid NOT NULL,
    anonymous               boolean NOT NULL DEFAULT true,
    public_note             text,
    reason_category         varchar(64),
    created_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ad_id, version),
    UNIQUE (ad_id, version, user_id, profile_revision_id),
    FOREIGN KEY (ad_id, user_id) REFERENCES ads(id, user_id),
    FOREIGN KEY (profile_revision_id, user_id) REFERENCES profile_revisions(id, user_id),
    CHECK (public_note IS NULL OR char_length(public_note) <= 2000)
);
CREATE INDEX ad_revisions_profile_idx ON ad_revisions(profile_revision_id, user_id);

-- district_id NULL: bu ilin tum ilceleri kabul edilir. Oncelik kucukten buyuge.
-- Exact unit hedefi bu cekirdekte yoktur; kesin gorev birimi sadece private fact'tir.
CREATE TABLE ad_targets (
    ad_id               uuid NOT NULL,
    ad_version          integer NOT NULL,
    priority            smallint NOT NULL CHECK (priority > 0),
    province_id         smallint NOT NULL REFERENCES provinces(id),
    district_id         bigint,
    PRIMARY KEY (ad_id, ad_version, priority),
    UNIQUE NULLS NOT DISTINCT (ad_id, ad_version, province_id, district_id),
    FOREIGN KEY (ad_id, ad_version) REFERENCES ad_revisions(ad_id, version),
    FOREIGN KEY (district_id, province_id) REFERENCES districts(id, province_id)
);
CREATE INDEX ad_targets_location_idx ON ad_targets(province_id, district_id, ad_id, ad_version);

ALTER TABLE ads ADD CONSTRAINT ads_current_revision_fk
    FOREIGN KEY (id, current_version) REFERENCES ad_revisions(ad_id, version)
    DEFERRABLE INITIALLY DEFERRED;

-- Kural surumu complete snapshot olarak eklenir, mevcut satir degistirilmez.
-- JSON definition semasi ve kaynak/yururluk degerlendirmesi uygulamada dogrulanir.
CREATE TABLE rulesets (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                varchar(128) NOT NULL,
    version             integer NOT NULL CHECK (version > 0),
    institution_id      uuid REFERENCES institutions(id),
    effective_from      date NOT NULL,
    effective_until     date,
    definition          jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_url          text,
    reviewed_by         uuid REFERENCES users(id),
    reviewed_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version),
    UNIQUE (id, version),
    CHECK (jsonb_typeof(definition) = 'object'),
    CHECK (effective_until IS NULL OR effective_until >= effective_from),
    CHECK ((reviewed_by IS NULL) = (reviewed_at IS NULL))
);
CREATE INDEX rulesets_institution_effective_idx ON rulesets(institution_id, effective_from);

-- passes_rules sadece incelenen ruleset degerlendirmesidir; kurum onayi degildir.
-- Uclu oneriler dahil tum eslesmelerin varsayilan hukuki sonucu unknown'dur.
-- preference_score ve ranking_score, hukuki durumdan ayri gosterilir.
-- Ranking, hard eligibility failure'i telafi edemez.
CREATE TABLE matches (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    participant_count   smallint NOT NULL CHECK (participant_count IN (2, 3)),
    state               match_state NOT NULL DEFAULT 'suggested',
    legal_eligibility   legal_eligibility_state NOT NULL DEFAULT 'unknown',
    preference_score    numeric(5,2) CHECK (preference_score BETWEEN 0 AND 100),
    ranking_score       numeric(5,2) CHECK (ranking_score BETWEEN 0 AND 100),
    ruleset_id          uuid NOT NULL,
    ruleset_version     integer NOT NULL,
    canonical_key       text NOT NULL,
    legal_reason_codes  text[] NOT NULL DEFAULT ARRAY[]::text[],
    evaluated_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz,
    UNIQUE (ruleset_id, ruleset_version, canonical_key),
    FOREIGN KEY (ruleset_id, ruleset_version) REFERENCES rulesets(id, version),
    CHECK (char_length(canonical_key) > 0)
);
CREATE INDEX matches_state_created_idx ON matches(state, created_at DESC);
CREATE INDEX matches_expiry_idx ON matches(expires_at)
    WHERE state IN ('suggested', 'negotiating');

-- Route: order i'deki kisi, order (i mod participant_count)+1 kisinin yerine gider.
-- Composite FK ilan sahibi ve profil revision'inin ayni kisiye ait oldugunu,
-- ayrica o profilin gercekten bu ilan revision'indan geldigini garanti eder.
CREATE TABLE match_participants (
    match_id                   uuid NOT NULL REFERENCES matches(id),
    user_id                    uuid NOT NULL REFERENCES users(id),
    source_ad_id               uuid NOT NULL,
    source_ad_version          integer NOT NULL,
    source_profile_revision_id uuid NOT NULL,
    route_order                smallint NOT NULL CHECK (route_order BETWEEN 1 AND 3),
    decision                   participant_decision NOT NULL DEFAULT 'pending',
    decided_at                 timestamptz,
    PRIMARY KEY (match_id, user_id),
    UNIQUE (match_id, route_order),
    UNIQUE (match_id, source_ad_id),
    FOREIGN KEY (source_ad_id, source_ad_version, user_id, source_profile_revision_id)
        REFERENCES ad_revisions(ad_id, version, user_id, profile_revision_id),
    CHECK ((decision = 'pending' AND decided_at IS NULL)
        OR (decision <> 'pending' AND decided_at IS NOT NULL))
);
CREATE INDEX match_participants_user_idx ON match_participants(user_id, match_id);
CREATE INDEX match_participants_source_idx ON match_participants(source_ad_id, source_ad_version);

-- UYGULAMA TRANSACTION INVARIANT'LARI (bu dosyada count/permutation trigger'i yok):
-- * matches + butun participant satirlari tek transaction'da eklenir.
-- * Satir sayisi participant_count; route_order tam olarak 1..N permutasyonudur.
-- * Her rota kenari hedefe, uygunluk grubuna ve kurala gore dogrulanir.
-- * Kaynak ilanlar active, expires_at uygun ve current_version snapshot ile aynidir.
-- * Kabul sirasinda users.current_profile_revision_id kaynak profil ile aynidir;
--   etkin/uygulanabilir ruleset resolver'i hala ayni id + version'u secmelidir.
-- * canonical_key, surumlu kaynaklari icerir. Ikilide kimlikler siralanir; uclu
--   dongude sadece en kucuk rotasyon secilir; ters yon siralanarak birlestirilmez.
-- * Member kaynaklari/route_order yaratildiktan sonra degistirilmez; sadece karar
--   alanlari yetkili kullanici adina guncellenir. Tum kabul ve durum gecisleri
--   matches satiri kilitlenerek kontrol edilir; degisen kaynak eslesmeyi stale eder.
-- * Profil pointer'i ile aktif ilanin yeni revision'i ayni transaction'da yazilir.
--   Profil, ilan revision'i, state veya expires_at gibi matching-relevant herhangi
--   bir degisiklik ayni transaction'da yeniden degerlendirme outbox olayi uretir.
--   Eslesme sure asimina ugramissa expired, kaynaklari degismisse stale kullanilir.

-- Konusmalar da eslesmeler de private API kaynaklaridir; public liste endpoint'i yok.
-- Match grubu varsayilan pending kalir; katilim icin tum ilgili taraflarin onayi
-- ve aktif uyelik gerekir. Odaya yalniz match gorundu diye otomatik katilinmaz.
CREATE TABLE conversations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind                conversation_kind NOT NULL DEFAULT 'direct',
    state               conversation_state NOT NULL DEFAULT 'pending',
    match_id            uuid REFERENCES matches(id),
    source_ad_id        uuid REFERENCES ads(id),
    created_by          uuid NOT NULL REFERENCES users(id),
    last_sequence       bigint NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    created_at          timestamptz NOT NULL DEFAULT now(),
    last_activity_at    timestamptz,
    closed_at           timestamptz,
    CHECK (kind <> 'match_group' OR match_id IS NOT NULL),
    CHECK ((state = 'closed') = (closed_at IS NOT NULL))
);
CREATE UNIQUE INDEX conversations_match_group_uq ON conversations(match_id)
    WHERE kind = 'match_group';
CREATE INDEX conversations_creator_idx ON conversations(created_by);
CREATE INDEX conversations_source_ad_idx ON conversations(source_ad_id);
CREATE INDEX conversations_match_idx ON conversations(match_id);

CREATE TABLE conversation_members (
    conversation_id     uuid NOT NULL REFERENCES conversations(id),
    user_id             uuid NOT NULL REFERENCES users(id),
    state               membership_state NOT NULL DEFAULT 'invited',
    invited_at          timestamptz NOT NULL DEFAULT now(),
    joined_at           timestamptz,
    left_at             timestamptz,
    last_read_sequence  bigint NOT NULL DEFAULT 0 CHECK (last_read_sequence >= 0),
    last_read_at        timestamptz,
    PRIMARY KEY (conversation_id, user_id),
    CHECK (state <> 'active' OR joined_at IS NOT NULL),
    CHECK (state <> 'left' OR left_at IS NOT NULL)
);
CREATE INDEX conversation_members_user_idx ON conversation_members(user_id, state, conversation_id);

CREATE TABLE messages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     uuid NOT NULL REFERENCES conversations(id),
    sender_id           uuid NOT NULL,
    client_message_id   uuid NOT NULL,
    sequence_no         bigint NOT NULL CHECK (sequence_no > 0),
    body                text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    edited_at           timestamptz,
    redacted_at         timestamptz,
    UNIQUE (conversation_id, sender_id, client_message_id),
    UNIQUE (conversation_id, sequence_no),
    FOREIGN KEY (conversation_id, sender_id)
        REFERENCES conversation_members(conversation_id, user_id),
    CHECK (char_length(body) BETWEEN 1 AND 5000)
);
CREATE INDEX messages_sender_idx ON messages(sender_id);

-- MESAJ YAZMA TRANSACTION'I:
-- 1. Auth principal sender_id'dir; istemci sender_id'sine guvenilmez.
-- 2. conversations satirini SELECT ... FOR UPDATE ile kilitle.
-- 3. Yetkiyi tekrar denetle: open conversation, aktif uyelik, engel yok.
-- 4. Idempotency anahtari varsa mevcut mesaji don; farkli payload ise 409.
-- 5. UPDATE conversations SET last_sequence = last_sequence + 1 RETURNING
--    last_sequence; bu degerle mesaj ve outbox olayini ayni transaction'da yaz.
-- 6. Commit'ten sonra ACK; worker socket/push yayimini outbox'tan yapar.
-- Unique FK tek basina aktif uyelik, engelleme veya sequence sayacini zorlamaz.
-- Uyelik ayrilinca satir silinmez; state guncellenir (gecmis sender FK korunur).
-- last_read_sequence sadece aktif uyenin kendi satirinda, <= last_sequence ve
-- GREATEST(eski, yeni) ile monoton artar; mesaj basina read boolean tutulmaz.
-- Typing/presence bu tabloda yoktur; izinli, kisa omurlu realtime olaylaridir.

CREATE TABLE outbox_events (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id            uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    aggregate_type      varchar(64) NOT NULL,
    aggregate_id        uuid NOT NULL,
    event_type          varchar(128) NOT NULL,
    deduplication_key   text UNIQUE,
    payload             jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    available_at        timestamptz NOT NULL DEFAULT now(),
    locked_until        timestamptz,
    attempts            integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    processed_at        timestamptz,
    CHECK (jsonb_typeof(payload) = 'object')
);
CREATE INDEX outbox_pending_idx ON outbox_events(available_at, id)
    WHERE processed_at IS NULL;

-- Worker leasing/claim SELECT ... FOR UPDATE SKIP LOCKED ile yapilir;
-- available_at/locked_until karsilastirmasi sorguda yapilir. Teslim en az bir kez
-- olabilir; worker ve istemci event_id/mesaj kimligi ile tekrar ayiklar.
-- payload'da belge, telefon, OTP veya mesaj metni yerine kaynak kimlikleri tasinir.
-- Push varsayilan olarak metni ifsa etmeyen genel bildirim gonderir.
--
-- OZELLIK GENISLETMELERI (bu migration kapsaminda tablo olusturulmaz):
-- auth_sessions: hash'li refresh token, expiry/revocation ve rotation kaydi;
-- otp_challenges: sunucu sirriyla HMAC, expiry, attempts, rate limit;
-- verification_requests/documents: private object key, review audit, retention;
-- blocks/reports/notification_preferences/contact_sharing_consents: sohbet ve
-- hassas veri paylasiminin ilgili endpoint'lerde her istekte kontrol edilmesi;
-- application_requests/petitions: ayri kurum sureci, surumlu PDF sablonu;
-- moderation/audit_logs: PII'yi loglamadan yetkili eylemler;
-- forum: cekirdekten bagimsiz, sonraki sprint modulu.
-- Bu tablolari eklemeden ilgili ozellikler tamamlanmis/guvenli kabul edilmez.
-- updated_at gibi alanlar uygulamada guncellenir; otomatik timestamp trigger'i yok.
-- Fiziksel silme yerine lifecycle state kullanilir; KVKK saklama/silme politikasinin
-- uygulama ve operasyon katmaninda ayrica tasarlanmasi gerekir.

COMMIT;
