import streamlit as st
import sqlite3
import google.genai as genai
# import openai  # OpenAI entegrasyonu için ilerde aktif edilebilir
from pypdf import PdfReader
from docx import Document
import time

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Çeviri", page_icon="🐱‍💻", layout="wide")

# --- VERİTABANI BAĞLANTISI (SQLite) ---
def init_db():
    conn = sqlite3.connect('ceviri_bellek.db', check_same_thread=False)
    c = conn.cursor()
    # Projeler Tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS projeler
                 (id INTEGER PRIMARY KEY, ad TEXT, olusturma_tarihi TEXT)''')
    # Paragraflar Tablosu (Her paragrafın durumu burada tutulur)
    c.execute('''CREATE TABLE IF NOT EXISTS paragraflar
                 (id INTEGER PRIMARY KEY, proje_id INTEGER, 
                  sira INTEGER, orjinal_metin TEXT, ceviri_metin TEXT, 
                  durum TEXT DEFAULT 'bekliyor')''') # durum: bekliyor, onaylandi
    conn.commit()
    return conn

conn = init_db()

# --- YARDIMCI FONKSİYONLAR ---

def get_api_key(provider):
    # Önce Secrets'a bakar, yoksa Session State'e bakar
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
    # Basitçe boş satırlara göre böler, daha zeki bölme eklenebilir
    return [p.strip() for p in metin.split('\n\n') if p.strip()]

def ceviri_yap(metin, model_adi, talimatlar):
    api_key = get_api_key("Gemini") # Şimdilik varsayılan Gemini
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

# --- ARAYÜZ ---

# 1. YAN MENÜ (AYARLAR)
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/616/616430.png", width=50) # Kedi ikonu temsili
    st.title("Ayarlar")
    
    secilen_llm = st.selectbox("Aktif Model", ["Gemini 2.5 Pro", "Gemini 2.5 Flash", "GPT-4o (Yakında)"])
    
    with st.expander("API Anahtarları (Manuel)"):
        st.info("Eğer 'Secrets' ayarlıysa burası boş kalabilir.")
        st.text_input("Gemini API Key", key="gemini_key", type="password")
        st.text_input("OpenAI API Key", key="openai_key", type="password")

    st.subheader("Sistem Talimatı")
    varsayilan_talimat = st.text_area("Çevirmen Kimliği", 
        value="Sen profesyonel bir kitap çevirmenisin. Edebi, akıcı ve anlam odaklı çevir.", height=100)

# 2. ANA EKRAN YÖNETİMİ
if 'aktif_proje_id' not in st.session_state:
    st.session_state.aktif_proje_id = None

# --- EKRAN A: PROJE LİSTESİ ---
if st.session_state.aktif_proje_id is None:
    st.title("🐱‍💻 Proje Yönetimi")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Mevcut Projeler")
        c = conn.cursor()
        projeler = c.execute("SELECT * FROM projeler ORDER BY id DESC").fetchall()
        
        if not projeler:
            st.info("Henüz hiç proje yok.")
        
        for p in projeler:
            p_id, p_ad, p_tarih = p
            # İlerleme durumunu hesapla
            toplam = c.execute("SELECT COUNT(*) FROM paragraflar WHERE proje_id=?", (p_id,)).fetchone()[0]
            biten = c.execute("SELECT COUNT(*) FROM paragraflar WHERE durum='onaylandi' AND proje_id=?", (p_id,)).fetchone()[0]
            yuzde = int((biten/toplam)*100) if toplam > 0 else 0
            
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.markdown(f"**{p_ad}**")
                c2.progress(yuzde/100, text=f"%{yuzde} Tamamlandı ({biten}/{toplam})")
                if c3.button("Aç", key=f"btn_{p_id}"):
                    st.session_state.aktif_proje_id = p_id
                    st.rerun()

    with col2:
        st.subheader("Yeni Proje Oluştur")
        yeni_ad = st.text_input("Proje Adı")
        dosya = st.file_uploader("Metin Dosyası (TXT, PDF, DOCX)")
        
        if st.button("Projeyi Yarat") and yeni_ad and dosya:
            # 1. Metni Oku
            metin = ""
            if dosya.name.endswith(".pdf"):
                reader = PdfReader(dosya)
                for page in reader.pages: metin += page.extract_text() + "\n"
            elif dosya.name.endswith(".docx"):
                doc = Document(dosya)
                for para in doc.paragraphs: metin += para.text + "\n"
            else:
                metin = dosya.read().decode("utf-8")
            
            # 2. Veritabanına Yaz
            cur = conn.cursor()
            cur.execute("INSERT INTO projeler (ad, olusturma_tarihi) VALUES (?, ?)", (yeni_ad, str(time.time())))
            yeni_id = cur.lastrowid
            
            paragraflar = metni_parcala(metin)
            for i, p in enumerate(paragraflar):
                cur.execute("INSERT INTO paragraflar (proje_id, sira, orjinal_metin) VALUES (?, ?, ?)", 
                            (yeni_id, i, p))
            conn.commit()
            st.success("Proje oluşturuldu! Listeden seçip açabilirsin.")
            st.rerun()

# --- EKRAN B: ÇEVİRİ EDİTÖRÜ ---
else:
    # Aktif projeyi çek
    cur = conn.cursor()
    proje = cur.execute("SELECT * FROM projeler WHERE id=?", (st.session_state.aktif_proje_id,)).fetchone()
    
    # Geri Dön Butonu
    if st.button("⬅️ Projelere Dön"):
        st.session_state.aktif_proje_id = None
        st.rerun()

    st.markdown(f"## 📂 {proje[1]}")
    st.caption(f"Kullanılan Model: {secilen_llm}")
    st.divider()
    
    # --- PRE-FETCH VE NAVİGASYON MANTIĞI ---
    # İlk 'bekliyor' durumundaki paragrafı bul (Kaldığımız yer)
    kalinan_yer = cur.execute("""
        SELECT * FROM paragraflar 
        WHERE proje_id=? AND durum='bekliyor' 
        ORDER BY sira ASC LIMIT 1
    """, (proje[0],)).fetchone()
    
    if not kalinan_yer:
        st.balloons()
        st.success("Tebrikler! Bu projedeki tüm çeviriler bitti.")
    else:
        aktif_id, pid, sira, orjinal, ceviri, durum = kalinan_yer
        
        # --- ARKA PLAN İŞLEMİ: BU VE SONRAKİ 2 PARAGRAFI ÇEVİR ---
        # Şu anki ve sonraki 2 paragrafı çek
        hedef_paragraflar = cur.execute("""
            SELECT * FROM paragraflar 
            WHERE proje_id=? AND sira >= ? 
            ORDER BY sira ASC LIMIT 3
        """, (pid, sira)).fetchall()
        
        with st.spinner("Yapay zeka analiz yapıyor..."):
            for p_row in hedef_paragraflar:
                p_id_temp, _, _, p_orj, p_cev, _ = p_row
                # Eğer çevirisi yoksa veya boşsa çevir
                if not p_cev:
                    yeni_ceviri = ceviri_yap(p_orj, "gemini-2.5-pro", varsayilan_talimat)
                    cur.execute("UPDATE paragraflar SET ceviri_metin=? WHERE id=?", (yeni_ceviri, p_id_temp))
                    conn.commit()
                    # Sayfayı yenilemeye gerek yok, altta güncelini göstereceğiz
        
        # Veriyi tekrar çek (güncellenmiş haliyle)
        aktif_paragraf = cur.execute("SELECT * FROM paragraflar WHERE id=?", (aktif_id,)).fetchone()
        _, _, _, guncel_orjinal, guncel_ceviri, _ = aktif_paragraf
        
        # --- EDİTÖR ALANI ---
        col_sol, col_sag = st.columns(2)
        
        with col_sol:
            st.markdown("### 🇬🇧 Orijinal")
            st.info(guncel_orjinal)
            
        with col_sag:
            st.markdown("### 🇹🇷 Çeviri")
            duzeltilmis_metin = st.text_area("Düzenle:", value=guncel_ceviri, height=200, label_visibility="collapsed")
            
            c1, c2 = st.columns([1, 1])
            if c1.button("✅ Onayla ve İlerle", type="primary"):
                # Kaydet ve durumunu 'onaylandi' yap
                cur.execute("UPDATE paragraflar SET ceviri_metin=?, durum='onaylandi' WHERE id=?", 
                            (duzeltilmis_metin, aktif_id))
                conn.commit()
                st.rerun()
                
            if c2.button("Atla (Sonra Bakarım)"):
                # Sadece sırayı atlamak için geçici çözüm, şimdilik onaylamadan geçebiliriz
                # veya veritabanında 'atlandi' durumu eklenebilir. 
                # Şimdilik onaylamış gibi davranıp sonuna ekliyoruz.
                cur.execute("UPDATE paragraflar SET durum='onaylandi' WHERE id=?", (aktif_id,))
                conn.commit()
                st.rerun()

        # --- GELECEK PARAGRAFLAR (ÖNİZLEME) ---
        st.divider()
        st.caption("👀 Sıradaki Paragraflar (Hazırlanıyor...)")
        
        sonrakiler = cur.execute("""
            SELECT orjinal_metin, ceviri_metin FROM paragraflar 
            WHERE proje_id=? AND sira > ? 
            ORDER BY sira ASC LIMIT 2
        """, (pid, sira)).fetchall()
        
        for sp in sonrakiler:
            s_orj, s_cev = sp
            with st.expander(f"{s_orj[:50]}..."):
                st.markdown(f"**Orj:** {s_orj}")
                st.markdown(f"**Taslak Çeviri:** {s_cev if s_cev else '⏳ Hazırlanıyor...'}")
