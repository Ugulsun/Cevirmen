import streamlit as st
import google.genai as genai
import json
import time

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Nobel Çevirmen", page_icon="📚", layout="wide")

st.title("📚 Nobel Çevirmen - Kişisel CAT Tool")
st.markdown("---")

# --- YAN MENÜ (API KEY & AYARLAR) ---
with st.sidebar:
    st.header("⚙️ Ayarlar")
    api_key = st.text_input("Google API Key", type="password", help="AI Studio'dan aldığın anahtarı buraya yapıştır.")
    
    st.subheader("📝 Talimatlar")
    varsayilan_talimat = """Sen Nobel ödüllü bir çevirmensin. Anlam odaklı çevir.
    - İngilizce tırnakları Türkçe (" ") yap.
    - 'Kelime' yerine 'Sözcük' kullan.
    - Akıcı ve edebi bir dil kullan."""
    
    sistem_talimati = st.text_area("Sistem Kuralları", value=varsayilan_talimat, height=200)
    
    # Hafıza Dosyası Yükleme (Opsiyonel)
    uploaded_hafiza = st.file_uploader("Hafıza Dosyası (json)", type=["json"])
    hafiza = []
    if uploaded_hafiza:
        hafiza = json.load(uploaded_hafiza)
        st.success(f"🧠 {len(hafiza)} kural hafızaya yüklendi!")

# --- ANA FONKSİYONLAR ---
def ceviriyi_baslat(metin, kurallar, hafiza_listesi, model_adi="gemini-2.5-pro"):
    client = genai.Client(api_key=api_key)
    
    # Hafızayı metne dök
    hafiza_metni = ""
    if hafiza_listesi:
        hafiza_metni = "\nUNUTMA (ÖĞRENDİKLERİN):\n" + "\n".join([f"- {k['kural']}" for k in hafiza_listesi])
    
    prompt = f"""{kurallar}
    {hafiza_metni}
    
    ÇEVRİLECEK METİN:
    {metin}
    """
    
    response = client.models.generate_content(
        model=model_adi,
        contents=prompt
    )
    return response.text

def ders_cikar(ham_metin, duzeltilmis_metin):
    client = genai.Client(api_key=api_key)
    prompt = f"""
    Ham Çeviri: "{ham_metin}"
    İnsan Düzeltmesi: "{duzeltilmis_metin}"
    
    Bu iki metin arasındaki farktan, çevirmenin stilini yansıtan genel bir kural çıkar.
    Çıktıyı sadece JSON formatında ver: {{"kural": "..."}}
    """
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config={'response_mime_type': 'application/json'}
    )
    return json.loads(response.text)

# --- ARAYÜZ SEKMELERİ ---
tab1, tab2 = st.tabs(["📖 Çeviri Yap", "🧠 Eğit (Ders Çıkar)"])

# 1. SEKME: ÇEVİRİ
with tab1:
    st.header("Dosya Çevirisi")
    uploaded_file = st.file_uploader("Çevrilecek .txt dosyasını yükle", type=["txt"])
    
    if uploaded_file and api_key:
        metin = uploaded_file.read().decode("utf-8")
        st.info(f"Dosya yüklendi: {len(metin)} karakter.")
        
        if st.button("🚀 Çeviriyi Başlat"):
            with st.spinner("Gemini çalışıyor..."):
                try:
                    # Basitlik için tüm metni gönderiyoruz (Çok uzunsa parça parça yapmak gerekir)
                    ceviri = ceviriyi_baslat(metin, sistem_talimati, hafiza)
                    
                    st.success("Çeviri Tamamlandı!")
                    st.text_area("Sonuç:", value=ceviri, height=300)
                    
                    st.download_button(
                        label="📥 Çeviriyi İndir",
                        data=ceviri,
                        file_name=f"TR_{uploaded_file.name}",
                        mime="text/plain"
                    )
                except Exception as e:
                    st.error(f"Hata: {e}")

# 2. SEKME: EĞİTİM
with tab2:
    st.header("Hatalardan Ders Çıkar")
    col1, col2 = st.columns(2)
    with col1:
        ham_txt = st.text_area("Yapay Zeka Çevirisi (Eski)", height=150)
    with col2:
        duzeltilmis_txt = st.text_area("Senin Düzeltmen (Yeni)", height=150)
        
    if st.button("🎓 Analiz Et ve Öğren"):
        if api_key and ham_txt and duzeltilmis_txt:
            with st.spinner("Analiz ediliyor..."):
                try:
                    yeni_kural = ders_cikar(ham_txt, duzeltilmis_txt)
                    st.success("Yeni Kural Öğrenildi!")
                    st.json(yeni_kural)
                    st.warning("Not: Bu kuralı 'hafiza.json' dosyana eklemeyi unutma.")
                except Exception as e:
                    st.error(f"Hata: {e}")
