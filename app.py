import streamlit as st
import sqlite3
import google.genai as genai
from pypdf import PdfReader
from docx import Document
import time

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Çeviri", page_icon="🐱‍💻", layout="wide")

# --- GÜVENLİK KONTROLÜ (FEDAI) 🔒 ---
def sifre_kontrol():
    """Doğru şifre girilmeden içeri almaz."""
    
    # Eğer Secrets'ta şifre tanımlı değilse herkesi içeri al (Geliştirme modu)
    if "UYGULAMA_SIFRESI" not in st.secrets:
        st.warning("⚠️ UYARI: Secrets içinde 'UYGULAMA_SIFRESI' tanımlanmamış. Uygulama herkese açık!")
        return True

    if "giris_yapildi" not in st.session_state:
        st.session_state["giris_yapildi"] = False

    if not st.session_state["giris_yapildi"]:
        st.title("🔒 Giriş Yap")
        sifre = st.text_input("Şifre", type="password")
        if st.button("Giriş"):
            if sifre == st.secrets["UYGULAMA_SIFRESI"]:
                st.session_state["giris_yapildi"] = True
                st.rerun() # Sayfayı yenile ve içeri al
            else:
                st.error("Yanlış şifre!")
        return False
    return True

# Eğer şifre kontrolü geçilmezse kodun geri kalanını çalıştırma
if not sifre_kontrol():
    st.stop()

# ==========================================
# BURADAN AŞAĞISI NORMAL UYGULAMA KODLARIN
# ==========================================

# --- VERİTABANI BAĞLANTISI ---
def init_db():
    conn = sqlite3.connect('ceviri_bellek.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS projeler
                 (id INTEGER PRIMARY KEY, ad TEXT, olusturma_tarihi TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS paragraflar
                 (id INTEGER PRIMARY KEY, proje_id INTEGER, 
                  sira INTEGER, orjinal_metin TEXT, ceviri_metin TEXT, 
                  durum TEXT DEFAULT 'bekliyor')''')
    conn.commit()
    return conn

conn = init_db()

# --- YARDIMCI FONKSİYONLAR ---
def get_api_key(provider):
    if provider == "Gemini":
        if "GOOGLE_API_KEY" in st.secrets:
            return st.secrets["GOOGLE_API_KEY"]
        return st.session_state.get("gemini_key", "")
    elif provider == "OpenAI":
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
        return st.session_state.get("openai_key", "")
    return ""

def metni_parcala(metin):
    return [p.strip() for p in metin.split('\n\n') if p.strip()]

def ceviri_yap(metin, model_adi, talimatlar):
    api_key = get_api_key("Gemini")
    if not api_key:
        return "⚠️ API Anahtarı Eksik"
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""{talimatlar}
        METİN: {metin}
        """
        response = client.models.generate_content(model=model_adi, contents=prompt)
        return response.text
    except Exception as e:
        return f"Hata: {str(e)}"

# --- ARAYÜZ BAŞLANGICI ---

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/616/616430.png", width=50)
    st.title("Ayarlar")
    
    # Çıkış Butonu
    if st.button("🔒 Çıkış Yap"):
        st.session_state["giris_yapildi"] = False
        st.rerun()
        
    st.divider()
    
    secilen_llm = st.selectbox("Aktif Model", ["Gemini 2.5 Pro", "Gemini 2.5 Flash"])
    
    with st.expander("API Anahtarları (Manuel)"):
        st.info("Secrets ayarlıysa boş bırakın.")
        st.text_input("Gemini API Key", key="gemini_key", type="password")

    varsayilan_talimat = st.text_area("Çevirmen Kimliği", 
        value="Sen profesyonel bir kitap çevirmenisin. Edebi, akıcı ve anlam odaklı çevir.", height=100)

if 'aktif_proje_id' not in st.session_state:
    st.session_state.aktif_proje_id = None

# EKRAN A: PROJE LİSTESİ
if st.session_state.aktif_proje_id is None:
    st.title("🐱‍💻 Proje Yönetimi")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Mevcut Projeler")
        c = conn.cursor()
        projeler = c.execute("SELECT * FROM projeler ORDER BY id DESC").fetchall()
        
        if not projeler:
            st.info("Henüz proje yok.")
        
        for p in projeler:
            p_id, p_ad, p_tarih = p
            toplam = c.execute("SELECT COUNT(*) FROM paragraflar WHERE proje_id=?", (p_id,)).fetchone()[0]
            biten = c.execute("SELECT COUNT(*) FROM paragraflar WHERE durum='onaylandi' AND proje_id=?", (p_id,)).fetchone()[0]
            yuzde = int((biten/toplam)*100) if toplam > 0 else 0
            
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.markdown(f"**{p_ad}**")
                c2.progress(yuzde/100, text=f"%{yuzde}")
                if c3.button("Aç", key=f"btn_{p_id}"):
                    st.session_state.aktif_proje_id = p_id
                    st.rerun()

    with col2:
        st.subheader("Yeni Proje")
        yeni_ad = st.text_input("Proje Adı")
        dosya = st.file_uploader("Dosya Yükle")
        
        if st.button("Oluştur") and yeni_ad and dosya:
            metin = ""
            if dosya.name.endswith(".pdf"):
                reader = PdfReader(dosya)
                for page in reader.pages: metin += page.extract_text() + "\n"
            elif dosya.name.endswith(".docx"):
                doc = Document(dosya)
                for para in doc.paragraphs: metin += para.text + "\n"
            else:
                metin = dosya.read().decode("utf-8")
            
            cur = conn.cursor()
            cur.execute("INSERT INTO projeler (ad, olusturma_tarihi) VALUES (?, ?)", (yeni_ad, str(time.time())))
            yeni_id = cur.lastrowid
            
            paragraflar = metni_parcala(metin)
            for i, p in enumerate(paragraflar):
                cur.execute("INSERT INTO paragraflar (proje_id, sira, orjinal_metin) VALUES (?, ?, ?)", 
                            (yeni_id, i, p))
            conn.commit()
            st.success("Oluşturuldu!")
            st.rerun()

# EKRAN B: EDİTÖR
else:
    cur = conn.cursor()
    proje = cur.execute("SELECT * FROM projeler WHERE id=?", (st.session_state.aktif_proje_id,)).fetchone()
    
    if st.button("⬅️ Projelere Dön"):
        st.session_state.aktif_proje_id = None
        st.rerun()

    st.markdown(f"## 📂 {proje[1]}")
    st.divider()
    
    kalinan_yer = cur.execute("""
        SELECT * FROM paragraflar 
        WHERE proje_id=? AND durum='bekliyor' 
        ORDER BY sira ASC LIMIT 1
    """, (proje[0],)).fetchone()
    
    if not kalinan_yer:
        st.balloons()
        st.success("Proje bitti!")
    else:
        aktif_id, pid, sira, orjinal, ceviri, durum = kalinan_yer
        
        # Pre-fetch
        hedef_paragraflar = cur.execute("""
            SELECT * FROM paragraflar 
            WHERE proje_id=? AND sira >= ? 
            ORDER BY sira ASC LIMIT 3
        """, (pid, sira)).fetchall()
        
        with st.spinner("Analiz..."):
            for p_row in hedef_paragraflar:
                p_id_temp, _, _, p_orj, p_cev, _ = p_row
                if not p_cev:
                    yeni_ceviri = ceviri_yap(p_orj, "gemini-2.5-pro", varsayilan_talimat)
                    cur.execute("UPDATE paragraflar SET ceviri_metin=? WHERE id=?", (yeni_ceviri, p_id_temp))
                    conn.commit()
        
        aktif_paragraf = cur.execute("SELECT * FROM paragraflar WHERE id=?", (aktif_id,)).fetchone()
        _, _, _, guncel_orjinal, guncel_ceviri, _ = aktif_paragraf
        
        col_sol, col_sag = st.columns(2)
        with col_sol:
            st.info(guncel_orjinal)
        with col_sag:
            duzeltilmis = st.text_area("Çeviri:", value=guncel_ceviri, height=200)
            if st.button("✅ Onayla", type="primary"):
                cur.execute("UPDATE paragraflar SET ceviri_metin=?, durum='onaylandi' WHERE id=?", 
                            (duzeltilmis, aktif_id))
                conn.commit()
                st.rerun()
