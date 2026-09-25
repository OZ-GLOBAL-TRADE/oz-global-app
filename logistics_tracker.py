import re

def detect_carrier(awb_no: str) -> str:
    awb = str(awb_no).replace(" ", "").replace("-", "").strip()
    if not awb or awb == "-": return "Bilinmiyor"
    if (awb.startswith("235") and len(awb) == 11) or "TK" in str(awb_no).upper(): return "Turkish Cargo"
    elif len(awb) == 10 and awb.isdigit(): return "DHL Express"
    elif len(awb) in [12, 15] and awb.isdigit(): return "FedEx"
    elif awb.upper().startswith("1Z"): return "UPS"
    return "Global Kargo / Hat"

def enrich_cargo_data(raw_crg_rows: list, df_req_records: list) -> list:
    req_map = {r["REQ_No"]: r for r in df_req_records if "REQ_No" in r}
    crg_list = []

    for row in raw_crg_rows:
        if not row or len(row) < 2: continue
        first_cell = str(row[0]).strip().upper()
        if first_cell in ["NO", "CRG_NO", "CRG KODU", "SIRA NO", ""]: continue

        has_no = first_cell.isdigit() or (len(row) > 1 and str(row[1]).strip().upper().startswith("CRG"))
        offset = 1 if has_no else 0
        crg_no = str(row[0 + offset]).strip()
        if not crg_no.upper().startswith("CRG"): continue

        req_str = str(row[1 + offset]).strip() if len(row) > 1 + offset else ""
        awb_no = str(row[2 + offset]).strip() if len(row) > 2 + offset else "-"
        carrier = str(row[3 + offset]).strip() if len(row) > 3 + offset and str(row[3 + offset]).strip() else detect_carrier(awb_no)
        cikis_tarihi = str(row[4 + offset]).strip() if len(row) > 4 + offset else "-"
        durum = str(row[5 + offset]).strip() if len(row) > 5 + offset else "Yolda"
        packing_list = str(row[6 + offset]).strip() if len(row) > 6 + offset else ""
        fatura = str(row[7 + offset]).strip() if len(row) > 7 + offset else ""
        notlar = str(row[8 + offset]).strip() if len(row) > 8 + offset else ""
        
        teslimat_tipi = str(row[9 + offset]).strip() if len(row) > 9 + offset else "Belirtilmedi"
        teslimat_adresi = str(row[10 + offset]).strip() if len(row) > 10 + offset else "Merkez Ofis"
        gcb_no = str(row[11 + offset]).strip() if len(row) > 11 + offset else "-"
        gumruk_statusu = str(row[12 + offset]).strip() if len(row) > 12 + offset else "Bekliyor"

        req_keys = [k.strip() for k in req_str.replace(";", ",").split(",") if k.strip()]
        total_cost = sum(float(req_map[rc].get("Toplam_Maliyet", 0.0)) for rc in req_keys if rc in req_map)
        
        req_details = [{
            "req_no": rc,
            "musteri": req_map[rc].get("Musteri", "Bilinmiyor") if rc in req_map else "Bilinmiyor",
            "urun": req_map[rc].get("Urun", "-") if rc in req_map else "-",
            "maliyet": float(req_map[rc].get("Toplam_Maliyet", 0.0)) if rc in req_map else 0.0
        } for rc in req_keys]

        crg_list.append({
            "CRG_No": crg_no,
            "Ilgili_REQler": req_keys,
            "REQ_Detaylari": req_details,
            "AWB_No": awb_no,
            "Tasiyici": carrier,
            "Cikis_Tarihi": cikis_tarihi,
            "Guncel_Durum": durum,
            "Packing_List_URL": packing_list,
            "Fatura_URL": fatura,
            "Lojistik_Notu": notlar,
            "Teslimat_Tipi": teslimat_tipi,
            "Teslimat_Adresi": teslimat_adresi,
            "GCB_No": gcb_no,
            "Gumruk_Statusu": gumruk_statusu,
            "Toplam_Maliyet_USD": total_cost
        })

    return crg_list
