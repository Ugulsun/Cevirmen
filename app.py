import streamlit as st
import google.genai as genai
import json
import io
import zipfile
from pypdf import PdfReader
from docx import Document

# --- SAYFA AYARLARI (KEDİ BURADA! 🐱‍💻) ---
st.set_page_config(page_title="Çeviri", page_icon="🐱‍💻", layout="wide")

st.title("🐱‍💻 Çeviri İstasyonu")
st.markdown("PDF, Word ve TXT dosyalarını yükle, proje bazlı çevir.")

# --- YAN MENÜ (AYARLAR & HAFIZA) ---
with st.sidebar:
    st.header("⚙️ Ayarlar")
    
    # API Key
    api_key = st.text_input("Google API Key", type="password", help="Anahtarın burada güvende.")
    
    st.divider()
    
    # 1. PROJE İSMİ
    proje_adi = st.text_input("📁 Proje Adı", value="Yeni_Proje")
    
    st.divider()

    # 2. HAFIZA YÖNETİMİ
    st.subheader("🧠 Proje Hafızası")
    st.info("Bu projenin öğrendiği kuralları (.json) buradan yükle.")
    
    uploaded_hafiza = st.file_uploader("Hafıza Dosyası Seç", type=["json"], key="hafiza_upload")
    
    hafiza = []
    if uploaded_hafiza:
        try:
            hafiza = json.load(uploaded_hafiza)
            st.success(f"✅ {len(hafiza)} kural yüklendi!")
        except:
            st.error("Dosya okunamadı.")
    else:
        st.caption("Henüz hafıza yüklenmedi, varsayılan kurallar geçerli.")

    # 3. TALİMATLAR
    st.subheader("📜 Talimatlar")
    varsayilan_talimat = """Sen profesyonel bir kitap çevirmenisin.
    - Anlam ve duygu odaklı çevir.
    - İngilizce tırnakları Türkçe (" ") yap.
    - 'Kelime' yerine 'Sözcük' kullan.
    - Akıcı, edebi ve modern Türkçe kullan."""
    sistem_talimati = st.text_area("Çeviri Kuralları", value=varsayilan_talimat, height=150)

# --- FONKSİYONLAR ---

def dosya_oku(uploaded_file):
    """Dosya tipine göre okuma yapar."""
    text = ""
    try:
        if uploaded_file.name.endswith(".pdf"):
            reader = PdfReader(uploaded_file)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif uploaded_file.name.endswith(".docx"):
            doc = Document(uploaded_file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        else: # .txt varsayalım
            text = uploaded_file.read().decode("utf-8")
    except Exception as e:
        return f"HATA: Dosya okunamadı. {e}"
    return text

def ceviriyi_yap(metin, kurallar, hafiza_listesi, api_key):
    if not api_key:
        return "Lütfen API Key girin."
    
    client = genai.Client(api_key=api_key)
    
    # Hafızayı prompta ekle
    hafiza_metni = ""
    if hafiza_listesi:
        hafiza_metni = "\nBUNLARI UNUTMA (ÖĞRENDİĞİN KURALLAR):\n" + "\n".join([f"- {k['kural']}" for k in hafiza_listesi])
    
    prompt = f"""{kurallar}
    {hafiza_metni}
    
    GÖREV: Aşağıdaki metni Türkçeye çevir. Formatı koru.
    
    METİN:
    {metin}
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"API Hatası: {e}"

def ders_cikar(ham_metin, duzeltilmis_metin, api_key):
    client = genai.Client(api_key=api_key)
    prompt = f"""
    Ham Çeviri: "{ham_metin}"
    İnsan Düzeltmesi: "{duzeltilmis_metin}"
    
    Farkları analiz et ve çevirmenin stiline dair GENEL BİR KURAL çıkar.
    Sadece JSON formatında ver: {{"kural": "..."}}
    """
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config={'response_mime_type': 'application/json'}
    )
    return json.loads(response.text)

# --- ANA EKRAN SEKMELERİ ---
tab1, tab2 = st.tabs(["📂 Çeviri", "🎓 Öğren"])

# --- 1. SEKME: ÇEVİRİ ---
with tab1:
    st.subheader(f"Proje: {proje_adi}")
    
    uploaded_files = st.file_uploader("Dosyaları Buraya Bırak (PDF, DOCX, TXT)", accept_multiple_files=True)
    
    if uploaded_files and st.button("🚀 Çevir"):
        if not api_key:
            st.error("Lütfen soldan API Key girin.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            sonuclar = {}
            
            for i, dosya in enumerate(uploaded_files):
                status_text.text(f"Çevriliyor: {dosya.name}...")
                ham_icerik = dosya_oku(dosya)
                # Not: Çok uzun metinlerde parçalama yapmak gerekebilir.
                ceviri_sonucu = ceviriyi_yap(ham_icerik, sistem_talimati, hafiza, api_key)
                
                yeni_isim = f"TR_{dosya.name.split('.')[0]}.txt"
                sonuclar[yeni_isim] = ceviri_sonucu
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            status_text.success("✅ Tamamlandı!")
            
            # ZIP İndirme
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for isim, icerik in sonuclar.items():
                    zf.writestr(isim, icerik)
            
            st.download_button(
                label=f"📦 {proje_adi}_Ceviriler.zip İndir",
                data=zip_buffer.getvalue(),
                file_name=f"{proje_adi}_Ceviriler.zip",
                mime="application/zip"
            )
            
            with st.expander("Sonuçları Gör"):
                for isim, icerik in sonuclar.items():
                    st.text_area(isim, icerik[:1000] + "...", height=150)

# --- 2. SEKME: EĞİTİM ---
with tab2:
    st.header("Stil Öğret")
    st.markdown("Gemini'nin yaptığı hatayı ve senin düzeltmeni buraya gir.")
    
    col1, col2 = st.columns(2)
    with col1:
        ham_txt = st.text_area("Yapay Zeka Çevirisi", height=150)
    with col2:
        duzeltilmis_txt = st.text_area("Senin Düzeltmen", height=150)
        
    if st.button("Analiz Et ve Kaydet"):
        if api_key and ham_txt and duzeltilmis_txt:
            with st.spinner("Analiz ediliyor..."):
                try:
                    yeni_kural = ders_cikar(ham_txt, duzeltilmis_txt, api_key)
                    hafiza.append(yeni_kural)
                    st.success("Yeni kural eklendi!")
                    st.json(yeni_kural)
                except Exception as e:
                    st.error(f"Hata: {e}")
    
    st.divider()
    
    # HAFIZA İNDİRME
    hafiza_json = json.dumps(hafiza, ensure_ascii=False, indent=4)
    st.download_button(
        label="💾 Hafızayı İndir (.json)",
        data=hafiza_json,
        file_name=f"{proje_adi}_hafiza.json",
        mime="application/json"
    )
