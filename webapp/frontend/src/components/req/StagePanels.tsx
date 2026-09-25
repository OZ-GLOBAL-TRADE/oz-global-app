import { useState } from "react";
import { API_BASE, fmtDate, money, num, qty, ReqDetail } from "@/lib/api";
import { Act, btn, btnPrimary } from "./Actions";
import { FiyatForm, GumrukForm, TalepForm, TeklifForm, TeslimForm } from "./EditPanels";
import { QuoteBreakdown, QuoteDocs } from "./Quote";
import { Callout, Column, DataTable, Metric, SectionTitle } from "./ui";

// Sekiz aşama paneli. Her panel, jarvis/ui/talepler.py'deki aynı adlı _panel_* fonksiyonunun karşılığıdır.
// Aktif aşamada düzenleme yetkisi varsa (`editable`) forma yönlenir (EditPanels.tsx / SiparisForm); aksi halde salt okunur görünüm.

type Props = { req: ReqDetail; editable: boolean; act: Act; busy: boolean };

function PanelTalep({ req, editable, act, busy }: Props) {
  if (editable) return <TalepForm key={req.updated_at} req={req} act={act} busy={busy} />;
  return (
    <div className="space-y-4">
      <div className="text-sm text-zinc-300">
        <b>Müşteri:</b> {req.customer} · <b>Para birimi:</b> {req.currency} · <b>Teslimat tipi:</b> {req.delivery_type}
      </div>
      {req.notes && <div className="text-sm text-zinc-500">Not: {req.notes}</div>}
      <DataTable
        rows={req.lines}
        columns={[
          { header: "Ürün", render: (l) => l.name },
          { header: "Adet", align: "right", render: (l) => qty(l.qty) },
        ]}
      />
    </div>
  );
}

function PanelFiyat({ req, editable, act, busy }: Props) {
  // key: kayıttan sonra (updated_at değişince) form sunucudaki güncel değerlerle yeniden başlar
  if (editable) return <FiyatForm key={req.updated_at} req={req} act={act} busy={busy} />;
  const total = req.lines.reduce((sum, l) => sum + l.qty * (l.unit_cost ?? 0), 0);
  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        Çin ofisinden / tedarikçiden gelen birim alış fiyatları. Katalogdaki son alış fiyatı referans içindir.
      </p>
      <DataTable
        rows={req.lines}
        columns={[
          { header: "Ürün", render: (l) => l.name },
          { header: "Tedarikçi", render: (l) => l.supplier ?? "-" },
          { header: "Adet", align: "right", render: (l) => qty(l.qty) },
          { header: "Katalog Son Alış", align: "right", render: (l) => num(l.catalog_last_cost) },
          { header: `Birim Alış (${req.currency})`, align: "right", render: (l) => num(l.unit_cost) },
        ]}
      />
      <div className="max-w-xs">
        <Metric label="Toplam ürün alış maliyeti" value={money(total, req.currency)} />
      </div>
    </div>
  );
}

function PanelGumruk({ req, editable, act, busy }: Props) {
  if (editable) return <GumrukForm key={req.updated_at} req={req} act={act} busy={busy} />;
  const cur = req.currency;
  const lineCols: Column<ReqDetail["lines"][number]>[] = [
    { header: "Ürün", render: (l) => l.name },
    { header: "GTİP", render: (l) => l.hs_code || "-" },
    { header: "Adet", align: "right", render: (l) => qty(l.qty) },
    { header: `Birim Alış (${cur})`, align: "right", render: (l) => num(l.unit_cost) },
    { header: `Birim Gümrük (${cur})`, align: "right", render: (l) => num(l.unit_customs) },
    { header: `Birim Lojistik (${cur})`, align: "right", render: (l) => num(l.unit_logistics) },
  ];
  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        Teslimat tipi: <b className="text-zinc-300">{req.delivery_type}</b>. Ürün başına gümrük ve lojistik masrafı ayrı
        gösterilir; ürüne bağlı olmayan masraflar aşağıda listelenir.
      </p>
      <DataTable rows={req.lines} columns={lineCols} />
      {req.costs.length > 0 && (
        <>
          <SectionTitle>Ekstra masraflar</SectionTitle>
          <DataTable
            rows={req.costs}
            columns={[
              { header: "Masraf", render: (c) => c.label },
              { header: "Tür", render: (c) => c.kind_label },
              { header: `Tutar (${cur})`, align: "right", render: (c) => num(c.amount) },
            ]}
          />
        </>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Metric label="Toplam gümrük" value={money(req.cost_summary.customs, cur)} />
        <Metric label="Toplam lojistik" value={money(req.cost_summary.logistics, cur)} />
        <Metric label="Diğer masraflar" value={money(req.cost_summary.other, cur)} />
      </div>
      {req.delivery_hint && <Callout tone="warn">{req.delivery_hint}</Callout>}
    </div>
  );
}

function PanelTeklif({ req, editable, act, busy }: Props) {
  const t = req.teklif;
  if (!t) return null;
  if (editable) return <TeklifForm key={req.updated_at} req={req} act={act} busy={busy} />;
  const cur = req.currency;
  const q = t.quote;
  return (
    <div className="space-y-4">
      <div className="text-sm text-zinc-300">
        <b>Varsayılan kâr marjı:</b> {t.margin_pct !== null ? `%${qty(t.margin_pct)}` : "-"} · <b>KDV:</b>{" "}
        {t.tax_enabled ? `%${qty(t.tax_pct)}` : "uygulanmıyor"} · <b>Geçerlilik:</b> {t.valid_days} gün ·{" "}
        <b>Lojistik:</b> {t.logistics_mode_label}
        {t.logistics_mode === "ayri" && t.logistics_margin_pct !== null && ` (marj %${qty(t.logistics_margin_pct)})`} ·{" "}
        <b>Teslimat:</b> {req.delivery_type}
      </div>
      {t.payment_terms.trim() && (
        <div className="text-sm text-zinc-500">
          Ödeme koşulları:{" "}
          {t.payment_terms
            .split("\n")
            .filter((l) => l.trim())
            .join(" · ")}
        </div>
      )}
      {!q ? (
        <Callout tone="info">Kâr marjı henüz girilmedi.</Callout>
      ) : (
        <>
          <QuoteBreakdown
            q={q}
            cur={cur}
            taxEnabled={t.tax_enabled}
            taxPct={t.tax_pct}
            mode={t.logistics_mode}
            missingUnitCost={t.missing_unit_cost}
            hint={t.hint}
            marginPct={t.margin_pct}
            warnPct={req.margin_warn_pct}
          />
        </>
      )}
      {t.quote_sent_at && <Callout tone="success">Teklif müşteriye iletildi ({fmtDate(t.quote_sent_at)}).</Callout>}
      <QuoteDocs req={req} />
    </div>
  );
}

function PanelKarar({ req }: Props) {
  const q = req.teklif?.quote;
  return (
    <div className="space-y-4">
      {q && (
        <div className="max-w-xs">
          <Metric
            label={"Müşteriye verilen teklif" + (req.teklif?.tax_enabled ? " (KDV hariç)" : " (KDV yok)")}
            value={money(q.total, req.currency)}
          />
        </div>
      )}
      {req.karar?.decision === "onay" && <Callout tone="success">Müşteri teklifi onayladı.</Callout>}
      {req.karar?.decision === null && req.status === "aktif" && (
        <Callout tone="info">Müşterinin kararı bekleniyor.</Callout>
      )}
      <QuoteDocs req={req} />
    </div>
  );
}

/** Sipariş aşaması düzenlenebilirken form (talepler.py::_panel_siparis ile aynı adımlar): müşteri PO no + satın alma onayı. */
function SiparisForm({ req, act, busy }: { req: ReqDetail; act: Act; busy: boolean }) {
  const s = req.siparis!;
  const [poNo, setPoNo] = useState(s.customer_po_no);
  const [approved, setApproved] = useState(s.po_approved_at !== null);
  const send = (advance: boolean) =>
    act("/siparis", { customer_po_no: poNo, po_approved: approved, advance }, { ok: advance ? "Sonraki aşamaya aktarıldı." : "Kaydedildi." });
  return (
    <div className="space-y-4 text-sm text-zinc-300">
      <div className="max-w-md">
        <label className="mb-1 block text-xs text-zinc-500">Müşteri sipariş referans no (opsiyonel)</label>
        <input
          value={poNo}
          onChange={(e) => setPoNo(e.target.value)}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 outline-none focus:border-sky-500"
        />
        <p className="mt-1 text-xs text-zinc-500">
          Müşterinin kendi sipariş numarası; bizim tedarikçiye açtığımız PO numarasından farklı ve bağımsızdır.
        </p>
      </div>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} className="h-4 w-4" />
        Çin ofisine satın alma onayı verildi
      </label>
      <p className="-mt-2 text-xs text-zinc-500">Onaylanınca bizim tedarikçiye açacağımız PO numarası otomatik oluşturulur.</p>
      {s.po_number && (
        <div>
          <span className="text-zinc-500">Satın alma sipariş no (PO):</span> <b className="text-white">{s.po_number}</b>
          {s.po_approved_at && <span className="text-zinc-500"> · onay: {fmtDate(s.po_approved_at)}</span>}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button className={btn} disabled={busy} onClick={() => send(false)}>
          💾 Kaydet
        </button>
        <button className={btnPrimary} disabled={busy} onClick={() => send(true)}>
          Kaydet ve Lojistik&apos;e Aktar →
        </button>
      </div>
    </div>
  );
}

function PanelSiparis({ req, editable, act, busy }: Props) {
  const s = req.siparis;
  if (!s) return null;
  // key: kayıttan sonra (updated_at değişince) form sunucudaki güncel değerlerle yeniden başlar
  if (editable) return <SiparisForm key={req.updated_at} req={req} act={act} busy={busy} />;
  return (
    <div className="space-y-3 text-sm text-zinc-300">
      <div>
        <span className="text-zinc-500">Müşteri sipariş referans no:</span> {s.customer_po_no || "-"}
      </div>
      <div>
        <span className="text-zinc-500">Çin ofisine satın alma onayı:</span>{" "}
        {s.po_approved_at ? `verildi (${fmtDate(s.po_approved_at)})` : "henüz verilmedi"}
      </div>
      {s.po_number && (
        <div>
          <span className="text-zinc-500">Satın alma sipariş no (PO):</span> <b className="text-white">{s.po_number}</b>
        </div>
      )}
    </div>
  );
}

function PanelLojistik({ req }: Props) {
  return (
    <div className="space-y-4">
      {req.shipments.length > 0 ? (
        <>
          <SectionTitle>Bağlı kargolar (CRG)</SectionTitle>
          <DataTable
            rows={req.shipments}
            columns={[
              { header: "Kargo", render: (sh) => <b className="text-white">{sh.code}</b> },
              { header: "Durum", render: (sh) => sh.logistics_status },
              { header: "AWB", render: (sh) => sh.awb_no || "-" },
              { header: "Bu REQ'den", align: "right", render: (sh) => `${qty(sh.qty_here)} kalem` },
            ]}
          />
        </>
      ) : (
        <Callout tone="info">Bu REQ henüz bir kargoya eklenmedi.</Callout>
      )}
      <p className="text-xs text-zinc-500">
        AWB, taşıyıcı, GÇB, gümrük statüsü ve belgeler Kargo modülünde tutulur; birden fazla REQ tek kargoda birleşebilir. Bu, REQ&apos;in
        kendi aşama akışını etkilemez.
      </p>
    </div>
  );
}

function PanelTeslim({ req, editable, act, busy }: Props) {
  const t = req.teslim;
  if (!t) return null;
  return (
    <div className="space-y-4">
      {req.status === "tamamlandi" && <Callout tone="success">REQ tamamlandı.</Callout>}
      {editable ? (
        // key: makbuz oluşturulunca (makbuz sayısı değişince) girilen adetler sıfırlansın, güncel Kalan gelsin
        <TeslimForm key={t.deliveries.length} req={req} act={act} busy={busy} />
      ) : (
        <DataTable
          rows={t.rows}
          columns={[
            { header: "Ürün", render: (r) => r.name },
            { header: "Sipariş Edilen", align: "right", render: (r) => qty(r.ordered) },
            { header: "Şimdiye Kadar Teslim", align: "right", render: (r) => qty(r.delivered) },
            { header: "Kalan", align: "right", render: (r) => qty(r.remaining) },
          ]}
        />
      )}
      {t.deliveries.length > 0 && (
        <div>
          <SectionTitle>Teslimat makbuzları</SectionTitle>
          <ul className="space-y-2">
            {t.deliveries.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 px-4 py-2.5 text-sm">
                <span className="font-medium text-white">{d.number}</span>
                <span className="text-zinc-400">{fmtDate(d.issued_at)}</span>
                <span className="text-zinc-300">{qty(d.total_qty)} kalem</span>
                <a
                  href={`${API_BASE}/api/deliveries/${d.id}/pdf`}
                  className="ml-auto rounded-lg border border-zinc-700 px-3 py-1 hover:bg-zinc-800"
                >
                  📄 PDF indir
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
      {req.status === "aktif" &&
        (t.all_delivered ? (
          <Callout tone="success">Tüm ürünler teslim edildi; REQ tamamlanabilir.</Callout>
        ) : (
          <Callout tone="info">Tüm ürünler tam teslim edilince REQ tamamlanabilir.</Callout>
        ))}
    </div>
  );
}

const PANELS: Record<string, (p: Props) => React.ReactNode> = {
  talep: PanelTalep,
  fiyat: PanelFiyat,
  gumruk: PanelGumruk,
  teklif: PanelTeklif,
  karar: PanelKarar,
  siparis: PanelSiparis,
  lojistik: PanelLojistik,
  teslim: PanelTeslim,
};

export default function StagePanel({ stage, ...props }: Props & { stage: string }) {
  const Panel = PANELS[stage];
  return Panel ? <Panel {...props} /> : null;
}
