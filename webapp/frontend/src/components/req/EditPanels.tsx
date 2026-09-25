"use client";

import { useState } from "react";
import { fmtDate, money, num, parseNum, qty, ReqDetail, toInput } from "@/lib/api";
import { Act, btn, btnPrimary } from "./Actions";
import { CatalogAdd, ItemRow, ItemRows, nextUid, rowsInvalid } from "./ItemRows";
import { QuoteBreakdown, QuoteDocs } from "./Quote";
import { Callout, DataTable, Metric, NumField, SectionTitle } from "./ui";
import { usePreview } from "./usePreview";

// Düzenlenebilir aşama panelleri (Fiyat / Gümrük / Teklif) — talepler.py::_panel_fiyat/_panel_gumruk/_panel_teklif'in
// düzenleme dalları. Değerler metin olarak tutulur (virgül/nokta kabul); kaydederken sayıya çevrilir, sunucu yeniden doğrular.
// Form durumu sunucudan gelen `updated_at` değişince (kayıttan sonra) üst bileşende `key` ile sıfırlanır.

type FormProps = { req: ReqDetail; act: Act; busy: boolean };

/** Sayıya çevir; boş/geçersiz → null (gönderim için). */
const val = (s: string): number | null => {
  const n = parseNum(s);
  return n === null || Number.isNaN(n) ? null : n;
};
/** Geçersiz (sayı değil) ya da negatif mi? Boş geçerlidir. */
const bad = (s: string): boolean => {
  const n = parseNum(s);
  return n !== null && (Number.isNaN(n) || n < 0);
};

const field =
  "w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500";

// ---------------------------------------------------------------- Fiyat Araştırması

export function FiyatForm({ req, act, busy }: FormProps) {
  const [rows, setRows] = useState(() =>
    Object.fromEntries(req.lines.map((l) => [l.id, { cost: toInput(l.unit_cost), supplier: l.supplier_id ? String(l.supplier_id) : "" }])),
  );
  const patch = (id: number, p: Partial<{ cost: string; supplier: string }>) =>
    setRows((r) => ({ ...r, [id]: { ...r[id], ...p } }));

  const total = req.lines.reduce((sum, l) => sum + l.qty * (val(rows[l.id].cost) ?? 0), 0);
  const invalid = req.lines.some((l) => bad(rows[l.id].cost));
  const payload = (advance: boolean) => ({
    lines: req.lines.map((l) => ({
      id: l.id,
      unit_cost: val(rows[l.id].cost),
      supplier_id: rows[l.id].supplier ? Number(rows[l.id].supplier) : null,
    })),
    advance,
  });

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        Çin ofisinden / tedarikçiden gelen birim alış fiyatlarını girin. Katalogdaki son alış fiyatı referans içindir.
      </p>
      {req.supplier_options.length === 0 && (
        <p className="text-xs text-zinc-500">Tedarikçi listesi boş — önce Kişiler &gt; Tedarikçiler&apos;den ekleyin.</p>
      )}
      <DataTable
        rows={req.lines}
        columns={[
          { header: "Ürün", render: (l) => l.name },
          {
            header: "Tedarikçi",
            render: (l) => (
              <select
                aria-label={`Tedarikçi: ${l.name}`}
                value={rows[l.id].supplier}
                onChange={(e) => patch(l.id, { supplier: e.target.value })}
                className="max-w-48 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm outline-none focus:border-sky-500"
              >
                <option value="">-</option>
                {req.supplier_options.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            ),
          },
          { header: "Adet", align: "right", render: (l) => qty(l.qty) },
          { header: "Katalog Son Alış", align: "right", render: (l) => num(l.catalog_last_cost) },
          {
            header: `Birim Alış (${req.currency})`,
            align: "right",
            render: (l) => (
              <NumField
                label={`Birim alış: ${l.name}`}
                value={rows[l.id].cost}
                invalid={bad(rows[l.id].cost)}
                onChange={(v) => patch(l.id, { cost: v })}
              />
            ),
          },
        ]}
      />
      <div className="max-w-xs">
        <Metric label="Toplam ürün alış maliyeti" value={money(total, req.currency)} />
      </div>
      {invalid && <Callout tone="warn">Geçersiz ya da negatif bir tutar girilmiş; kırmızı alanları düzeltin.</Callout>}
      <div className="flex flex-wrap gap-2">
        <button className={btn} disabled={busy || invalid} onClick={() => act("/fiyat", payload(false), { ok: "Kaydedildi." })}>
          💾 Kaydet
        </button>
        <button
          className={btnPrimary}
          disabled={busy || invalid}
          onClick={() => act("/fiyat", payload(true), { ok: "Sonraki aşamaya aktarıldı." })}
        >
          Kaydet ve Gümrük&apos;e Aktar →
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Gümrük & Lojistik

type CostRow = { uid: number; label: string; kind: string; amount: string };


export function GumrukForm({ req, act, busy }: FormProps) {
  const cur = req.currency;
  const [rows, setRows] = useState(() =>
    Object.fromEntries(req.lines.map((l) => [l.id, { customs: toInput(l.unit_customs), logistics: toInput(l.unit_logistics) }])),
  );
  const [costs, setCosts] = useState<CostRow[]>(() =>
    req.costs.map((c) => ({ uid: nextUid(), label: c.label, kind: c.kind, amount: toInput(c.amount) })),
  );
  const patchRow = (id: number, p: Partial<{ customs: string; logistics: string }>) => setRows((r) => ({ ...r, [id]: { ...r[id], ...p } }));
  const patchCost = (u: number, p: Partial<CostRow>) => setCosts((cs) => cs.map((c) => (c.uid === u ? { ...c, ...p } : c)));

  const linePayload = req.lines.map((l) => ({ id: l.id, unit_customs: val(rows[l.id].customs), unit_logistics: val(rows[l.id].logistics) }));
  const costPayload = costs.map((c) => ({ label: c.label.trim(), amount: val(c.amount), kind: c.kind }));
  const preview = usePreview(req.code, { lines: linePayload, costs: costPayload });
  const summary = preview?.cost_summary ?? req.cost_summary;
  const hint = preview ? preview.hint : req.delivery_hint;

  const invalid = req.lines.some((l) => bad(rows[l.id].customs) || bad(rows[l.id].logistics)) || costs.some((c) => bad(c.amount));
  const send = (advance: boolean) =>
    act("/gumruk", { lines: linePayload, costs: costPayload, advance }, { ok: advance ? "Sonraki aşamaya aktarıldı." : "Kaydedildi." });

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        Teslimat tipi: <b className="text-zinc-300">{req.delivery_type}</b>. Ürün başına gümrük ve lojistik masrafını ayrı girin (gümrük yoksa 0
        yazın; lojistik boş kalabilir). Ürüne bağlı olmayan masrafları aşağıya tür seçerek ekleyin.
      </p>
      <DataTable
        rows={req.lines}
        columns={[
          { header: "Ürün", render: (l) => l.name },
          { header: "GTİP", render: (l) => l.hs_code || "-" },
          { header: "Adet", align: "right", render: (l) => qty(l.qty) },
          { header: `Birim Alış (${cur})`, align: "right", render: (l) => num(l.unit_cost) },
          {
            header: `Birim Gümrük (${cur})`,
            align: "right",
            render: (l) => (
              <NumField
                label={`Birim gümrük: ${l.name}`}
                value={rows[l.id].customs}
                invalid={bad(rows[l.id].customs)}
                onChange={(v) => patchRow(l.id, { customs: v })}
              />
            ),
          },
          {
            header: `Birim Lojistik (${cur})`,
            align: "right",
            render: (l) => (
              <NumField
                label={`Birim lojistik: ${l.name}`}
                value={rows[l.id].logistics}
                invalid={bad(rows[l.id].logistics)}
                onChange={(v) => patchRow(l.id, { logistics: v })}
              />
            ),
          },
        ]}
      />

      <SectionTitle>Ekstra masraflar</SectionTitle>
      <p className="-mt-1 text-xs text-zinc-500">Ürüne bağlı olmayanlar: nakliye, ekspertiz, gümrük müşavir ücreti vb.</p>
      {costs.length > 0 && (
        <ul className="space-y-2">
          {costs.map((c) => (
            <li key={c.uid} className="flex flex-wrap items-center gap-2">
              <input
                aria-label="Masraf açıklaması"
                placeholder="Masraf"
                value={c.label}
                onChange={(e) => patchCost(c.uid, { label: e.target.value })}
                className={`${field} min-w-48 flex-1`}
              />
              <select
                aria-label="Masraf türü"
                value={c.kind}
                onChange={(e) => patchCost(c.uid, { kind: e.target.value })}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm outline-none focus:border-sky-500"
              >
                {req.cost_kinds.map((k) => (
                  <option key={k.key} value={k.key}>
                    {k.label}
                  </option>
                ))}
              </select>
              <NumField label={`Tutar (${cur})`} value={c.amount} invalid={bad(c.amount)} onChange={(v) => patchCost(c.uid, { amount: v })} />
              <button aria-label="Masrafı sil" className={btn} onClick={() => setCosts((cs) => cs.filter((x) => x.uid !== c.uid))}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        className={btn}
        onClick={() => setCosts((cs) => [...cs, { uid: nextUid(), label: "", kind: req.cost_kinds.find((k) => k.key === "lojistik")?.key ?? "diger", amount: "" }])}
      >
        ＋ Masraf ekle
      </button>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Metric label="Toplam gümrük" value={money(summary.customs, cur)} />
        <Metric label="Toplam lojistik" value={money(summary.logistics, cur)} />
        <Metric label="Diğer masraflar" value={money(summary.other, cur)} />
      </div>
      {hint && <Callout tone="warn">{hint}</Callout>}
      {invalid && <Callout tone="warn">Geçersiz ya da negatif bir tutar girilmiş; kırmızı alanları düzeltin.</Callout>}
      <div className="flex flex-wrap gap-2">
        <button className={btn} disabled={busy || invalid} onClick={() => send(false)}>
          💾 Kaydet
        </button>
        <button className={btnPrimary} disabled={busy || invalid} onClick={() => send(true)}>
          Kaydet ve Teklif Aşamasına Aktar →
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Teklif

export function TeklifForm({ req, act, busy }: FormProps) {
  const t = req.teklif!;
  const cur = req.currency;
  const [margin, setMargin] = useState(t.margin_pct !== null ? toInput(t.margin_pct) : "20");
  const [taxOn, setTaxOn] = useState(t.tax_enabled);
  const [tax, setTax] = useState(toInput(t.tax_pct));
  const [valid, setValid] = useState(String(t.valid_days));
  const [terms, setTerms] = useState(t.payment_terms);
  const [mode, setMode] = useState(t.logistics_mode);
  const [ownLogi, setOwnLogi] = useState(t.logistics_margin_pct !== null);
  const [logiMargin, setLogiMargin] = useState(toInput(t.logistics_margin_pct ?? t.margin_pct ?? 20));
  const [pricing, setPricing] = useState(() =>
    Object.fromEntries(t.line_pricing.map((p) => [p.id, { margin: toInput(p.margin_pct), override: toInput(p.sale_price_override) }])),
  );
  const patchP = (id: number, p: Partial<{ margin: string; override: string }>) => setPricing((r) => ({ ...r, [id]: { ...r[id], ...p } }));

  const teklif = {
    margin_pct: val(margin),
    logistics_margin_pct: mode === "ayri" && ownLogi ? val(logiMargin) : null,
    tax_enabled: taxOn,
    tax_pct: val(tax),
    valid_days: val(valid),
    payment_terms: terms,
    logistics_mode: mode,
  };
  const lines = t.line_pricing.map((p) => ({ id: p.id, margin_pct: val(pricing[p.id].margin), sale_price_override: val(pricing[p.id].override) }));
  const preview = usePreview(req.code, { teklif, lines });
  // İlk önizleme gelene kadar sunucudaki kayıtlı hesap gösterilir (form değerleri henüz kayıtlıyla aynı)
  const q = preview ? preview.quote : t.quote;
  const hint = preview ? preview.hint : t.hint;
  const missing = preview ? Boolean(preview.missing_unit_cost) : t.missing_unit_cost;

  const validDays = val(valid);
  const invalid =
    bad(margin) || bad(tax) || bad(logiMargin) || bad(valid) || val(margin) === null || validDays === null || validDays < 1 ||
    t.line_pricing.some((p) => bad(pricing[p.id].margin) || bad(pricing[p.id].override));
  const send = (action: "save" | "pdf" | "sent", ok: string) => act("/teklif", { teklif, lines, action }, { ok });
  const pricingCaption = q ? q.rows.filter((r) => r.kind === "urun").map((r) => `${r.name}: ${r.margin_label}`).join(" · ") : "";

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs text-zinc-500">Varsayılan kâr marjı (%)</label>
          <NumField label="Varsayılan kâr marjı" className="w-full" value={margin} invalid={bad(margin) || val(margin) === null} onChange={setMargin} />
          <p className="mt-1 text-xs text-zinc-500">Maliyetin üzerine eklenir (markup). Kendi marjı/fiyatı olmayan tüm ürünler bunu kullanır.</p>
        </div>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input type="checkbox" checked={taxOn} onChange={(e) => setTaxOn(e.target.checked)} className="h-4 w-4" />
            KDV uygula
          </label>
          <div className={taxOn ? "" : "opacity-50"}>
            <label className="mb-1 block text-xs text-zinc-500">KDV (%)</label>
            <NumField label="KDV oranı" className="w-full" value={tax} invalid={taxOn && bad(tax)} onChange={setTax} />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-xs text-zinc-500">Geçerlilik (gün)</label>
          <NumField label="Geçerlilik günü" className="w-full" value={valid} invalid={bad(valid) || validDays === null || validDays < 1} onChange={setValid} />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs text-zinc-500">Ödeme koşulları</label>
        <textarea
          value={terms}
          onChange={(e) => setTerms(e.target.value)}
          rows={3}
          placeholder={"Her satır PDF'de ayrı bir madde olarak görünür.\nÖrn:\n%50 peşin\n%50 sevkiyat öncesi"}
          className={field}
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="mb-1 text-xs text-zinc-500">Lojistik teklifte nasıl görünsün?</legend>
        <div className="flex flex-wrap gap-4 text-sm text-zinc-300">
          {req.logistics_modes.map((m) => (
            <label key={m.key} className="flex items-center gap-2">
              <input type="radio" name="lmode" checked={mode === m.key} onChange={() => setMode(m.key)} />
              {m.label}
            </label>
          ))}
        </div>
        <p className="text-xs text-zinc-500">
          Toplam tutar aynı kalır, yalnızca sunum değişir. &apos;Ayrı kalem&apos;: ürünlerin ham fiyatı değişmez, lojistik tek satır olarak eklenir.
        </p>
        {mode === "ayri" && (
          <div className="flex flex-wrap items-center gap-3 text-sm text-zinc-300">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={ownLogi} onChange={(e) => setOwnLogi(e.target.checked)} className="h-4 w-4" />
              Lojistik için ayrı kâr marjı kullan
            </label>
            {ownLogi && <NumField label="Lojistik kâr marjı" value={logiMargin} invalid={bad(logiMargin)} onChange={setLogiMargin} />}
          </div>
        )}
      </fieldset>

      <div>
        <SectionTitle>Ürün bazlı kâr marjı / doğrudan satış fiyatı (opsiyonel)</SectionTitle>
        <p className="mb-2 text-xs text-zinc-500">
          İki sütundan yalnızca biri geçerli olur: &apos;Doğrudan Satış Fiyatı&apos; doluysa &apos;Kâr Marjı %&apos; yok sayılır. Boş (ya da 0) = varsayılan marjdan
          hesapla.
        </p>
        <DataTable
          rows={t.line_pricing}
          columns={[
            { header: "Ürün", render: (p) => p.name },
            { header: "Adet", align: "right", render: (p) => qty(p.qty) },
            {
              header: "Maliyet",
              align: "right",
              render: (p) => num(preview?.line_costs?.[t.line_pricing.indexOf(p)] ?? p.cost),
            },
            {
              header: "Kâr Marjı %",
              align: "right",
              render: (p) => (
                <NumField label={`Kâr marjı: ${p.name}`} value={pricing[p.id].margin} invalid={bad(pricing[p.id].margin)} onChange={(v) => patchP(p.id, { margin: v })} />
              ),
            },
            {
              header: "Doğrudan Satış Fiyatı",
              align: "right",
              render: (p) => (
                <NumField label={`Doğrudan satış fiyatı: ${p.name}`} value={pricing[p.id].override} invalid={bad(pricing[p.id].override)} onChange={(v) => patchP(p.id, { override: v })} />
              ),
            },
          ]}
        />
        {pricingCaption && (
          <p className="mt-2 text-xs text-zinc-500">
            <b>Fiyatlandırma:</b> {pricingCaption}
          </p>
        )}
      </div>

      {q ? (
        <QuoteBreakdown
          q={q}
          cur={cur}
          taxEnabled={taxOn}
          taxPct={val(tax) ?? 0}
          mode={mode}
          missingUnitCost={missing}
          hint={hint}
          marginPct={val(margin)}
          warnPct={req.margin_warn_pct}
        />
      ) : (
        <Callout tone="info">Kâr marjı girildiğinde teklif hesabı burada görünür.</Callout>
      )}

      {t.quote_sent_at && <Callout tone="success">Teklif müşteriye iletildi ({fmtDate(t.quote_sent_at)}).</Callout>}
      <QuoteDocs req={req} />

      {invalid && <Callout tone="warn">Geçersiz değer var (kâr marjı, KDV, geçerlilik günü ya da tablo hücreleri); kırmızı alanları düzeltin.</Callout>}
      <div className="flex flex-wrap gap-2">
        <button className={btn} disabled={busy || invalid} onClick={() => send("save", "Kaydedildi.")}>
          💾 Kaydet
        </button>
        <button className={btn} disabled={busy || invalid} onClick={() => send("pdf", "Teklif PDF'i hazır.")}>
          📄 Teklif PDF&apos;i oluştur
        </button>
        <button className={btnPrimary} disabled={busy || invalid} onClick={() => send("sent", "Sonraki aşamaya aktarıldı.")}>
          ✉️ Müşteriye iletildi olarak işaretle ve Karar&apos;a geç →
        </button>
      </div>
      <p className="text-xs text-zinc-500">
        Sıra: PDF&apos;i oluşturun, indirip müşteriye gönderin, sonra &apos;iletildi&apos; olarak işaretleyin. İçerik değişirse yeni revizyon (-R2) açılır.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------- Talep (ürün satırları + teslimat tipi)

export function TalepForm({ req, act, busy }: FormProps) {
  const [deliveryType, setDeliveryType] = useState(req.delivery_type);
  const [items, setItems] = useState<ItemRow[]>(() =>
    req.lines.map((l) => ({ uid: nextUid(), id: l.id, productId: l.product_id ? String(l.product_id) : "", qty: toInput(l.qty), fallbackName: l.name })),
  );

  // Ürünü seçilmemiş satırlar kaydedilirken atılır (Streamlit'teki gibi); seçilmiş satırın adedi 0'dan büyük olmalı
  const invalid = rowsInvalid(items);
  const payload = (advance: boolean) => ({
    delivery_type: deliveryType,
    items: items.map((r) => ({ id: r.id, product_id: r.productId ? Number(r.productId) : null, qty: val(r.qty) })),
    advance,
  });

  return (
    <div className="space-y-4">
      <div className="text-sm text-zinc-300">
        <b>Müşteri:</b> {req.customer} · <b>Para birimi:</b> {req.currency}
      </div>
      {req.notes && <div className="text-sm text-zinc-500">Not: {req.notes}</div>}

      <fieldset className="space-y-1">
        <legend className="mb-1 text-xs text-zinc-500">Teslimat tipi</legend>
        <div className="flex flex-wrap gap-4 text-sm text-zinc-300">
          {req.delivery_types.map((d) => (
            <label key={d} className="flex items-center gap-2">
              <input type="radio" name="deliv" checked={deliveryType === d} onChange={() => setDeliveryType(d)} />
              {d}
            </label>
          ))}
        </div>
        <p className="text-xs text-zinc-500">
          Gümrük teslim: ürün gümrükte teslim edilir. Kapı teslim: müşterinin adresine kadar. Masrafları buna göre girin.
        </p>
      </fieldset>

      <SectionTitle>Ürünler</SectionTitle>
      <ItemRows items={items} setItems={setItems} products={req.product_options} />
      <CatalogAdd busy={busy} onAdd={(name, hs) => act("/catalog-product", { name, hs_code: hs }, { ok: `'${name.trim()}' kataloğa eklendi.` })} />

      {invalid && <Callout tone="warn">Seçili ürünlerin adedi 0&apos;dan büyük bir sayı olmalı; kırmızı alanları düzeltin.</Callout>}
      <div className="flex flex-wrap gap-2">
        <button className={btn} disabled={busy || invalid} onClick={() => act("/talep", payload(false), { ok: "Kaydedildi." })}>
          💾 Kaydet
        </button>
        <button className={btnPrimary} disabled={busy || invalid} onClick={() => act("/talep", payload(true), { ok: "Sonraki aşamaya aktarıldı." })}>
          Kaydet ve Fiyat Araştırması&apos;na Aktar →
        </button>
      </div>
    </div>
  );
}
// ---------------------------------------------------------------- Teslim (makbuz oluşturma)

export function TeslimForm({ req, act, busy }: FormProps) {
  const t = req.teslim!;
  const [qtys, setQtys] = useState<Record<number, string>>({});
  const [by, setBy] = useState("");
  const [to, setTo] = useState(t.customer);
  const over = (r: (typeof t.rows)[number]) => (val(qtys[r.line_id] ?? "") ?? 0) > r.remaining + 1e-9;
  const invalid = t.rows.some((r) => bad(qtys[r.line_id] ?? "") || over(r));
  const anyQty = t.rows.some((r) => (val(qtys[r.line_id] ?? "") ?? 0) > 0);

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        Teslim edilecek ürünleri ve adetlerini girin; kısmi (ön) teslimat da yapılabilir. Her teslimat için ayrı bir makbuz (OUT/NNNN) oluşur; tüm ürünler
        tam teslim edilince REQ tamamlanabilir.
      </p>
      <DataTable
        rows={t.rows}
        columns={[
          { header: "Ürün", render: (r) => r.name },
          { header: "Sipariş Edilen", align: "right", render: (r) => qty(r.ordered) },
          { header: "Şimdiye Kadar Teslim", align: "right", render: (r) => qty(r.delivered) },
          { header: "Kalan", align: "right", render: (r) => qty(r.remaining) },
          {
            header: "Bu Teslimatta",
            align: "right",
            render: (r) => (
              <NumField
                label={`Bu teslimatta: ${r.name}`}
                value={qtys[r.line_id] ?? ""}
                invalid={bad(qtys[r.line_id] ?? "") || over(r)}
                onChange={(v) => setQtys((q) => ({ ...q, [r.line_id]: v }))}
                className="w-24"
              />
            ),
          },
        ]}
      />
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-zinc-500">Teslim Eden</label>
          <input aria-label="Teslim Eden" value={by} onChange={(e) => setBy(e.target.value)} className={field} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-zinc-500">Teslim Alan</label>
          <input aria-label="Teslim Alan" value={to} onChange={(e) => setTo(e.target.value)} className={field} />
        </div>
      </div>
      {invalid && <Callout tone="warn">Geçersiz ya da kalan adedi aşan bir miktar girilmiş; kırmızı alanları düzeltin.</Callout>}
      <button
        className={btnPrimary}
        disabled={busy || invalid || !anyQty}
        onClick={() =>
          act(
            "/deliveries",
            { rows: t.rows.map((r) => ({ line_id: r.line_id, qty: val(qtys[r.line_id] ?? "") })), delivered_by: by, delivered_to: to },
            { ok: "Teslimat makbuzu oluşturuldu." },
          )
        }
      >
        📄 Teslimat Makbuzu Oluştur
      </button>
    </div>
  );
}