# Memur Becayiş Platformu

Üniversite bitirme projesi için hazırlanmış, Streamlit ile çalışan etkileşimli becayiş demosu. Örnek ilanları inceleyebilir, kendi oturumunda profil ve ilan oluşturabilir, karşılıklı tercihlere dayanan ikili ve üçlü eşleşmeleri görebilir ve dilekçe taslağı indirebilirsin.

**Canlı uygulama:** [Memur Becayiş demosunu aç](https://memur-becayis-platformu-kjvlrmwmfswheuyoket4fm.streamlit.app/)

## Demo kapsamı

- İl, kurum, unvan ve personel bilgileriyle ilan arama ve filtreleme.
- Örnek veriler üzerinde profil ve ilan akışı; anonim ilan görünümü.
- Karşılıklı hedefler için ikili eşleşme ve yönü korunan üçlü kapalı döngü önerisi.
- Aynı tarayıcı oturumunda çalışan örnek sohbet akışı.
- Türkçe karakterleri destekleyen PDF dilekçe taslağı indirme.
- Becayiş sürecini ve ürünün sınırlarını anlatan rehber ekranı.

Bu sürümde veriler `st.session_state` içinde, oturum süresince tutulur. Kalıcı bir veritabanı, gerçek kullanıcı hesabı, SMS OTP, belge doğrulaması veya kullanıcılar arası canlı WebSocket bağlantısı yoktur. Sohbet ekranı ve profil kayıtları birer demonstrasyondur; gerçek kişisel veri veya görev belgesi girilmemelidir. Yeni oturum başlatıldığında eklediğin veriler kaybolabilir.

Eşleşme yüzdesi ve tercih uyumu, kurumun yer değiştirme onayı anlamına gelmez. Üçlü öneri algoritmik bir döngüdür; bu sürüm kurumsal veya hukuki uygulanabilirliğini doğrulamaz. PDF çıktısı incelenip uyarlanması gereken bir taslaktır.

## Yerelde çalıştırma

Python **3.11 veya üzeri** gerekir. Dağıtım ve CI için seçilen sürüm Python 3.11'dir. Komutları repository kökünde çalıştır:

```bash
python -m venv .venv
```

Sanal ortamı etkinleştir:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Bağımlılıkları kur ve uygulamayı başlat:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Terminalin gösterdiği yerel adresi aç. Bağımlılık sürümlerinin kaynağı `requirements.txt` dosyasıdır. Demo için API anahtarı, `.env` veya Streamlit secrets ayarı gerekmez.

## Testler

Python alan modeli, PDF ve uygulama testlerini çalıştır:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Özgün JavaScript eşleştirme örneğini ayrıca kontrol etmek için Node.js kuruluysa:

```bash
node --test examples/matching.test.mjs
```

JavaScript örneği Streamlit uygulamasının çalışması için gerekli değildir. GitHub Actions, Python 3.11 üzerinde bağımlılıkları kurup Python testlerini çalıştırır; özel token veya secrets tanımlamak gerekmez.

## Streamlit Community Cloud dağıtımı

Hedef dağıtım ayarları:

| Alan | Değer |
| --- | --- |
| GitHub sahibi | `ulasdgn` |
| Repository | `memur-becayis-platformu` |
| Branch | `main` |
| Entry point | `app.py` |
| Python sürümü | `3.11` |
| Secrets | Bu demo için gerekmiyor |

Repository hedef hesaba yüklendikten sonra [Streamlit Community Cloud](https://share.streamlit.io/) içinde uygulama oluştur, yukarıdaki repository/branch/dosya yolunu seç ve **Advanced settings** içinden Python 3.11'i ayarla. Başarılı derlemeden sonra uygulamayı açıp arama, ilan, eşleştirme ve PDF indirmeyi doğrula. Canlı URL'yi ancak bu kontrolden sonra README'ye ekle. Dağıtım alanları ve Python seçimi için [resmî Streamlit dağıtım kılavuzu](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy) kullanılabilir.

`.streamlit/secrets.toml`, kimlik bilgileri ve yerel veriler Git'e eklenmez. Üretim sürümünde gereken anahtarlar, ilgili hosting ortamının secrets yönetiminde tutulmalıdır.

## Teknik kaynaklar ve sonraki sürüm

- [Üretim mimarisi ve 12 haftalık yol haritası](docs/ROADMAP.md)
- [PostgreSQL başlangıç şeması](docs/core-schema.sql)
- [JavaScript eşleştirme örneği](examples/matching.mjs)
- [JavaScript algoritma testleri](examples/matching.test.mjs)

SQL dosyası PostgreSQL 15+ için bir başlangıç taslağıdır; Streamlit demosuna bağlı değildir ve bu repository kapsamında canlı veritabanında çalıştırıldığı iddia edilmez. Revision immutability ve bazı transaction kuralları dosyada uygulama sorumluluğu olarak açıklanır.

Üretim hedefi Next.js/TypeScript web PWA, NestJS modüler monolit, PostgreSQL ve gerektiğinde Redis/BullMQ'dur. Gerçek kimlik doğrulaması, yetkili canlı sohbet ve kalıcı kayıtlar bu mimarinin sonraki aşamasında geliştirilir.

PDF için paketlenen Noto Sans fontunun lisansı [assets/fonts/OFL.txt](assets/fonts/OFL.txt) dosyasındadır.
