from datetime import datetime

import streamlit as st

from jarvis import pipeline as pl, services as sv
from jarvis.db import session_scope
from jarvis.ui.common import TR_TZ, notify_error, notify_success


def render():
    actor = st.session_state["actor"]
    st.title("Ayarlar")
    if actor.role != pl.ADMIN:
        st.error("Bu sayfa yalnızca yöneticiler içindir.")
        return
    with session_scope() as s:
        company = sv.get_company(s, actor)
        st.subheader("Şirket bilgileri")
        st.caption("Müşteriye giden teklif PDF'inin başlığında, altında ve banka bilgilerinde görünür.")
        with st.form("company_form"):
            legal_name = st.text_input("Resmi unvan", value=company.legal_name)
            address = st.text_area("Adres", value=company.address, height=80)
            tax_info = st.text_input("Vergi dairesi / vergi no", value=company.tax_info, placeholder="Örn: Çankaya V.D. 1234567890")
            c1, c2, c3 = st.columns(3)
            phone, email, website = c1.text_input("Telefon", value=company.phone), c2.text_input("E-posta", value=company.email), c3.text_input("Web sitesi", value=company.website)
            bank_info = st.text_area("Banka bilgileri", value=company.bank_info, height=80, placeholder="Banka, şube, IBAN...\nHer satır PDF'de ayrı satır olarak görünür.",
                                     help="Her satır PDF'de ayrı bir satır olarak, teklifin en altında 'Ödeme Detayları' başlığı altında görünür.")

            st.markdown("**Teklif numaralandırma**")
            n1, n2 = st.columns(2)
            quote_prefix = n1.text_input("Teklif öneki", value=company.quote_prefix, help="Örn: OZ. Numara: ÖNEK + YYAAGG + sıra no (örn. OZ260921204).")
            quote_seq = n2.number_input("Son kullanılan teklif sıra no", min_value=0, step=1, value=int(company.quote_seq),
                                        help="Odoo'daki son teklif numarasının sıra kısmını girin; yeni teklifler bundan sonraki numarayla devam eder. Sonradan yalnızca artırılabilir.")

            st.markdown("**Satın alma sipariş (PO) numaralandırma**")
            st.caption("Çin ofisine/tedarikçiye satın alma onayı verildiğinde otomatik oluşturulur.")
            p1, p2 = st.columns(2)
            po_prefix = p1.text_input("PO öneki", value=company.po_prefix, help="Örn: P. Numara: ÖNEK + YYAAGG + sıra no (örn. P260921004).")
            po_seq = p2.number_input("Son kullanılan PO sıra no", min_value=0, step=1, value=int(company.po_seq),
                                     help="Odoo'daki son satın alma sipariş numarasının sıra kısmını girin. Sonradan yalnızca artırılabilir.")

            st.markdown("**Kargo (CRG) numaralandırma**")
            g1, g2 = st.columns(2)
            shipment_prefix = g1.text_input("Kargo öneki", value=company.shipment_prefix, help="Örn: CRG. Numara: ÖNEK_sıra no (örn. CRG_07).")
            shipment_seq = g2.number_input("Son kullanılan kargo sıra no", min_value=0, step=1, value=int(company.shipment_seq))

            st.markdown("**Teslimat makbuzu numaralandırma**")
            d1, d2 = st.columns(2)
            delivery_prefix = d1.text_input("Teslimat öneki", value=company.delivery_prefix, help="Örn: OUT. Numara: ÖNEK/sıra no (örn. OUT/00135).")
            delivery_seq = d2.number_input("Son kullanılan teslimat sıra no", min_value=0, step=1, value=int(company.delivery_seq))

            if st.form_submit_button("Kaydet", type="primary"):
                try:
                    sv.update_company(s, actor, legal_name=legal_name, address=address, tax_info=tax_info, phone=phone, email=email,
                                      website=website, bank_info=bank_info, quote_prefix=quote_prefix, quote_seq=int(quote_seq),
                                      po_prefix=po_prefix, po_seq=int(po_seq), shipment_prefix=shipment_prefix, shipment_seq=int(shipment_seq),
                                      delivery_prefix=delivery_prefix, delivery_seq=int(delivery_seq))
                except sv.ServiceError as e:
                    notify_error(str(e))
                else:
                    notify_success("Ayarlar kaydedildi.")
                    st.rerun()

        now = datetime.now(TR_TZ)
        st.caption(f"Bir sonraki teklif numarası: **{company.quote_prefix}{now:%y%m%d}{company.quote_seq + 1:03d}** · "
                   f"bir sonraki PO numarası: **{company.po_prefix}{now:%y%m%d}{company.po_seq + 1:03d}** · "
                   f"bir sonraki kargo kodu: **{company.shipment_prefix}_{company.shipment_seq + 1:02d}** · "
                   f"bir sonraki teslimat no: **{company.delivery_prefix}/{company.delivery_seq + 1:05d}**")
        st.divider()
        st.caption("🔑 **Gemini** (`GEMINI_API_KEY`) ve **DHL** (`DHL_API_KEY`) anahtarları güvenlik için bu sayfadan değil, "
                  ".env dosyasından (yerelde) veya Streamlit Cloud'daki Secrets bölümünden (buluttayken) okunur.")

        st.divider()
        st.subheader("Kullanıcı şifreleri")
        st.caption("Giriş sistemi yalnızca `JARVIS_DEV_MODE` kapatıldığında (canlıda) devrededir; yerelde geliştirme "
                  "modunda hâlâ kenar çubuğundaki hızlı kullanıcı değiştirici kullanılır. Şifresi belirlenmemiş "
                  "kullanıcı giriş yapamaz.")
        users = sv.list_users(s)
        for user in users:
            with st.expander(f"{user.name} · {user.username} · {'🔓 şifre var' if user.password_hash else '🔒 şifre yok'}"):
                with st.form(f"pw_form_{user.id}", clear_on_submit=True):
                    new_pw = st.text_input("Yeni şifre (en az 8 karakter)", type="password", key=f"pw_{user.id}")
                    if st.form_submit_button("Şifreyi belirle/değiştir"):
                        try:
                            sv.set_password(s, actor, user.id, new_pw)
                        except sv.ServiceError as e:
                            notify_error(str(e))
                        else:
                            notify_success(f"{user.name} için şifre güncellendi.")
                            st.rerun()
