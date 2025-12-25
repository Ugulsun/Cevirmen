import streamlit as st
import google.genai as genai
import json
import io
import zipfile
from pypdf import PdfReader
from docx import Document

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Nobel Çevirmen Pro", page_icon="📚", layout="wide")

st.title("📚 Nobel Çevirmen: Proje İstasyonu")
st.markdown("PDF, Word ve TXT dosyalarını yükle, proje bazlı çevir.")

# --- YAN MENÜ (AYARLAR & HAFIZA) ---
with st.sidebar:
    st.header("⚙️ Proje Ayarları")
    
    # API Key
    api_key = st.text_input("Google API Key", type="password", help="Anahtarın burada güvende.")
    
    st.divider()
    
    # 1. PROJE İSMİ
    proje_adi = st.text_input("📁 Proje Adı", value="Yeni_Kitap_Projesi")
    
    st.divider()

    # 2. HAFIZA YÖNETİMİ (PROJE BAZLI)
    st.subheader("🧠 Proje Hafızası")
    st.info("Her projenin 'öğrendikleri' farklı olabilir. İlgili hafıza dosyasını buradan yükle.")
    
    uploaded_hafiza = st.file_uploader("Hafıza Yükle (.json)", type=["json"], key="hafiza_upload")
    
    hafiza = []
    if uploaded_hafiza:
        try:
            hafiza = json.load(uploaded_hafiza)
            st.success(f"✅ {len(hafiza)} kural yüklendi!")
        except:
            st.error("Hafıza dosyası bozuk.")
    else:
        st.warning("Şu an hafıza boş (Varsayılan kurallar geçerli).")

    # 3. TALİMATLAR
    st.subheader("📜 Genel Talimatlar")
    varsayilan_talimat = """Sen Nobel ödüllü bir çevirmensin. Anlam ve duygu odaklı çevir.
    - İngilizce tırnakları Türkçe (" ") yap.
    - 'Kelime' yerine 'Sözcük' kullan.
    - Akıcı, edebi ve modern Türkçe kullan."""
    sistem_talimati = st.text_area("Editör Talimatları", value=varsayilan_talimat, height=150)

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
        hafiza_metni = "\nBUNLARI ASLA UNUTMA (ÖĞRENİLEN KURALLAR):\n" + "\n".join([f"- {k['kural']}" for k in hafiza_listesi])
    
    prompt = f"""{kurallar}
    {hafiza_metni}
    
    GÖREV: Aşağıdaki metni Türkçeye çevir. Formatı (paragrafları) koru.
    
    ÇEVRİLECEK METİN:
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
tab1, tab2 = st.tabs(["📂 Proje Dosyaları (Çeviri)", "🎓 Eğit & Hafıza İndir"])

# --- 1. SEKME: ÇEVİRİ MERKEZİ ---
with tab1:
    st.subheader(f"Proje: {proje_adi}")
    
    # Çoklu dosya yükleme
    uploaded_files = st.file_uploader("Dosyaları Sürükle (PDF, DOCX, TXT)", accept_multiple_files=True)
    
    if uploaded_files and st.button("🚀 Tümünü Çevir"):
        if not api_key:
            st.error("Önce sol menüden API Key girmelisin!")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Sonuçları hafızada tutmak için sözlük
            sonuclar = {}
            
            for i, dosya in enumerate(uploaded_files):
                status_text.text(f"İşleniyor: {dosya.name}...")
                
                # 1. Oku
                ham_icerik = dosya_oku(dosya)
                
                # 2. Çevir (Metin çok uzunsa parçalamak gerekir, şimdilik bütün atıyoruz)
                # Not: PDF'ler çok uzunsa Gemini limitine takılabilir.
                ceviri_sonucu = ceviriyi_yap(ham_icerik, sistem_talimati, hafiza, api_key)
                
                # 3. Sonucu Kaydet
                yeni_isim = f"TR_{dosya.name.split('.')[0]}.txt"
                sonuclar[yeni_isim] = ceviri_sonucu
                
                # İlerleme çubuğunu güncelle
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            status_text.text("✅ Tüm işlemler tamamlandı!")
            
            # --- ZIP İNDİRME ---
            # Tüm çevirileri bir ZIP dosyasına koyuyoruz
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
            
            # Ekranda önizleme göster
            with st.expander("Sonuç Önizlemeleri"):
                for isim, icerik in sonuclar.items():
                    st.text_area(isim, icerik[:1000] + "...", height=150)

# --- 2. SEKME: EĞİTİM & HAFIZA ---
with tab2:
    st.header("Hatalardan Ders Çıkar & Kaydet")
    
    col1, col2 = st.columns(2)
    with col1:
        ham_txt = st.text_area("Yapay Zeka Çevirisi", height=150, placeholder="Ham çeviriyi buraya yapıştır...")
    with col2:
        duzeltilmis_txt = st.text_area("Senin Düzeltmen", height=150, placeholder="Düzeltilmiş halini buraya yapıştır...")
        
    if st.button("Analiz Et ve Hafızaya Ekle"):
        if api_key and ham_txt and duzeltilmis_txt:
            with st.spinner("Gemini analiz ediyor..."):
                try:
                    yeni_kural = ders_cikar(ham_txt, duzeltilmis_txt, api_key)
                    hafiza.append(yeni_kural) # Geçici hafızaya ekle
                    st.success("Yeni Kural Öğrenildi!")
                    st.json(yeni_kural)
                except Exception as e:
                    st.error(f"Hata: {e}")
    
    st.divider()
    
    # HAFIZAYI İNDİR BUTONU (Persistence Çözümü)
    st.subheader("💾 Hafızayı Yedekle")
    st.markdown("Projeyi kapatmadan önce, bugünkü öğrendiklerini indir. Bir sonraki sefere sol menüden geri yüklersin.")
    
    hafiza_json = json.dumps(hafiza, ensure_ascii=False, indent=4)
    st.download_button(
        label="🧠 Güncel Hafıza Dosyasını İndir (.json)",
        data=hafiza_json,
        file_name=f"{proje_adi}_hafiza.json",
        mime="application/json"
    )
