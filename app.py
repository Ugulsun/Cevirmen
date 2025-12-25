import streamlit as st
import google.genai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
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
        st.error("⚠️ Secrets içinde 'GCP_JSON' bulunamadı.")
        st.stop()
    
    creds_info = json.loads(st.secrets["GCP_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_nobel_folder_id(service):
    """-CEVIRI PROJELERI klasörünü bulur."""
    # supportsAllDrives=True ile her yerde arar
    query = "name = '-CEVIRI PROJELERI' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    try:
        results = service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = results.get('files', [])
        if not items:
            st.error("❌ Google Drive'da '-CEVIRI PROJELERI' klasörü bulunamadı!")
            st.stop()
        return items[0]['id']
    except HttpError as e:
        st.error(f"Klasör Aranırken Hata Oluştu: {e}")
        st.stop()

def save_project_to_drive(service, folder_id, project_data, project_name):
    """Proje verilerini kaydeder (HATA YAKALAMA MODU)."""
    file_metadata = {
        'name': 'project_data.json',
        'mimeType': 'application/json',
        'parents': [folder_id]
    }
    
    # JSON verisini hazırla
    json_bytes = json.dumps(project_data, ensure_ascii=False, indent=4).encode('utf-8')
    # Resumable=True büyük dosyalar için daha güvenli olabilir, değiştirdim.
    media = MediaIoBaseUpload(io.BytesIO(json_bytes), mimetype='application/json', resumable=True)
    
    try:
        # Dosya var mı kontrol et
        query = f"name = 'project_data.json' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = results.get('files', [])
        
        if items:
            # Güncelle
            service.files().update(fileId=items[0]['id'], media_body=media, supportsAllDrives=True).execute()
        else:
            # Yarat
            service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
            
    except HttpError as e:
        # İŞTE BURASI HATANIN SEBEBİNİ SÖYLEYECEK
        error_content = e.content.decode('utf-8') if e.content else "Detay yok"
        st.error(f"🚨 KAYIT HATASI (HttpError) Detayı:\nStatus: {e.resp.status}\nMesaj: {error_content}")
        raise e # İşlemi durdur

def load_project_from_drive(service, folder_id):
    """Drive'dan veriyi çeker."""
    try:
        query = f"name = 'project_data.json' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = results.get('files', [])
        
        if not items: return None
        
        request = service.files().get_media(fileId=items[0]['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        fh.seek(0)
        return json.load(fh)
    except Exception as e:
        st.error(f"Dosya Okuma Hatası: {e}")
        return None

def delete_project_folder(service, folder_id):
    """Klasörü çöp kutusuna atar."""
    try:
        service.files().update(fileId=folder_id, body={'trashed': True}, supportsAllDrives=True).execute()
        return True
    except HttpError as e:
        st.error(f"Silme Hatası: {e}")
        return False

def rename_project_folder(service, folder_id, new_name):
    """Klasör adını değiştirir."""
    try:
        service.files().update(fileId=folder_id, body={'name': new_name}, supportsAllDrives=True).execute()
        return True
    except HttpError as e:
        st.error(f"İsim Değiştirme Hatası: {e}")
        return False

# --- YARDIMCI FONKSİYONLAR ---
def metni_parcala(metin):
    return [p.strip() for p in metin.split('\n\n') if p.strip()]

def paragraf_eslestir(orjinal_liste, ceviri_liste):
    data = []
    len_ceviri = len(ceviri_liste)
    for i, orj in enumerate(orjinal_liste):
        durum = "bekliyor"
        ceviri = ""
        if i < len_ceviri:
            ceviri = ceviri_liste[i]
            durum = "onaylandi"
        data.append({"id": i, "orjinal": orj, "ceviri": ceviri, "durum": durum})
    return data

def ceviri_yap_gemini(metin, api_key, talimatlar):
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"{talimatlar}\n\nMETİN: {metin}"
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return response.text
    except Exception as e: return f"Hata: {str(e)}"

# --- ARAYÜZ ---
if "aktif_proje" not in st.session_state:
    st.session_state.aktif_proje = None

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
    if st.button("🚪 Ana Menüye Dön"):
        st.session_state.aktif_proje = None
        st.rerun()

# --- EKRAN 1: PROJE LİSTESİ ---
if st.session_state.aktif_proje is None:
    st.title("📂 Projelerim")
    
    tabs = st.tabs(["Mevcut Projeler", "Yeni Proje Oluştur"])
    
    with tabs[0]:
        # Klasörleri tarihe göre sırala
        results = srv.files().list(q=f"'{ana_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                                   fields="files(id, name, createdTime)", orderBy="createdTime desc", 
                                   supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        projeler = results.get('files', [])
        
        if not projeler:
            st.info("Henüz hiç proje yok. Yandaki sekmeden oluşturabilirsin.")
        
        for p in projeler:
            # UI: Proje Kartı
            with st.container(border=True):
                col_ad, col_bos, col_islem = st.columns([6, 1, 2])
                
                # İsim tıklanabilir buton gibi davranır
                if col_ad.button(f"📂 {p['name']}", key=f"open_{p['id']}", use_container_width=True):
                    with st.spinner("Proje yükleniyor..."):
                        data = load_project_from_drive(srv, p['id'])
                        if data:
                            st.session_state.aktif_proje = data
                            st.session_state.aktif_folder_id = p['id']
                            st.rerun()
                        else:
                            st.error("Bu klasör boş veya veri dosyası (project_data.json) silinmiş.")

                # İşlem Menüsü (Sil / Yeniden Adlandır)
                with col_islem:
                    with st.popover("Ayarlar ⚙️"):
                        yeni_ad = st.text_input("Yeni İsim", value=p['name'], key=f"n_{p['id']}")
                        if st.button("Kaydet", key=f"ren_{p['id']}"):
                            if rename_project_folder(srv, p['id'], yeni_ad):
                                st.success("Değişti!")
                                time.sleep(1)
                                st.rerun()
                        
                        st.divider()
                        if st.button("🗑️ Projeyi Sil", key=f"del_{p['id']}", type="primary"):
                            if delete_project_folder(srv, p['id']):
                                st.success("Silindi!")
                                time.sleep(1)
                                st.rerun()

    with tabs[1]:
        st.subheader("Yeni Proje")
        proje_adi = st.text_input("Proje Adı")
        dosya_orj = st.file_uploader("1. Orijinal Metin", type=['txt', 'docx', 'pdf'])
        dosya_cev = st.file_uploader("2. Yarım Çeviri (Opsiyonel)", type=['txt', 'docx', 'pdf'])
        
        if st.button("Projeyi Oluştur") and proje_adi and dosya_orj:
            with st.spinner("Proje hazırlanıyor..."):
                # 1. Dosya Okuma
                def read_file(f):
                    if f.name.endswith('.pdf'): r = PdfReader(f); return "".join([p.extract_text() for p in r.pages])
                    elif f.name.endswith('.docx'): d = Document(f); return "\n\n".join([p.text for p in d.paragraphs])
                    else: return f.read().decode('utf-8')
                
                txt_orj = read_file(dosya_orj)
                txt_cev = read_file(dosya_cev) if dosya_cev else ""
                
                project_data = {
                    "meta": {"ad": proje_adi, "tarih": str(datetime.now())},
                    "paragraflar": paragraf_eslestir(metni_parcala(txt_orj), metni_parcala(txt_cev))
                }
                
                # 2. Klasör Yarat
                folder_meta = {
