import streamlit as st
import google.genai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
import json
import io
import time
from datetime import datetime
from pypdf import PdfReader
from docx import Document

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Çeviri", page_icon="🐱‍💻", layout="wide")

# --- DRIVE BAĞLANTISI ---
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    if "GCP_JSON" not in st.secrets:
        st.error("⚠️ Secrets içinde 'GCP_JSON' bulunamadı. Lütfen Service Account JSON içeriğini ekleyin.")
        st.stop()
    
    creds_info = json.loads(st.secrets["GCP_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_nobel_folder_id(service):
    """-CEVIRI PROJELERI klasörünün ID'sini bulur, yoksa uyarır."""
    query = "name = '-CEVIRI PROJELERI' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        st.error("❌ Google Drive'da '-CEVIRI PROJELERI' klasörü bulunamadı! Lütfen oluşturun ve bot mailiyle paylaşın.")
        st.stop()
    return items[0]['id']

def save_project_to_drive(service, folder_id, project_data, project_name):
    """Proje verilerini JSON olarak Drive'a kaydeder (Basit Mod)."""
    file_metadata = {
        'name': 'project_data.json',
        'mimeType': 'application/json',
        'parents': [folder_id]
    }
    
    # Mevcut dosyayı bul
    query = f"name = 'project_data.json' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    items = results.get('files', [])
    
    # JSON verisini hazırla
    json_bytes = json.dumps(project_data, ensure_ascii=False, indent=4).encode('utf-8')
    
    # KRİTİK DÜZELTME: resumable=False
    media = MediaIoBaseUpload(io.BytesIO(json_bytes),
                              mimetype='application/json', 
                              resumable=False) 
    
    if items:
        # Güncelle
        file_id = items[0]['id']
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        # Yarat
        service.files().create(body=file_metadata, media_body=media).execute()

def load_project_from_drive(service, folder_id):
    """Drive'dan proje verisini çeker."""
    query = f"name = 'project_data.json' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    items = results.get('files', [])
    
    if not items:
        return None
    
    file_id = items[0]['id']
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    
    fh.seek(0)
    return json.load(fh)

# --- YARDIMCI METİN İŞLEMLERİ ---
def metni_parcala(metin):
    return [p.strip() for p in metin.split('\n\n') if p.strip()]

def paragraf_eslestir(orjinal_liste, ceviri_liste):
    """Yarım çeviri ile orijinali eşleştirir."""
    data = []
    len_ceviri = len(ceviri_liste)
    for i, orj in enumerate(orjinal_liste):
        durum = "bekliyor"
        ceviri = ""
        if i < len_ceviri:
            ceviri = ceviri_liste[i]
            durum = "onaylandi"
        
        data.append({
            "id": i,
            "orjinal": orj,
            "ceviri": ceviri,
            "durum": durum
        })
    return data

def ceviri_yap_gemini(metin, api_key, talimatlar):
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""{talimatlar}
        Yorum yapma, sadece çeviriyi ver.
        METİN: {metin}
        """
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return response.text
    except Exception as e:
        return f"Hata: {str(e)}"

# --- ARAYÜZ ---
if "aktif_proje" not in st.session_state:
    st.session_state.aktif_proje = None

# Drive Servisini Başlat
try:
    srv = get_drive_service()
    ana_folder_id = get_nobel_folder_id(srv)
except Exception as e:
    st.error(f"Bağlantı Hatası: {e}")
    st.stop()

with st.sidebar:
    st.title("⚙️ Ayarlar")
    api_key = st.text_input("Gemini API Key", type="password")
    
    st.divider()
    if st.button("Çıkış / Proje Kapat"):
        st.session_state.aktif_proje = None
        st.rerun()

# --- EKRAN 1: PROJE LİSTESİ ---
if st.session_state.aktif_proje is None:
    st.title("📂 Projeler (Drive)")
    
    tabs = st.tabs(["Mevcut Projeler", "Yeni Proje Oluştur"])
    
    with tabs[0]:
        q = f"'{ana_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = srv.files().list(q=q, fields="files(id, name)").execute()
        projeler = results.get('files', [])
        
        if not projeler:
            st.info("Drive'da hiç proje klasörü yok.")
        
        for p in projeler:
            col1, col2 = st.columns([3, 1])
            col1.subheader(f"📁 {p['name']}")
            if col2.button("Projeyi Aç", key=p['id']):
                data = load_project_from_drive(srv, p['id'])
                if data:
                    st.session_state.aktif_proje = data
                    st.session_state.aktif_folder_id = p['id']
                    st.rerun()
                else:
                    st.error("Proje verisi okunamadı.")

    with tabs[1]:
        st.subheader("Yeni Proje Başlat")
        proje_adi = st.text_input("Proje Adı (Klasör Adı)")
        dosya_orj = st.file_uploader("1. Orijinal Dosya (Zorunlu)", type=['txt', 'docx', 'pdf'])
        dosya_cev = st.file_uploader("2. Yarım Çeviri (Varsa)", type=['txt', 'docx', 'pdf'], help="Varsa yarım çeviriyi yükle.")
        
        if st.button("Oluştur") and proje_adi and dosya_orj:
            with st.spinner("Drive klasörü oluşturuluyor..."):
                # Dosya okuma
                def read_file(f):
                    if f.name.endswith('.pdf'):
                        r = PdfReader(f); return "".join([p.extract_text() for p in r.pages])
                    elif f.name.endswith('.docx'):
                        d = Document(f); return "\n\n".join([p.text for p in d.paragraphs])
                    else: return f.read().decode('utf-8')
                
                txt_orj = read_file(dosya_orj)
                txt_cev = read_file(dosya_cev) if dosya_cev else ""
                
                list_orj = metni_parcala(txt_orj)
                list_cev = metni_parcala(txt_cev)
                
                project_data = {
                    "meta": {"ad": proje_adi, "tarih": str(datetime.now())},
                    "paragraflar": paragraf_eslestir(list_orj, list_cev)
                }
                
                # Drive işlemleri
                folder_meta = {
                    'name': proje_adi,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [ana_folder_id]
                }
                folder = srv.files().create(body=folder_meta, fields='id').execute()
                new_folder_id = folder.get('id')
                
                save_project_to_drive(srv, new_folder_id, project_data, proje_adi)
                st.success(f"Proje oluşturuldu! {len(list_cev)} paragraf hazır eşleştirildi.")

# --- EKRAN 2: EDİTÖR ---
else:
    proje = st.session_state.aktif_proje
    folder_id = st.session_state.aktif_folder_id
    paragraflar = proje["paragraflar"]
    
    st.header(f"📝 {proje['meta']['ad']}")
    
    toplam = len(paragraflar)
    biten = len([p for p in paragraflar if p['durum'] == 'onaylandi'])
    st.progress(biten/toplam, text=f"İlerleme: {biten}/{toplam}")
    
    if "cursor" not in st.session_state:
        first_waiting = next((i for i, p in enumerate(paragraflar) if p['durum'] == 'bekliyor'), 0)
        st.session_state.cursor = first_waiting

    col1, col2, col3, col4 = st.columns([1, 1, 2, 1])
    if col1.button("⬅️ Önceki"): st.session_state.cursor = max(0, st.session_state.cursor - 1)
    if col2.button("Sonraki ➡️"): st.session_state.cursor = min(toplam - 1, st.session_state.cursor + 1)
    
    yeni_cursor = col3.number_input("Git", min_value=1, max_value=toplam, value=st.session_state.cursor + 1) - 1
    if yeni_cursor != st.session_state.cursor:
        st.session_state.cursor = yeni_cursor
        st.rerun()

    if col4.button("⏭️ Boşa Git"):
        next_waiting = next((i for i, p in enumerate(paragraflar) if p['durum'] == 'bekliyor'), st.session_state.cursor)
        st.session_state.cursor = next_waiting
        st.rerun()

    # Editör
    idx = st.session_state.cursor
    current_p = paragraflar[idx]
    
    st.divider()
    st.markdown(f"### Paragraf {idx + 1}")
    
    c_sol, c_sag = st.columns(2)
    with c_sol:
        st.info(current_p['orjinal'])
    
    with c_sag:
        if not current_p['ceviri'] and api_key:
            with st.spinner("Çevriliyor..."):
                oto_ceviri = ceviri_yap_gemini(current_p['orjinal'], api_key, "Sen profesyonel çevirmensin.")
                current_p['ceviri'] = oto_ceviri
        
        yeni_metin = st.text_area("Çeviri", value=current_p['ceviri'], height=200)
        
        if st.button("✅ Onayla", type="primary"):
            current_p['ceviri'] = yeni_metin
            current_p['durum'] = 'onaylandi'
            save_project_to_drive(srv, folder_id, proje, proje['meta']['ad'])
            
            if idx < toplam - 1:
                st.session_state.cursor += 1
            st.toast("Kaydedildi!")
            st.rerun()
            
    st.divider()
    if st.button("Word İndir"):
        doc = Document()
        doc.add_heading(proje['meta']['ad'], 0)
        for p in paragraflar:
            if p['durum'] == 'onaylandi':
                doc.add_paragraph(p['ceviri'])
            else:
                doc.add_paragraph(f"--- [Çevrilmedi] ---")
        bio = io.BytesIO()
        doc.save(bio)
        st.download_button("Dosyayı İndir", bio.getvalue(), file_name=f"{proje['meta']['ad']}.docx")
