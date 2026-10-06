# Üretim mimarisi ve geliştirme yol haritası

## Mevcut demonstrasyon

Streamlit sürümü, bitirme projesinin kullanıcı akışlarını ve eşleştirme fikrini incelemeyi sağlar. Örnek kayıtlar, profil/ilan değişiklikleri ve sohbet akışı oturum içindedir. Gerçek kimlik doğrulaması, kalıcı kayıt, belge incelemesi, çok kullanıcılı canlı sohbet veya kurum başvurusu uygulanmış değildir. İkili ve üçlü tercih döngüsü, hukuki uygunluk ve kurum kararıyla ayrı tutulur.

## Üretim hedefi

| Katman | Tercih | Görevi |
| --- | --- | --- |
| Web/PWA | Next.js + TypeScript | İlanlar, profil, eşleşmeler, sohbet ve erişilebilir arayüz |
| Backend | NestJS modüler monolit | Kimlik, yetki, kurallar, eşleştirme ve iş akışları |
| Veritabanı | PostgreSQL | Sürümlü profil/ilan, eşleşme, konuşma ve kalıcı mesajlar |
| Arka plan işleri | Redis + BullMQ | İlan değişiminde eşleştirme ve bildirim işleri |
| Gerçek zaman | Socket.io/WebSocket | Yetkili konuşma odaları, yazıyor ve durum olayları |
| Dosyalar | Özel nesne depolama | Erişim süresi sınırlı doğrulama belgeleri ve PDF çıktıları |
| Bildirim | Uygulama içi kutu; sonraki aşamada push | Yeni adaylar ve mesajlar |

İlk üretim sürümünde modüller tek backend içinde kalır: `Auth`, `Profiles`, `Listings`, `Rules`, `Matching`, `Messaging`, `Verification`, `Applications`, `Notifications` ve `Moderation`. PostgreSQL kalıcı doğruluk kaynağıdır. Bir veritabanı değişikliği ve outbox olayı aynı transaction'da yazılır; worker, commit edilmiş olayı tüketir. Socket/push ile teslim tekrarlanabildiği için tüketiciler olay kimliğine göre tekrarları ayıklar.

## Veri ve eşleştirme kuralları

`docs/core-schema.sql` ilişkisel çekirdeğin başlangıcıdır. Kataloglar, `users`, `profile_revisions`, `ads`, `ad_revisions`, `ad_targets`, `rulesets`, `matches`, `match_participants`, `conversations`, `conversation_members`, `messages` ve `outbox_events` tablolarını içerir.

- Kimlik ve iletişim bilgileri özel alanlardır. Anonim ilan API'si, açıkça izin verilen alanlardan DTO üretir; ad ve kesin birim tarayıcıya gönderilmez.
- İstihdam türü ile atama düzeni ayrıdır. Hizmet sınıfı, hizmet kolu, derece/kademe ve farklı başlangıç tarihleri uygulanabilirliklerine göre tutulur; bilinmeyen bilgi uygunluk varsayımına dönüştürülmez.
- Profil ve ilan revision'ları append-only servis sözleşmesiyle kullanılır. SQL taslağı immutability'yi tek başına zorlamaz; üretimde yetkiler/guard'lar ve migration kontrolleri eklenir.
- Profil pointer'ı ve aktif ilan revision'ı aynı transaction'da değişir. İlanın durumu, süresi veya ilgili fact değiştiğinde yeniden değerlendirme olayı çıkar.
- İkili öneri iki karşılıklı kenardır. Üçlü öneri `A → B → C → A` kapalı döngüsüdür. Aynı kullanıcı bir döngüye iki kez alınmaz.
- Üçlü canonical key en küçük rotasyonla üretilir ve yön korunur. Kaynak ilan/profil sürümleri ve ruleset sürümü öneride saklanır.
- Tercih ve sıralama puanı, hard eligibility başarısızlığını telafi etmez. Varsayılan hukuki değerlendirme `unknown` olur; kurum kararı ayrı süreçtir.
- Kabul transaction'ı güncel profil/ilan pointer'larını ve etkin ruleset'i yeniden kontrol eder. Kaynağı değişmiş öneri `stale`, süresi dolmuş öneri `expired` olur.

Ruleset'ler kaynak referansı, yürürlük tarihleri ve inceleme bilgisiyle sürümlenir. Bir öneride kullanılan kurum şartları değiştiğinde eski sonuçlar yeniden değerlendirilir. Dilekçe şablonları da kurum bazında incelenip sürümlenmelidir.

## Kimlik, belge ve iletişim

İlk üretim dilimi e-posta/şifre girişi, hesap kurtarma, güvenli oturum yönetimi ve yönetici yetkilerini kapsar. Parolalar uygun parola hash algoritmasıyla tutulur; erişim ve yenileme token'larının iptal/rotation akışı tasarlanır. SMS OTP sonraki dilimde süre, deneme sayısı ve gönderim sınırıyla eklenir; düşük entropili OTP için sunucu sırrıyla HMAC kullanılır.

Kurumsal e-posta rozeti, posta kutusuna erişimi belirtir. Görev belgesi incelemesi ayrı doğrulama türüdür. Belgeler özel depoda, kısa süreli erişimle ve belirlenmiş saklama politikasıyla işlenir. TC kimlik numarası varsayılan veri modeli dışında kalır; telefon paylaşımı tarafların açık onaylı akışıdır.

Canlı mesajlaşmada sunucu principal'ı göndereni belirler. Odaya katılma ve her mesaj olayında üyelik, konuşma durumu ve engelleme kontrol edilir. Mesajlara konuşma başına sunucu sıra numarası verilir; idempotency anahtarı aynı gönderimin çoğalmasını engeller. Yeniden bağlantı eksik sıra numaralarını tamamlar. Okundu bilgisi üye başına monoton `last_read_sequence` olarak tutulur. Grup konuşması tarafların onayıyla açılır; push bildirimi varsayılan olarak mesaj metnini göstermez.

## 12 haftalık plan

| Hafta | Geliştirme çıktısı | Kabul kanıtı |
| --- | --- | --- |
| 1–2 | Veri sözlüğü, kataloglar, kuralların sınırları, backend/web iskeleti, CI ve e-posta giriş | Migration ve oturum akışı testleri; sahte veriyle çalışan ortam |
| 3–4 | Sürümlü profil, ilan/hedefler, filtreler, anonim DTO | Başka kullanıcı kayıtlarına yetkisiz erişim engellenir; anonim API'de gizli alan bulunmaz |
| 5–6 | İkili eşleşme, üçlü döngü prototipi, canonical key, outbox işçisi | Döngü yönü, tekrarlar, kurum/unvan uyumsuzluğu ve ilan değişimi testleri |
| 7–8 | İletişim isteği, onaylı sohbet, engelleme, sıra/idempotency ve yeniden bağlantı | Yetkisiz oda reddi; tekrar gönderimde tek mesaj; bağlantı kaybında eksik mesajların tamamlanması |
| 9–10 | Eşleşme kabul süreci, kurum e-postası rozeti, bildirim kutusu ve PDF şablonları | Eski revision kabul edilemez; Türkçe PDF doğru üretilir; kurum süreci ayrı durumlarla izlenir |
| 11–12 | Yetki/mahremiyet kontrolleri, yük ölçümü, mobil görünüm, erişilebilirlik ve tez/demo | Temel akışlar farklı ekranlarda çalışır; test raporu ve bilinen sınırlar teslim edilir |

Mobil uygulama, geniş forum, otomatik belge değerlendirmesi, SMS ve kapsamlı push desteği sonraki sürümlere ayrılabilir. Önce web/PWA'da profil → ilan → öneri → onaylı iletişim → taslak dilekçe zinciri tamamlanır.

## Doğrulama yaklaşımı

Alan testleri, karşılıklı hedefleri, üçlü yön/rotasyonları, aynı kişinin tekrarını ve bilinmeyen uygunluk sonuçlarını kapsar. Veritabanı entegrasyon testleri composite FK'leri, tek aktif ilanı, transaction'ları ve eşzamanlı mesaj sırasını doğrular. API testleri sahiplik ve anonim alan projeksiyonunu denetler. PDF testleri Unicode karakterleri ve boş/eksik alan davranışını kontrol eder. Worker testleri aynı olayın yeniden tesliminde çift öneri veya bildirim oluşmamasını sınar.

Streamlit testlerinin geçmesi, bu üretim güvenlik kurallarının uygulanmış olduğunu göstermez. Üretim geçişinde PostgreSQL migration'ları gerçek test veritabanında çalıştırılır ve bağımsız kullanıcı oturumlarıyla uçtan uca kontroller yapılır.
