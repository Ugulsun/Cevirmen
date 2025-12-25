import streamlit as st
import google.genai as genai
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
import json
import io
import time
from datetime import datetime
from pypdf import PdfReader
from docx import Document

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Çeviri (OAuth)", page_icon="🔑", layout="wide")

# --- OAUTH AYARLARI ---
SCOPES = ['https://www.googleapis.com/auth/drive']
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob" 

def get_auth_flow():
    """Secrets'tan bilgileri alıp OAuth akışını başlatır."""
    if "oauth" not in st.secrets or "CLIENT_CONFIG" not in st.secrets["oauth"]:
        st.error("⚠️ Secrets içinde [oauth] ve CLIENT_CONFIG bulunamadı.")
        st.stop()
        
    client_config = json.loads(st.secrets["oauth"]["CLIENT_CONFIG"])
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    return flow

def authenticate_user():
    """Kullanıcıyı giriş yapmaya zorlar."""
    if "creds" in st.session_state:
        return st.session_state.creds

    st.title("🔑 Google Girişi Gerekli")
    st.info("Kişisel Drive alanını kullanmak için giriş yapmalısın.")
    
    flow = get_auth_flow()
    auth_url, _ = flow.authorization_url(prompt='consent')
    
    st.markdown(f"### 1. Adım: [Buraya Tıkla ve İzin Ver]({auth_url})")
    st.markdown("Linke tıklayıp izin verdikten sonra Google sana bir kod verecek.")
    
    auth_code = st.text_input("### 2. Adım: Kodu buraya yapıştır ve Enter'a bas:")
    
    if auth_code:
        try:
            flow.fetch_token(code=auth_code)
            creds = flow.credentials
            st.session_state.creds = creds
            st.success("Giriş Başarılı! Bekleyin...")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"Giriş Hatası: {str(e)}")
            st.stop()
    st.stop() 

# --- DRIVE İŞLEMLERİ ---
def get_drive_service(creds):
    return build('drive', 'v3', credentials=creds)

def get_or_create_folder(service, folder_name):
    """Senin Drive'ında klasör arar, yoksa yaratır."""
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    items = results.get('files', [])
    
    if items:
        return items[0]['id']
    else:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

def save_project(service, folder_id, project_data, project_name):
    """Projeyi kaydeder. Kota SENİN kotan olduğu için hata vermez."""
    file_name = f"{project_name}.json"
    
    # Eski dosyayı bul
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    items = results.get('files', [])
    
    json_bytes = json.dumps(project_data, ensure_ascii=False, indent=4).encode('utf-8')
    media = MediaIoBaseUpload(io.BytesIO(json_bytes), mimetype='application/json', resumable=True)
    
    if items:
        service.files().update(fileId=items[0]['id'], media_body=media).execute()
    else:
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        service.files().create(body=file_metadata, media_body=media).execute()

# --- STANDART FONKSİYONLAR ---
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

# --- UYGULAMA BAŞLANGICI ---
creds = authenticate_user()
srv = get_drive_service(creds)
ana_klasor_id = get_or_create_folder(srv, "CEVIRI_PROJELERI_OAUTH")

with st.sidebar:
    st.write(f"👤 Giriş Yapıldı")
    if st.button("Çıkış Yap"):
        del st.session_state.creds
        st.rerun()
    st.divider()
    api_key = st.text_input("Gemini API Key", type="password")

if "aktif_proje" not in st.session_state:
    st.session_state.aktif_proje = None

# --- EKRAN 1: LİSTE ---
if st.session_state.aktif_proje is None:
    st.title("📂 Projelerim (Kişisel Drive)")
    
    tabs = st.tabs(["Mevcut Projeler", "Yeni Proje"])
    
    with tabs[0]:
        q = f"'{ana_klasor_id}' in parents and mimeType = 'application/json' and trashed = false"
        results = srv.files().list(q=q, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if not files: st.info("Henüz proje yok.")
        
        for f in files:
            col1, col2 = st.columns([4, 1])
            if col1.button(f"📄 {f['name']}", key=f.get('id')):
                request = srv.files().get_media(fileId=f['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False: _, done = downloader.next_chunk()
                fh.seek(0)
                st.session_state.aktif_proje = json.load(fh)
                st.session_state.aktif_dosya_id = f['id']
                st.rerun()
            
            if col2.button("🗑️", key=f"del_{f['id']}"):
                srv.files().delete(fileId=f['id']).execute()
                st.success("Silindi")
                time.sleep(1)
                st.rerun()

    with tabs[1]:
        st.subheader("Yeni Proje")
        ad = st.text_input("Proje Adı")
        dosya = st.file_uploader("Metin Dosyası", type=['txt', 'docx', 'pdf'])
        
        if st.button("Oluştur") and ad and dosya:
            if dosya.name.endswith('.pdf'): txt = "".join([p.extract_text() for p in PdfReader(dosya).pages])
            elif dosya.name.endswith('.docx'): txt = "\n\n".join([p.text for p in Document(dosya).paragraphs])
            else: txt = dosya.read().decode('utf-8')
            
            data = {
                "meta": {"ad": ad, "tarih": str(datetime.now())},
                "paragraflar": paragraf_eslestir(metni_parcala(txt), [])
            }
            
            save_project(srv, ana_klasor_id, data, ad)
            st.success("Proje oluşturuldu!")
            time.sleep(1)
            st.rerun()

# --- EKRAN 2: EDİTÖR ---
else:
    proje = st.session_state.aktif_proje
    st.header(f"📝 {proje['meta']['ad']}")
    
    if st.button("🔙 Listeye Dön"):
        st.session_state.aktif_proje = None
        st.rerun()
        
    paragraflar = proje["paragraflar"]
    if "cursor" not in st.session_state: st.session_state.cursor = 0
    
    col_nav1, col_nav2 = st.columns(2)
    if col_nav1.button("⬅️"): st.session_state.cursor = max(0, st.session_state.cursor - 1)
    if col_nav2.button("➡️"): st.session_state.cursor = min(len(paragraflar)-1, st.session_state.cursor + 1)
    
    idx = st.session_state.cursor
    p = paragraflar[idx]
    
    col1, col2 = st.columns(2)
    col1.info(p['orjinal'])
    
    if not p['ceviri'] and api_key and st.button("🤖 Çevir"):
        with st.spinner("Çevriliyor..."):
            p['ceviri'] = ceviri_yap_gemini(p['orjinal'], api_key, "Sen profesyonel çevirmensin.")
            
    yeni_ceviri = col2.text_area("Çeviri", p['ceviri'], height=200)
    
    if col2.button("✅ Kaydet", type="primary"):
        p['ceviri'] = yeni_ceviri
        p['durum'] = "onaylandi"
        save_project(srv, ana_klasor_id, proje, proje['meta']['ad'])
        st.toast("Kaydedildi!")
