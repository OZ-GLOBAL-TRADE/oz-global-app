# Jarvis Web — Canlıya alma (erp.ozglobaltrade.com)

İki parça vardır ve ikisi de gereklidir:

| Parça | Nedir | Nerede çalışır |
|---|---|---|
| **Arayüz** | Statik dosyalar (HTML/JS/CSS) | cPanel → `erp.ozglobaltrade.com` alt alanı (Node/Python gerekmez) |
| **API** | FastAPI (Python) — Supabase'e bağlanır | Render (ya da benzeri bir PaaS) → `api.ozglobaltrade.com` |

cPanel paylaşımlı hosting Python API'yi çalıştıramaz; bu yüzden API ayrı barınır. İkisi **aynı alan adının alt alanları**
olduğu için (`erp.` ve `api.ozglobaltrade.com`) oturum çerezi tarayıcıda "aynı site" sayılır ve sorunsuz çalışır.
Farklı bir alan adı (ör. `xyz.onrender.com`) kullanırsanız çerez engellenebilir — üretimde alt alan kullanın.

## 1) API'yi barındırın (Render)

1. `webapp/` klasörünün GitHub deposunda olduğundan emin olun (Streamlit'in kullandığı depo). `.env`, `secrets.toml`, `*.db`
   dosyaları depoya **girmemeli**.
2. Render → **New → Web Service** → depoyu seçin.
   - **Root Directory:** deponun kökü `oz-global-app-main` klasörüyse boş bırakın; değilse o klasörün yolunu yazın.
   - **Runtime:** Python 3 · **Build Command:** `pip install -r webapp/backend/requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT --app-dir webapp/backend`
   - **Health Check Path:** `/healthz`
   - **Plan:** *Starter* önerilir. Ücretsiz plan 15 dakika hareketsizlikte uyur; ilk girişte ~1 dakika bekletir.
3. **Environment** bölümüne şunları ekleyin:

   | Anahtar | Değer |
   |---|---|
   | `JARVIS_DEV_MODE` | `0` (zorunlu — çerez yalnızca HTTPS'de gönderilir, otomatik giriş kapanır) |
   | `SESSION_SECRET` | rastgele, en az 32 karakter. Üretmek için: `py -c "import secrets; print(secrets.token_urlsafe(48))"` — **kısa/varsayılan değerle uygulama hiç açılmaz** |
   | `DATABASE_URL` | Supabase bağlantı adresi (Streamlit Secrets'takiyle aynı) |
   | `WEB_ORIGINS` | `https://erp.ozglobaltrade.com` (sonunda `/` olmadan, tam bu yazım) |
   | `CLAUDE_API_KEY` | Jarvis AI/brifing için (isteğe bağlı) |
   | `GEMINI_API_KEY`, `DHL_API_KEY` | mevcut Streamlit'tekiler (isteğe bağlı) |
   | `PYTHON_VERSION` | `3.13.7` |

4. Deploy bitince `https://<servis-adı>.onrender.com/healthz` → `{"ok":true}` görmelisiniz.
5. **Custom Domain:** Render → Settings → Custom Domains → `api.ozglobaltrade.com` ekleyin. Render size bir CNAME hedefi verir.
6. **DNS:** cPanel → **Zone Editor** (Bölge Düzenleyici) → `ozglobaltrade.com` → **CNAME kaydı ekle**: ad `api`, hedef Render'ın verdiği adres.
   > "Alan Adları → Alt alan adı oluştur" ile `api` oluşturmayın: o, kayıt cPanel sunucusuna yönlendirir.
   Render alan adını doğrulayınca HTTPS sertifikasını kendisi verir (birkaç dakika).
7. `https://api.ozglobaltrade.com/healthz` açılıyorsa API hazırdır.

Alternatif: kökteki `render.yaml` Blueprint olarak da kullanılabilir (Render → New → Blueprint); gizli değerleri (`DATABASE_URL` vb.) yine panelden girersiniz.

## 2) Arayüzü cPanel'e yükleyin

1. Bilgisayarınızda (API adresi arayüze **derleme anında** gömülür):
   ```
   webapp\build_web.cmd https://api.ozglobaltrade.com
   ```
   Çıktı: `webapp\dist\erp-web.zip`. (API farklı bir adreste olursa o adresi yazıp yeniden derleyin.)
2. cPanel → **File Manager** → belge kök dizini `/home/ozglobaltrade/erp.ozglobaltrade.com` → **Upload** ile zip'i yükleyin →
   zip'e sağ tık → **Extract**. Zip'in *içindekiler* doğrudan bu klasöre çıkmalı (`index.html` klasörün hemen altında olmalı; iç içe bir
   `out/` klasörü oluşmamalı). Sonra zip dosyasını silin.
3. `.htaccess` gizli dosyadır: File Manager → **Settings** → *Show Hidden Files (dotfiles)* işaretleyin ve dosyanın orada olduğunu kontrol edin.
   (HTTPS yönlendirmesi ve güvenlik başlıkları bu dosyadadır.)
4. **HTTPS sertifikası:** cPanel → **SSL/TLS Status** → `erp.ozglobaltrade.com` için **Run AutoSSL**. Sertifika gelmeden site
   güvenli açılmaz ve oturum çerezi çalışmaz (birkaç dakika sürebilir).
5. `https://erp.ozglobaltrade.com` → giriş ekranı gelmeli. Kullanıcı adı/şifre Streamlit'tekiyle aynıdır
   (şifreler Streamlit Ayarlar sayfasından belirlenir).

## 3) Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| Giriş ekranı "Failed to fetch" / ağ hatası | API çalışmıyor ya da `WEB_ORIGINS` tam adresle (`https://erp.ozglobaltrade.com`, sonda `/` yok) eşleşmiyor; `https://api.ozglobaltrade.com/healthz`'i tarayıcıda açın |
| Giriş "başarılı" ama sayfa yine girişe atıyor | Çerez engelleniyor: `JARVIS_DEV_MODE=0` mi? Arayüz ve API `ozglobaltrade.com` alt alanları mı? İkisi de HTTPS mi? |
| Site açılıyor ama tüm adreslerde 404 / boş | Zip'in içindekiler doğrudan belge kök dizininde olmalı (iç içe klasör olmasın) |
| `/talepler` gibi adreslerde 404 | `.htaccess` yüklenmemiş olabilir ya da hosting `.htaccess`'i yok sayıyor; hosting desteğine sorun |
| API açılmıyor, logda "SESSION_SECRET … 32 karakter" | `SESSION_SECRET` tanımlı değil/kısa (bilinçli koruma) |
| İlk giriş çok yavaş | Render ücretsiz planı uyudu; Starter plana geçin |

## 4) Önemli notlar

- **İki uygulama aynı Supabase veritabanını paylaşır** (Streamlit ve yeni arayüz). Yeni arayüzde yaptığınız her değişiklik gerçek veridir.
  Silme **çöp kutusuna** gider ve geri alınabilir (kalıcı silme yalnızca Admin'de, adı yazarak onayla). Denemek için önce bir deneme REQ'i
  açıp onu silmeyi deneyin. İlk denemeleri okuma ağırlıklı yapın (Panel, Talepler, REQ ayrıntısı).
- Yeni arayüzün yazma işlemleri bugüne kadar yalnızca yerel SQLite üzerinde denendi; Postgres/Supabase'de ilk gerçek deneme sizin olacak.
  Bir hata görürseniz REQ kodunu ve ekran görüntüsünü iletin.
- `SESSION_SECRET`'i değiştirirseniz herkesin oturumu kapanır (zararsız). Sızdığını düşünürseniz değiştirin.
- **Silme özelliğinin göçü:** bu sürüm `reqs/partners/products/events` tablolarına `deleted_at`/`deleted_by` sütunları ekler. Render açılışta
  bunları otomatik ekler (`init_db`, yalnızca eksik sütunu ekler). Yayından sonra, bir terminalde `$env:DATABASE_URL` Supabase adresine ayarlıyken
  `py -m alembic stamp head` çalıştırın (göçleri "uygulanmış" diye işaretler; veriye dokunmaz). Streamlit uygulaması da aynı depodan yeniden
  dağıtılacağı için silinen kayıtlar onda da görünmez.
- Yeni sürüm yayınlamak: **önce API** — depoya push (Render otomatik dağıtır, `/healthz` yeşil olana kadar bekleyin); **sonra arayüz** —
  `build_web.cmd` ile yeni zip → cPanel'e yükleyip mevcut dosyaların üzerine çıkarın. Sıra önemli: yeni arayüz henüz yayında olmayan bir
  API uç noktasını çağırırsa o sayfa hata verir. Zip'i yükledikten sonra tarayıcıda Ctrl+F5 (önbelleği atlayarak yenile).
