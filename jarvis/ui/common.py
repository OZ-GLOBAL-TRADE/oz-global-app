from datetime import datetime, timedelta, timezone

import streamlit as st

from jarvis import ai, config, jarvis_chat, pipeline as pl, seed, services as sv, sounds, tts
from jarvis.db import backend_name, session_scope
from jarvis.models import User

TR_TZ = timezone(timedelta(hours=3))  # Türkiye kalıcı UTC+3
SYMBOLS = {"USD": "$", "EUR": "€", "TRY": "₺"}
STAGE_COLORS = {"talep": "#64748B", "fiyat": "#0EA5E9", "gumruk": "#8B5CF6", "teklif": "#F59E0B",
                "karar": "#EC4899", "siparis": "#10B981", "lojistik": "#14B8A6", "teslim": "#22C55E"}
STATUS_COLORS = {pl.DONE: "#22C55E", pl.SHELVED: "#EF4444"}

CSS = """
<style>
.kpi { border: 1px solid rgba(128,128,128,.28); border-top: 3px solid var(--c); border-radius: 12px; padding: 14px 16px; background: rgba(128,128,128,.07); }
.kpi .l { font-size: 11px; letter-spacing: .07em; text-transform: uppercase; opacity: .72; font-weight: 600; }
.kpi .v { font-size: 32px; font-weight: 700; line-height: 1.15; margin-top: 2px; }
.kpi .h { font-size: 12px; opacity: .62; margin-top: 2px; }
.pill { display: inline-block; padding: 2px 11px; border-radius: 999px; font-size: 12px; font-weight: 600; color: #fff; vertical-align: middle; }
.stepper { display: flex; gap: 6px; margin: 4px 0 14px; }
.step { flex: 1; text-align: center; font-size: 12px; line-height: 1.3; padding: 7px 3px; border-bottom: 3px solid rgba(128,128,128,.35); opacity: .55; }
.step.done { color: #10B981; border-color: #10B981; opacity: 1; }
.step.now { color: #38BDF8; border-color: #38BDF8; font-weight: 700; opacity: 1; }
.colhead { display: flex; justify-content: space-between; font-size: 12px; font-weight: 700; padding: 6px 2px; margin-bottom: 6px; border-bottom: 3px solid var(--c); }
.colhead span { opacity: .7; }
.st-key-board button { padding: 0 !important; min-height: 1.6rem; }
.st-key-board button p { white-space: nowrap; font-size: 13px; font-weight: 600; }
.st-key-board [data-testid="stCaptionContainer"] { font-size: 11px; line-height: 1.3; }
/* Sağdan kayan panel: içinde key'i "drawer_" ile başlayan bir container olan diyalog (Notlar & Görevler, Günlük
   Brifing) ortalanmış modal yerine sağa sabit tam boy panel olur; "Yeni REQ" gibi diğer diyaloglar etkilenmez. */
div[data-testid="stDialog"]:has([class*="st-key-drawer_"]) > div {
  position: fixed; top: 0; right: 0; bottom: 0; margin: 0; width: min(560px, 100vw); max-width: none;
  height: 100vh; max-height: none; border-radius: 0; overflow-y: auto; animation: jarvisSlideIn .25s ease-out;
  box-shadow: -8px 0 24px rgba(0,0,0,.35);
}
div[data-testid="stDialog"]:has([class*="st-key-drawer_"]) section[role="dialog"] { width: 100%; max-width: none; }
.st-key-sfx { position: absolute; width: 0; height: 0; overflow: hidden; }
@keyframes jarvisSlideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)
    # Ses efektleri için her çalıştırmada AYNI yerde duran gizli yuva. Ses çağrıldığı yerde st.audio ile çizilirse
    # bazı çalıştırmalarda var bazılarında yok olur, altındaki her öğenin konumu kayar; Streamlit de açık expander'ları
    # ve düzenlenmekte olan tabloları "yeni öğe" sanıp sıfırlıyordu.
    with st.container(key="sfx"):
        st.session_state["_sfx_slot"] = st.empty()


def _play(wav_bytes: bytes):
    (st.session_state.get("_sfx_slot") or st).audio(wav_bytes, format="audio/wav", autoplay=True)


def play_success_sound():
    _play(sounds.SUCCESS)


def play_error_sound():
    _play(sounds.ERROR)


def notify_success(message: str, icon: str = "✅"):
    """st.toast + kısa bir onay sesi. Kaydetme/oluşturma gibi başarılı işlemlerde st.toast yerine kullanılır."""
    play_success_sound()
    st.toast(message, icon=icon)


def notify_error(message: str):
    """st.error + kısa bir uyarı sesi. Birden fazla hata mesajı art arda gösterilecekse (bir listeyle dönen
    ServiceError'lar gibi) sesi yalnızca BİR kez çalmak için doğrudan play_error_sound() + st.error() kullanın,
    bu fonksiyonu döngü içinde çağırmayın."""
    play_error_sound()
    st.error(message)


def money(v, cur="USD") -> str:
    if v is None: return "-"
    text = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{SYMBOLS.get(cur, cur)} {text}"


def to_local(dt):
    if dt is None: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TR_TZ)


def fmt_dt(dt) -> str:
    return to_local(dt).strftime("%d.%m.%Y %H:%M") if dt else "-"


def fmt_date(dt) -> str:
    return to_local(dt).strftime("%d.%m.%Y") if dt else "-"


def pill(text: str, color: str) -> str:
    return f"<span class='pill' style='background:{color}'>{text}</span>"


def req_pill(req) -> str:
    if req.status == pl.ACTIVE: return pill(pl.STAGE_BY_KEY[req.stage].label, STAGE_COLORS[req.stage])
    return pill(pl.STATUS_LABELS[req.status], STATUS_COLORS[req.status])


def kpi(label: str, value, hint: str, color: str) -> str:
    return f"<div class='kpi' style='--c:{color}'><div class='l'>{label}</div><div class='v'>{value}</div><div class='h'>{hint}</div></div>"


@st.cache_resource(show_spinner=False)
def boot() -> bool:
    with session_scope() as s: seed.bootstrap(s)
    return True


def get_actor() -> sv.Actor:
    boot()
    if not config.DEV_MODE:
        return _login_gate()
    with session_scope() as s: users = {u.username: sv.to_actor(u) for u in sv.list_users(s)}
    names = list(users)
    with st.sidebar:
        st.caption("🧪 Geliştirme modu: canlıya alınırken kapatılacak")
        chosen = st.selectbox("Kullanıcı olarak görüntüle", names, index=names.index("yusuf.oz") if "yusuf.oz" in names else 0,
                              format_func=lambda u: f"{users[u].name} · {pl.ROLE_LABELS[users[u].role]}", key="dev_user")
        st.caption("🗄️ Veritabanı: " + ("PostgreSQL (kalıcı)" if backend_name() == "postgresql" else "SQLite (yerel/geçici: buluttayken yeniden başlayınca sıfırlanır)"))
    return users[chosen]


def _login_gate() -> sv.Actor:
    """JARVIS_DEV_MODE kapalıyken gerçek giriş: kullanıcı adı + şifre. Oturum yalnızca st.session_state'te
    tutulur (sekme/tarayıcı kapanınca ya da sayfa sert yenilenince düşer — kalıcı çerez henüz yok, istenirse
    sonraki bir turda eklenir)."""
    if user_id := st.session_state.get("auth_user_id"):
        with session_scope() as s:
            user = s.get(User, user_id)
            if user and user.active:
                return sv.to_actor(user)
        st.session_state.pop("auth_user_id", None)  # kullanıcı silinmiş/pasif olmuş

    st.title("✨ Jarvis · OZ Global Trade")
    with st.form("login_form"):
        username = st.text_input("Kullanıcı adı")
        password = st.text_input("Şifre", type="password")
        if st.form_submit_button("Giriş yap", type="primary"):
            with session_scope() as s:
                try:
                    actor = sv.authenticate(s, username, password)
                except sv.ServiceError as e:
                    notify_error(str(e))
                    st.stop()
            st.session_state["auth_user_id"] = actor.id
            st.session_state["jarvis_just_logged_in"] = True
            st.rerun()
    st.stop()


def maybe_play_welcome():
    """Gerçek girişten (JARVIS_DEV_MODE=0) hemen sonra, uygulamanın ilk render'ında bir kez karşılama
    sesi çalar. `_login_gate`, `st.rerun()`'dan önce bayrağı koyar; ses ancak bir sonraki render'da,
    burada tüketilince çalınabilir (rerun sırasında konan bir st.audio hiç DOM'a çizilmeden silinir)."""
    if st.session_state.pop("jarvis_just_logged_in", False):
        _play(sounds.WELCOME)


def logout_button():
    """DEV_MODE kapalıyken kenar çubuğunda küçük bir çıkış düğmesi."""
    if config.DEV_MODE: return
    with st.sidebar:
        if st.button("🚪 Çıkış yap", key="logout_btn", width="stretch"):
            st.session_state.pop("auth_user_id", None)
            st.rerun()


def sidebar_open_tasks(actor: sv.Actor):
    """Kenar çubuğunda, size atanan tamamlanmamış görevlerin her sayfada görünen bir uyarısı ('uygulama içi
    uyarı' — yalnızca panelde değil, her nereye gidilirse gidilsin görünür kalır)."""
    with session_scope() as s:
        tasks = sv.list_my_open_tasks(s, actor)
    if not tasks: return
    with st.sidebar:
        with st.expander(f"🔔 Size atanan {len(tasks)} açık görev", expanded=True):
            for t in tasks[:15]:
                # REQ görünürlüğü sahiplik bazlı olduğu için (bkz. pipeline.can_view_req), atama sırasında zaten
                # görebildiği REQ'ler için görev verilir — yine de aşama ilerleyip görüş alanı daralmışsa (örn.
                # gümrükçüye atanan görev REQ gümrük aşamasından çıkınca) 'Aç' göstermek yerine sessizce metin gösterilir.
                can_open = t.req and pl.can_view_req(actor.id, actor.role, t.req)
                c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
                c1.caption(f"**{t.req.code if t.req else '-'}** · {t.message}")
                if can_open and c2.button("Aç", key=f"sbtask_{t.id}", width="stretch"):
                    st.session_state["open_req"] = t.req.code
                    st.switch_page(st.session_state["pages"]["talepler"])


def sidebar_tools(actor: sv.Actor):
    """Yalnızca admin: demo veriyi yükle / sil (gerçek kayıtlara dokunmaz)."""
    if actor.role != pl.ADMIN: return
    with st.sidebar.expander("🧪 Demo veri"):
        st.caption("Her yönetici için 2'şer örnek REQ. Sistemi denemek içindir; tek tuşla silinir.")
        if st.button("Örnek REQ'leri yükle", width="stretch"):
            with session_scope() as s: seed.load_demo(s)
            notify_success("Demo veri yüklendi.")
            st.rerun()
        if st.button("Demo verisini sil", width="stretch"):
            with session_scope() as s: result = seed.purge_demo(s)
            st.session_state.pop("open_req", None)
            notify_success(f"Silindi: {result['req']} REQ, {result['urun']} ürün, {result['kisi']} kişi.", icon="🗑️")
            st.rerun()


def _speak(text: str):
    """Son cevabı Microsoft Edge'in nöral sesiyle okur (emoji temizlenmiş, tarayıcının robotik
    sesinden daha doğal). Sentez başarısız olursa sessizce hiçbir şey çalınmaz — hataya düşmez."""
    audio = tts.synthesize(text)
    if audio:
        st.audio(audio, format="audio/mp3", autoplay=True)


def _ask_and_append(actor, history, prompt: str) -> str:
    with st.spinner("Jarvis düşünüyor..."):
        with session_scope() as s:
            try:
                reply, pending = jarvis_chat.ask(s, actor, history[:-1], prompt)
            except Exception as e:
                reply, pending = f"⚠️ Beklenmeyen bir hata oldu: {e}", None
    history.append({"role": "assistant", "content": reply})
    st.session_state["jarvis_chat_open"] = True
    if pending: st.session_state["jarvis_pending_action"] = pending
    return reply


def sidebar_chat(actor: sv.Actor):
    """Her sayfada erişilebilir Jarvis AI sohbeti. Uygulama ilk açıldığında sesli bir karşılamayla başlar;
    metinle ya da mikrofonla sorulabilir. Faz 2: REQ ilerletme / kargo güncelleme gibi komutlar önce
    öneri olarak gelir, yalnızca kullanıcı arayüzde açıkça onaylarsa gerçekleşir."""
    with st.sidebar:
        st.divider()
        history = st.session_state.setdefault("jarvis_chat_history", [])

        if not history and not st.session_state.get("jarvis_greeted"):
            st.session_state["jarvis_greeted"] = True
            with session_scope() as s:
                try:
                    greeting = jarvis_chat.greeting(s, actor)
                except Exception:
                    greeting = f"Merhaba {actor.name}, hoş geldiniz."
            history.append({"role": "assistant", "content": greeting})
            st.session_state["jarvis_speak_next"] = greeting

        if history:
            with st.expander(f"🤖 Jarvis AI · sohbet", expanded=st.session_state.get("jarvis_chat_open", True)):
                for h in history:
                    st.chat_message(h["role"]).write(h["content"])
        else:
            st.caption("🤖 **Jarvis AI**: her aşamada, sahip olduğunuz yetki dahilinde sorularınızı yanıtlar.")

        pending = st.session_state.get("jarvis_pending_action")
        if pending:
            st.warning(f"⏳ Onay bekliyor: {pending['aciklama']}")
            c1, c2 = st.columns(2)
            if c1.button("✅ Onayla", key="jarvis_confirm", width="stretch"):
                with session_scope() as s:
                    result = jarvis_chat.execute_action(s, actor, pending["eylem"], pending["parametreler"])
                history.append({"role": "assistant", "content": result})
                st.session_state.pop("jarvis_pending_action", None)
                st.session_state["jarvis_chat_open"] = True
                st.rerun()
            if c2.button("✖️ Vazgeç", key="jarvis_cancel", width="stretch"):
                history.append({"role": "assistant", "content": f"İptal edildi: {pending['aciklama']}"})
                st.session_state.pop("jarvis_pending_action", None)
                st.rerun()

        audio = st.audio_input("🎤 Sesli sor", key="jarvis_voice_input")
        if audio is not None and audio.file_id != st.session_state.get("jarvis_last_audio_id"):
            st.session_state["jarvis_last_audio_id"] = audio.file_id
            with st.spinner("Ses yazıya çevriliyor..."):
                text, err = ai.transcribe_audio(audio.getvalue(), audio.type or "audio/wav")
            if err:
                notify_error(err)
            else:
                history.append({"role": "user", "content": text})
                reply = _ask_and_append(actor, history, text)
                st.session_state["jarvis_speak_next"] = reply
                st.rerun()

        prompt = st.chat_input("Jarvis'e sor...", key="jarvis_chat_input")
        if prompt:
            history.append({"role": "user", "content": prompt})
            _ask_and_append(actor, history, prompt)
            st.rerun()

        to_speak = st.session_state.pop("jarvis_speak_next", None)
        if to_speak: _speak(to_speak)
