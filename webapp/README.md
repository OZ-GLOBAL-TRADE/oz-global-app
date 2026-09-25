# Jarvis Web — Streamlit'ten çıkış (yeni arayüz)

Streamlit'in gerçek sınırlarını (sert yenilemede oturum düşmesi, tam sayfa yeniden çalışma, kısıtlı
UI bileşenleri) aşmak için ayrı bir FastAPI + Next.js uygulaması. Mevcut `jarvis/` paketi (services.py,
pipeline.py, models.py, analytics.py, ...) **hiç değişmedi** — bu yeni katman ona ince bir HTTP/oturum
arayüzü ekliyor. Eski Streamlit uygulaması (`jarvis_app.py`) ekip bu yeni arayüze geçene kadar aynı
Supabase'e bağlı olarak çalışmaya devam ediyor.

## Durum (2026-09-25)

**Hazır ve tarayıcıda uçtan uca doğrulanmış:**
- Giriş / çıkış (`jarvis.services.authenticate`, bcrypt) + imzalı HttpOnly oturum çerezi (sert
  yenilemede DÜŞMÜYOR — Streamlit'in bilinen eksiğinin gerçek düzeltmesi).
- Sol menülü ortak kabuk (`components/AppShell.tsx`) — her yeni sayfa bunu sarmalıyor, kullanıcı/çıkış
  başlığı tekrar yazılmıyor.
- Panel: KPI kartları (`jarvis.analytics` ile aynı hesap).
- Talepler: **yalnızca liste** — arama (REQ kodu/müşteri/ürün, 200ms debounce), durum sekmeleri
  (Aktif/Tamamlanan/Rafa Kaldırılan/Tümü), aşama etiketi, teklif tutarı (rol bazlı gizleme
  `pl.can_view_stage` ile Streamlit'teki gibi).

- **Talepler → REQ detayı (SALT OKUNUR)** (`/talepler/[code]`, listede satıra tıklayınca): aşama stepper'ı,
  rol bazlı görünen aşama sekmeleri, 8 aşama paneli (Talep/Fiyat/Gümrük/Teklif/Karar/Sipariş/Lojistik/Teslim),
  Geçmiş (sistem kaydı), sağdan kayan **Notlar & Görevler** çekmecesi (not/görev/dosya listesi), teklif ve
  teslimat makbuzu PDF indirme, REQ dosyası indirme. Tarayıcıda admin ve gümrükçü rolleriyle doğrulandı.

- **REQ yazma — 1. dilim (2026-09-25, tarayıcıda doğrulandı):** aşama ilerletme (kapı eksikleri listelenir),
  müşteri kararı (onay/ret + sebep), Sipariş paneli formu (müşteri PO no + satın alma onayı + kaydet/aktar),
  Teklif aşamasında "PDF oluştur" ve "iletildi işaretle + Karar'a geç", "Önceki aşamaya dön" / "Rafa kaldır"
  (hazır sebep listesi + "Diğer"), "Yeniden aç", Notlar & Görevler yazma (not ekle, görev ata/tamamla/iptal,
  dosya yükle/sil). Gümrükçü rolünde yönetici eylemleri gizli, yalnızca kendi aşamasını ilerletebilir.

- **REQ yazma — 2. dilim: fiyatlama çekirdeği (2026-09-25, tarayıcıda doğrulandı):** düzenlenebilir **Fiyat**
  (birim alış + tedarikçi seçimi), **Gümrük** (birim gümrük/lojistik + ekstra masraflar, canlı toplamlar ve
  teslimat-tipi uyarısı) ve **Teklif** (marj, KDV, geçerlilik, ödeme koşulları, lojistik gösterimi, ürün bazlı
  marj/doğrudan fiyat, canlı teklif önizlemesi, PDF, iletildi + Karar'a geç) panelleri. Fiyat → Gümrük → Teklif →
  Karar zinciri yeni arayüzden uçtan uca çalıştı. Gümrükçü kendi aşamasını ilerletince REQ görüş alanından çıkar
  ve arayüz listeye döner (`_write` → `{hidden: true}`).

- **REQ yazma — 3. dilim: Talep + Teslim (2026-09-25, tarayıcıda doğrulandı):** **Talep** formu (teslimat tipi,
  ürün satırı ekle/sil/adet, katalogda olmayan ürün ekleme — kaydedilmemiş düzenlemeleri silmez) ve **Teslim**
  formu (kısmi/tam teslimat makbuzu, Teslim Eden/Alan, kalan adedi aşamaz; tüm ürünler teslim edilince
  "REQ'yi tamamla" görünür). Artık bir REQ'nin bütün yaşam döngüsü (Talep → Tamamlandı) Streamlit'e dönmeden
  yeni arayüzden yürüyor; endpoint'ler: `talep`, `catalog-product`, `deliveries`.

- **Yeni REQ açma diyaloğu (2026-09-25, tarayıcıda doğrulandı):** Talepler listesinde "＋ Yeni REQ" (yalnızca
  `can_create`, yani yönetici roller). Müşteri seç ya da diyalogdan hızlı ekle (kısa kod, Son REQ no, VKN, adres),
  "Kod otomatik verilecek: X" canlı gösterilir, para birimi, teslimat tipi, ürün satırları, katalogda olmayan ürün
  ekleme, not. Endpoint'ler: `GET /api/new-req/options`, `POST /api/customers`, `POST /api/catalog-products`,
  `POST /api/reqs` (kodu sunucu üretir). **Artık bir REQ'nin bütün yaşamı (açma → tamamlama) yeni arayüzde.**
  Ürün satırı düzenleyicisi ve katalog ekleme, Talep paneliyle ortak (`components/req/ItemRows.tsx`).

- **Düzeltmeler + liste (2026-09-25, tarayıcıda doğrulandı):** başlıkta "✏️ Düzelt" (REQ no — yalnızca sayı,
  müşteri sayacı buna göre devam eder; para birimi — her aşamada), Talep dışı aşamalarda "🔢 Adetleri düzelt"
  (teslim edilen/kargoya ayrılan miktarın altına inilemez). REQ no değişince sunucu yeni kodla yeniden okur
  (`_write` bir `str` dönerse onu yeni kod sayar) ve sayfa yeni adrese geçer. Talepler listesinde onay kutulu çoklu
  seçim (kutucuk satırı açmaz) + **Excel indirme** (`POST /api/reqs/export`, `openpyxl`; yalnızca kullanıcının
  görebildiği REQ'ler, Teklif sütunu yetkiye göre, tutar sayısal hücre + ayrı para birimi sütunu) ve **Aşama
  Görünümü** (Kanban: aktif REQ'ler aşama sütunlarında, tamamlanan/rafa kaldırılanlar altta açılır liste).

- **Panel tam (2026-09-25, tarayıcıda doğrulandı):** KPI kartları, aşama bazlı sayı ve ortalama süre grafikleri
  (+ açılıştan tamamlanmaya ortalama, en uzun bekleme notu), **Teklif & Kâr** (gösterim para birimi USD/EUR/TRY —
  tüm teklifler canlı ECB kuruyla çevrilir; toplam teklif/kâr, kâr oranı, kazanma oranı; Yönetici / Ürün / Müşteri /
  Zaman sekmeleri), Son Hareketler, sağdan kayan **Günlük Brifing** (`POST /api/panel/briefing`; anahtar yoksa gerçek
  veriden maddeler, varsa Claude yorumu). Hesaplar `jarvis/analytics.py::financial_summary`'de (saf fonksiyon,
  `tests/test_analytics_summary.py` — 5 test); endpoint yalnızca JSON'lar. Grafikler bağımlılıksız CSS
  (`components/charts.tsx`), her çubuk `aria-label` taşır. **Streamlit'ten bilinçli fark:** kâr/teklif verisi yalnızca
  teklif aşamasını görebilen rollere gider (gümrükçünün Panel'inde `financials: null`, Son Hareketler'de Teklif
  sütunu yok); Streamlit'te gümrükçü de toplam kârı görüyordu.

- **Kişiler ve Ürünler (2026-09-25, tarayıcıda doğrulandı):** `/kisiler` (Müşteriler/Tedarikçiler sekmeleri) ve `/urunler`;
  satır içi düzenleme (`components/EditableTable.tsx`: yalnızca DEĞİŞEN hücreler kaydedilir, değişen hücre vurgulanır,
  "Vazgeç", arama, 100'er satır), yeni müşteri/tedarikçi/ürün ekleme formları, benzer ürün uyarısı. Ad/kod düzenlenemez;
  gümrükçü Kişiler'de salt okunur, Ürünler'de yalnızca GTİP'i düzenler (`editable_fields`, sunucu ayrıca zorlar).
  Backend: `catalog.py` (APIRouter) + `deps.py` (ortak `get_actor`); seçenek listeleri artık `pipeline.py`'de tek kaynak.
- **Logo:** `public/logo.png` (kırpılmış) beyaz bir kart içinde giriş ekranı ve kenar çubuğunda (`components/Logo.tsx`; logo lacivert/şeffaf
  olduğu için koyu zeminde okunmaz); favicon `src/app/icon.png` (amblem). Teklif/teslimat PDF'lerinde hâlâ metin wordmark var
  (`quote_pdf.py`/`delivery_pdf.py`); logo oraya da konabilir (istenirse).
- **Testler:** `tests/test_webapp_api.py` (15 test) web API'sini gerçek HTTP yığınıyla (FastAPI TestClient) sınar: oturum, 400+errors
  biçimi, kapı hataları, gümrükçüye veri gizleme + `hidden` yanıtı, önizlemenin veri yazmaması, indirme başlıkları/yetkisi, Excel,
  panel kur çevrimi, kişiler/ürünler beyaz listeleri, canlı-mod açılış korumaları. Bilerek hata sokularak (mutasyon) yakalandıkları doğrulandı.

- **Silme (çöp kutusu) + düzeltmeler (2026-09-25, tarayıcıda doğrulandı):** kullanıcı kararı = "çöp kutusu + kalıcı sil".
  **Silme geri alınabilir**: `deleted_at`/`deleted_by` (`models.SoftDeleteMixin`; REQ, müşteri/tedarikçi, ürün, not/görev). Silinen kayıt `services`
  katmanındaki TÜM listelerden/aramalardan çıkar (Streamlit, web, AI sohbet, analitik aynı kaynağı kullandığı için birlikte); `get_req(...,
  include_deleted=True)` yalnızca çöp kutusu işlemleri içindir. Yetkiler: sil/geri yükle = yönetici roller (Admin + Ürün Yöneticisi); **kalıcı sil =
  yalnızca Admin, yalnızca çöp kutusundaki kayıt, kaydın adını/REQ kodunu yazarak** (arayüzde `ConfirmDialog` + serviste `_typed_confirm`).
  Kurallar: kargoya bağlı REQ silinemez; REQ'i olan müşteri (silinmişler dahil) kalıcı silinemez; silinen kaydın adı yeniden kullanılamaz
  ("silinenler arasında, geri yükleyin" — DB benzersizlik kuralı); silinmiş müşteriye REQ açılamaz / silinmiş ürün yeni satıra eklenemez ama
  mevcut REQ satırları korunur (`save_items`: silinmiş/kalıcı silinmiş ürünlü satırlar Talep kaydında düşmez); not/görev silme = yazan kişi ya da
  yönetici, içerik gizlenir, geçmişe içeriksiz "Not silindi." kaydı düşer.
  **Düzeltmeler**: müşteri/tedarikçi/ürün ADI (çakışma denetimli), müşteri KISA KODU (yalnızca yeni REQ'leri etkiler; başka müşterinin REQ koduyla
  çakışan kod verilemez), REQ'in MÜŞTERİSİ (REQ kodu değişmez; teklif/teslimat makbuzu çıkmışsa reddedilir), REQ notu ve teslimat tipi HER aşamada.
  Uç noktalar: `POST /api/reqs/{code}/delete|customer|meta|notes/{id}/delete`, `POST /api/partners/{id}/delete`, `POST /api/products/{id}/delete`,
  `GET /api/trash/{reqs|customers|suppliers|products}`, `POST /api/trash/{kind}/{ident}/restore|purge` (`trash.py`). Arayüz: satır sonunda 🗑️,
  Kişiler/Ürünler altında "🗑️ Silinenler" bölümü, Talepler'de "🗑️ Silinenler" görünümü, REQ'te "🗑️ REQ'i sil" + "✏️ Düzelt" menüsü.
  **Göç**: `migrations/versions/faf3aae762b9` (yalnızca nullable sütunlar). Canlıya alırken: backend'i push et → Render açılışta `init_db()` sütunları
  ekler → sonra `alembic stamp head` (bkz. CLAUDE.md "Supabase'e migration uygulama").

**Henüz yok (sırayla, önerilen adım):**
1. Kargo (CRG), Ayarlar, Jarvis AI sohbet (sol menüde henüz yok).
2. "Tedarikçi Ara (Jarvis AI)" (`sv.search_suppliers`, Fiyat aşaması; Gemini anahtarı gerekir).

**Bilinen yerel-geliştirme farkı:** SQLite tarihleri saat dilimsiz (UTC) saklar; arayüz `new Date(iso)` ile bunu tarayıcı
saati sayar, Excel dışa aktarma ise UTC+3'e çevirir — yerelde aynı REQ için 3 saat fark görünür. Supabase/Postgres'te
tarihler saat dilimli olduğundan (`DateTime(timezone=True)`) ikisi de doğru. Yerel SQLite'ta karşılaştırma yaparken
akılda tutun.

Her adımda aynı desen: backend'e ince bir endpoint (`jarvis.services`'i çağırır, mantık eklemez) +
frontend'de bir sayfa/bileşen, isolated scratch-DB kopyasında tarayıcıda doğrula, gerçek DB'nin
değişmediğini kontrol et.

## Çalıştırma (yerel geliştirme)

Backend (proje kökünün `requirements.txt`'i + bu klasörün `requirements.txt`'i kurulu olmalı):

```bash
py -m uvicorn main:app --reload --port 8600 --app-dir webapp/backend
```

Frontend (ilk seferde `cd webapp/frontend && npm install`):

```bash
cd webapp/frontend
npm run dev
```

Tarayıcıda `http://localhost:3000`. Backend `http://localhost:8600`'de dinler; adres
`frontend/.env.local`'daki `NEXT_PUBLIC_API_URL` ile değiştirilebilir.

**Ortam değişkenleri** (backend, mevcut `jarvis/config.py` üzerinden okunur — `.env` ya da gerçek
deploy'da Secrets): `DATABASE_URL` (Supabase), `SESSION_SECRET` (rastgele, uzun bir metin — prod'da
mutlaka ayarlanmalı, yoksa dev-only sabit değer kullanılır ve GÜVENSİZDİR), `JARVIS_DEV_MODE=0`.

## Mimari

- **Backend** (`backend/main.py`): FastAPI, tüm iş mantığı için `jarvis.services`/`jarvis.pipeline`/
  `jarvis.analytics`'i doğrudan çağırır. Oturum Starlette'in `SessionMiddleware`'i (itsdangerous ile
  imzalı çerez) — `request.session["user_id"]`, her istekte `jarvis.services.to_actor` ile gerçek
  `Actor` nesnesine çevrilir; rol/şirket bazlı yetki kontrolleri hep `services.py` içinde kalır,
  burada tekrarlanmaz.
- **Frontend** (`frontend/`): Next.js (App Router) + TypeScript + Tailwind. `src/lib/api.ts` tek bir
  `fetch` sarmalayıcısı (`credentials: "include"` ile çerezi taşır). Sayfalar şimdilik Client Component
  (`"use client"`) — form durumu ve `fetch` gerektiği için; ekranlar büyüdükçe salt-okunur kısımlar
  Server Component'e taşınabilir.

### REQ detay endpoint'leri ve gizleme kuralı

- `GET /api/reqs/{code}` → `backend/req_detail.py::build`. **Rolün göremediği aşamanın verisi yanıta hiç
  girmez** (`teklif`/`karar`/`siparis`/`teslim` bölümleri `null` gelir; gümrükçüde kâr marjı, teklif, PO no,
  teslimat yok). Frontend'de "gizle" yapılmaz — veri hiç gönderilmez. Yeni bir aşama bölümü eklerken de
  `pl.can_view_stage(role, key)` ile koşullu ekleyin. Tip karşılığı: `frontend/src/lib/api.ts::ReqDetail`.
- `GET /api/attachments/{id}`, `/api/quotes/{id}/pdf`, `/api/deliveries/{id}/pdf`: yetki `sv.get_req` +
  `can_view_stage` ile kontrol edilir (yetkisiz → 404). Yanıtlar HER ZAMAN `Content-Disposition: attachment` +
  `nosniff` (kullanıcı yüklediği .html gibi bir dosya API kökeninde satır içi açılıp betik çalıştırmasın).
- **Yazma endpoint'leri** (`main.py`, hepsi `_write` yardımcısından geçer): `POST /api/reqs/{code}/` `advance`,
  `move-back`, `shelve`, `reopen`, `decision`, `siparis`, `quote`, `quote-sent`, `notes`, `tasks/{id}/complete|cancel`,
  `attachments` (ham gövde yükleme, ad `?filename=` ile — multipart bağımlılığı gerekmez), `DELETE attachments/{id}`.
  `_write`: REQ'i açar → işlemi yapar → `expire_all()` → tazelenmiş detayı döner (frontend durumu bununla değiştirir).
  `ServiceError` → global handler ile 400 `{detail, errors[]}`. Çok adımlı işlemler (Sipariş: kaydet + onay + ilerlet)
  ilk hatada durur, önceki adımlar zaten kaydedilmiştir; bu yüzden frontend hata sonrası detayı yeniden çeker.
  Yeni bir yazma endpoint'i eklerken: yetki kararını servise bırak, gövdeyi `_text()` ile temizle, dönüşte `_write`'ın
  detayını kullan. Sebep listeleri artık tek kaynak: `pipeline.MOVE_BACK_REASONS` / `SHELVE_REASONS`.
- **Fiyatlama endpoint'leri:** `POST /api/reqs/{code}/` `fiyat` (`lines:[{id,unit_cost,supplier_id}], advance`),
  `gumruk` (`lines:[{id,unit_customs,unit_logistics}], costs:[{label,amount,kind}], advance`), `teklif`
  (`teklif:{...alanlar}, lines:[{id,margin_pct,sale_price_override}], action: save|pdf|sent`) — Streamlit
  panellerindeki adım sırasının aynısı, ilk hatada durur. Eski `/quote` ve `/quote-sent` kalktı (Teklif formu karşılıyor).
- **Canlı önizleme = `POST /api/reqs/{code}/preview`** (`req_detail.preview`): kaydedilmemiş form değerleriyle
  `pl.calculate_quote` çalıştırır, hiçbir şey yazmaz. Teklif/maliyet hesabı frontend'de YENİDEN YAZILMAZ; form
  değişince `usePreview` (250 ms debounce) çağırır. Yetkisiz role yalnızca maliyet toplamı döner (`quote: null`).
- Sayılar formda **metin** olarak tutulur (`NumField`, virgül/nokta kabul), `parseNum`/`toInput` (`lib/api.ts`);
  geçersiz/negatif değer kırmızı işaretlenir ve kaydet düğmeleri kilitlenir, sunucu yine de doğrular. Form durumu
  `key={req.updated_at}` ile kayıttan sonra sunucudaki değerlerle yeniden başlar.
- Frontend yazma altyapısı: `page.tsx` içindeki `act(path, body, {method, ok})` + `busyRef` (çift tıklamayı engeller) +
  `FlashBanner`; bileşenler `components/req/Actions.tsx` (`StageActions`, `ReqControls`, `ReasonPicker`).
  Çekmece ve panel `req.can_*` bayraklarıyla düğme gösterir; asıl yetki servis katmanında.
- Frontend'de dinamik rota `app/talepler/[code]/page.tsx` bir Client Component; `useParams` ile kodu okur,
  bileşen `key={code}` ile bağlanır (REQ değişince durum sıfırlanır — efekt içinde `setState` lint hatası verir).
- Doğrulama deseni (bu makinede): gerçek `spark_dev.db`'ye DOKUNMADAN scratch kopya + backend sarmalayıcı script
  (`launch.json`'daki `env` alanı yok sayılıyor, bu yüzden `DATABASE_URL` script içinde ayarlanır). Tarayıcı
  panesi görünür değilse tıklama/ekran görüntüsü çalışmaz; `tabs_select` ile sekmeyi öne alın.

## Barındırma (canlıya alma) — ayrıntı için **`DEPLOY.md`**

Mevcut ozglobaltrade.com hosting'i paylaşımlı (cPanel) — Python/Node çalıştıramaz. Bu yüzden iki parça:
- **Arayüz = statik site** (`next.config.ts`: `output: "export"`, `trailingSlash`): `build_web.cmd <api-adresi>` →
  `dist/erp-web.zip` → cPanel'deki `erp.ozglobaltrade.com` belge köküne çıkarılır. `public/.htaccess` HTTPS yönlendirmesi
  ve güvenlik başlıklarını taşır. API adresi derleme anında gömülür (`NEXT_PUBLIC_API_URL`).
- **API = FastAPI** Render'da (`render.yaml` / `DEPLOY.md`), `api.ozglobaltrade.com` (DNS'te CNAME). Arayüz ve API aynı
  alan adının alt alanları olduğu için `SameSite=Lax` çerez çalışır.
- Statik dışa aktarma yüzünden **REQ kodu yolda değil sorgu parametresindedir**: `/talepler/detay/?code=DMH_REQ_04`
  (`reqHref()` — bağlantıları hep bununla üretin; `[kod]` gibi dinamik rota eklemeyin, `output: "export"` derlemesi bozulur).
- Backend canlı yapılandırması (ortam değişkenleri, `main.py` başında açıklı): `SESSION_SECRET` (canlıda ≥32 karakter yoksa
  uygulama AÇILMAZ), `WEB_ORIGINS`, `COOKIE_SAMESITE`, `JARVIS_DEV_MODE=0`; `/healthz` sağlık kontrolü; açılışta `init_db()`.
- Doğrulama (yerel): test derlemesi statik olarak sunulup canlı-mod backend (Secure çerez) ile tarayıcıda denendi (giriş,
  sert yenileme, derin bağlantı, yazma, yeniden adlandırma yönlendirmesi); backend Streamlit'siz temiz bir sanal ortamda
  yalnızca `webapp/backend/requirements.txt` ile kurulup PDF/Excel/panel/yazma testleri koşuldu. **Gerçek Render/cPanel/
  Supabase üzerinde henüz denenmedi.**
