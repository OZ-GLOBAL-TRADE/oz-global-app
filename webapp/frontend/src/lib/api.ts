// Backend'e (FastAPI) tek giriş noktası. credentials: "include" olmadan tarayıcı oturum çerezini
// göndermez/kabul etmez — cross-origin (localhost:3000 -> localhost:8600) istekte bu zorunlu.
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8600";

export class ApiError extends Error {
  status: number;
  /** İş kuralı hatalarında (400) tek tek eksikler, ör. "Birim gümrük girilmemiş: ..." */
  errors: string[];
  constructor(status: number, message: string, errors: string[] = []) {
    super(message);
    this.status = status;
    this.errors = errors.length ? errors : [message];
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Bilinmeyen hata", Array.isArray(body.errors) ? body.errors : []);
  }
  return res.json();
}

/** Dosya yükleme: ham gövde (multipart değil) — ad sorgu parametresinde, tür Content-Type'ta. */
export async function uploadFile<T>(path: string, file: File): Promise<T> {
  const res = await fetch(`${API_BASE}${path}?filename=${encodeURIComponent(file.name)}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Bilinmeyen hata", Array.isArray(body.errors) ? body.errors : []);
  }
  return res.json();
}

/** POST ile dosya indirir (ör. Excel dışa aktarma): yanıtı blob olarak alıp tarayıcıya indirtir. */
export async function downloadPost(path: string, body: unknown, filename: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, err.detail || "Bilinmeyen hata", Array.isArray(err.errors) ? err.errors : []);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** REQ ayrıntı sayfasının adresi. Kod yol yerine sorgu parametresindedir (statik dışa aktarma için; bkz. app/talepler/detay). */
export const reqHref = (code: string) => `/talepler/detay?code=${encodeURIComponent(code)}`;

export type Me = { id: number; username: string; name: string; role: string; role_label: string };

// ---- Panel (backend/main.py::panel; hesaplar jarvis/analytics.py'de) ----

export type ProductRow = { name: string; qty: number; sale: number; cost: number; profit: number; req_count: number; margin_pct: number | null };

export type Financials =
  | { priced: false }
  | {
      priced: true;
      currency: string;
      missing: number;
      rates: { EUR?: number; TRY?: number } | null;
      total_offer: number;
      total_profit: number;
      margin_on_cost_pct: number | null;
      win_rate_pct: number | null;
      decided: number;
      wins: number;
      by_manager: { name: string; offer: number; profit: number }[];
      by_customer: { name: string; offer: number; profit: number }[];
      monthly: { month: string; opened: number; offer: number | null }[];
      products: { top_profit: ProductRow[]; lowest_margin: ProductRow[]; table: ProductRow[] };
    };

export type PanelData =
  | { empty: true; scope_all: boolean }
  | {
      empty: false;
      scope_all: boolean;
      cards: { aktif_talep: number; fiyat_bekleyen: number; gumrukte: number; teklif_karar: number; siparis_lojistik: number };
      done: number;
      shelved: number;
      lead_time: string | null;
      per_stage: { key: string; label: string; count: number }[];
      durations: {
        in_hours: boolean;
        rows: { label: string; days: number; hours: number; text: string; count: number }[];
        slowest: { label: string; text: string } | null;
      };
      financials: Financials | null;
      recent: { code: string; customer: string; owner: string; stage_label: string; teklif: number | null; currency: string; updated_at: string }[];
    };
export type ReqRow = {
  code: string;
  customer: string;
  owner: string;
  status: "aktif" | "tamamlandi" | "rafa";
  stage: string;
  stage_label: string;
  waiting: string | null;
  line_count: number;
  updated_at: string;
  teklif: number | null;
  currency: string;
};

/** GET /api/new-req/options — Yeni REQ diyaloğunun seçenekleri (müşteri başına bir sonraki otomatik REQ kodu dahil). */
export type NewReqOptions = {
  customers: { id: number; name: string; short_code: string; next_code: string }[];
  products: { id: number; name: string; hs_code: string }[];
  currencies: string[];
  delivery_types: string[];
};

// ---- Kişiler / Ürünler (backend/catalog.py) ----

export type Partner = {
  /** Silme uyarısı için bağlı kayıt sayıları (silinmemiş REQ'ler) */
  req_count: number;
  line_count: number;
  product_count: number;
  id: number;
  name: string;
  short_code: string | null;
  req_seq: number;
  kind: string;
  tax_no: string;
  address: string;
  email: string;
  phone: string;
  category: string;
  keywords: string;
  country: string;
  notes: string;
};

export type PartnersPayload = {
  partners: Partner[];
  can_edit: boolean;
  customer_kinds: string[];
  supplier_categories: string[];
  added?: { name: string; short_code: string | null };
  removed?: { name: string };
  changed?: number;
};

export type Product = {
  /** Ürünün kaç (silinmemiş) REQ satırında kullanıldığı */
  line_count: number;
  id: number;
  name: string;
  category: string;
  hs_code: string;
  last_cost: number | null;
  spec: string;
  notes: string;
  default_supplier_id: number | null;
};

/** Çöp kutusu (backend/trash.py) */
export type TrashItem = {
  ident: string;
  title: string;
  subtitle: string;
  deleted_at: string | null;
  deleted_by: string | null;
  blocked: string | null;
};
export type TrashPayload = { items: TrashItem[]; can_purge: boolean };

export type ProductsPayload = {
  products: Product[];
  suppliers: { id: number; name: string }[];
  categories: string[];
  can_add: boolean;
  editable_fields: string[];
  added?: { name: string };
  removed?: { name: string };
  changed?: number;
};

export type ReqList = {
  reqs: ReqRow[];
  can_view_amount: boolean;
  can_create: boolean;
  stages: { key: string; label: string }[];
};

// ---- REQ detayı (backend/req_detail.py::build ile birebir aynı şekil) ----

export type StageState = "done" | "now" | "todo";
export type StepperCell = { key: string; label: string; state: StageState };

export type DetailLine = {
  id: number;
  name: string;
  qty: number;
  hs_code: string;
  catalog_last_cost: number | null;
  unit_cost: number | null;
  unit_customs: number | null;
  unit_logistics: number | null;
  supplier: string | null;
  supplier_id: number | null;
  product_id: number | null;
};

/** Yazma eyleminden sonra REQ artık bu rolün görüş alanı dışındaysa (ör. gümrükçü kendi aşamasını ilerletti). */
export type Hidden = { hidden: true };

export type LinePricing = {
  id: number;
  name: string;
  qty: number;
  cost: number;
  margin_pct: number | null;
  sale_price_override: number | null;
};

/** POST /preview: kaydedilmemiş form değerleriyle canlı hesap (hesap sunucuda, pipeline.calculate_quote ile). */
export type Preview = {
  cost_summary: { products: number; customs: number; logistics: number; other: number };
  hint: string | null;
  quote: QuoteCalc | null;
  line_costs: number[] | null;
  missing_unit_cost?: boolean;
};

/** Metin kutusundaki sayıyı çözer: boş → null, geçersiz → NaN. Virgül ve nokta ondalık ayırıcı kabul edilir (tr-TR). */
export function parseNum(s: string): number | null {
  const t = s.trim().replace(",", ".");
  if (t === "") return null;
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : Number.NaN;
}

export function toInput(v: number | null | undefined): string {
  return v === null || v === undefined ? "" : String(v).replace(".", ",");
}

export type QuoteDocRow = {
  id: number;
  number: string;
  issued_at: string;
  currency: string;
  total: number;
  grand_total: number;
  is_latest: boolean;
};

export type QuoteCalc = {
  cost_products: number;
  cost_customs: number;
  cost_logistics: number;
  cost_other: number;
  cost_total: number;
  profit: number;
  total: number;
  tax: number;
  grand_total: number;
  rows: {
    name: string;
    qty: number;
    unit_cost: number;
    unit_price: number;
    line_total: number;
    margin_label: string;
    kind: "urun" | "lojistik";
  }[];
};

export type TeklifSection = {
  margin_pct: number | null;
  tax_enabled: boolean;
  tax_pct: number;
  valid_days: number;
  payment_terms: string;
  logistics_mode: string;
  logistics_mode_label: string;
  logistics_margin_pct: number | null;
  quote_sent_at: string | null;
  missing_unit_cost: boolean;
  quote: QuoteCalc | null;
  hint: string | null;
  quotes: QuoteDocRow[];
  line_pricing: LinePricing[];
};

export type NoteTask = {
  id: number;
  kind: "note" | "task";
  created_at: string;
  user: string | null;
  assignee: string | null;
  message: string;
  state: "open" | "done" | "cancelled" | null;
  can_act: boolean;
  can_delete: boolean;
  done_at: string | null;
  cancelled_at: string | null;
};

export type ReqDetail = {
  code: string;
  customer: string;
  owner: string;
  status: "aktif" | "tamamlandi" | "rafa";
  status_label: string;
  stage: string;
  stage_label: string;
  waiting: string | null;
  currency: string;
  delivery_type: string;
  notes: string;
  shelved_reason: string | null;
  created_at: string;
  updated_at: string;
  stepper: StepperCell[];
  visible_stages: string[];
  current_stage: string;
  can_edit_current: boolean;
  can_advance: boolean;
  can_manage: boolean;
  can_move_back: boolean;
  can_shelve: boolean;
  can_reopen: boolean;
  can_fix: boolean;
  can_delete: boolean;
  customer_id: number;
  customer_change_blocked: boolean;
  customer_options: { id: number; name: string }[];
  currencies: string[];
  next_stage_label: string | null;
  move_back_reasons: string[];
  shelve_reasons: string[];
  assignable_users: { id: number; name: string }[];
  supplier_options: { id: number; name: string }[];
  product_options: { id: number; name: string; hs_code: string }[];
  delivery_types: string[];
  cost_kinds: { key: string; label: string }[];
  logistics_modes: { key: string; label: string }[];
  margin_warn_pct: number;
  lines: DetailLine[];
  costs: { label: string; kind: string; kind_label: string; amount: number }[];
  cost_summary: { products: number; customs: number; logistics: number; other: number };
  delivery_hint: string | null;
  shipments: { code: string; logistics_status: string; awb_no: string; qty_here: number }[];
  teklif: TeklifSection | null;
  karar: { decision: "onay" | "ret" | null } | null;
  siparis: { customer_po_no: string; po_number: string | null; po_approved_at: string | null } | null;
  teslim: {
    rows: { line_id: number; name: string; ordered: number; delivered: number; remaining: number }[];
    deliveries: { id: number; number: string; issued_at: string; total_qty: number; delivered_by: string; delivered_to: string }[];
    all_delivered: boolean;
    customer: string;
  } | null;
  open_tasks: number;
  notes_tasks: NoteTask[];
  history: { kind: string; created_at: string; user: string | null; message: string }[];
  attachments: { id: number; filename: string; size: number; content_type: string; uploaded_at: string }[];
};

const SYMBOLS: Record<string, string> = { USD: "$", EUR: "€", TRY: "₺" };

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Adet gibi tam ya da kesirli olabilen sayılar (Streamlit'teki %g gibi: gereksiz sıfır yok). */
export function qty(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("tr-TR", { maximumFractionDigits: 3 });
}

export function money(v: number | null, cur: string): string {
  if (v === null) return "-";
  const s = SYMBOLS[cur] || cur;
  return `${s} ${v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
