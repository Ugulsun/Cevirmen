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
    query = "name = '-CEVIRI PROJELERI' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    try:
        results = service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = results.get('files', [])
        if not items:
            st.error("❌ Google Drive'da '-CEVIRI PROJELERI' klasörü bulunamadı!")
            st.stop()
        return items[0]['id']
    except HttpError as e:
        st.error(f"Klasör Hatası: {e}")
        st.stop()

# --- KRİTİK DEĞİŞİKLİK: GOOGLE DOCS OLARAK KAYDETME ---
def save_project_to_drive(service, folder_id, project_data, project_name):
    """
    KOTA HİLESİ: Veriyi JSON dosyası yerine Google Doc olarak kaydeder.
    Google Docs kota (storage) harcamaz, bu yüzden 'Service Account' hata vermez.
    """
    # 1. Eski veriyi bul ve sil (Docs güncellenemez, silinip yeniden yazılır)
    query = f"name = 'project_db' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    items = results.get('files', [])
    
    # Eskisini temizle
    if items:
        for item in items:
            try:
                service.files().delete(fileId=item['id'], supportsAllDrives=True).execute()
            except: pass # Zaten silinmişse geç
            
    # 2. Veriyi Hazırla
    json_str = json.dumps(project_data, ensure_ascii=False, indent=4)
    media = MediaIoBaseUpload(io.BytesIO(json_str.encode('utf-8')), mimetype='text/plain', resumable=True)
    
    # 3. Google Doc Olarak Yarat (mimeType hilesi)
    file_metadata = {
        'name': 'project_db',
        'mimeType': 'application/vnd.google-apps.document', # <--- BU SATIR KOTAYI ATLATIR
        'parents': [folder_id]
    }
    
    service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()

def load_project_from_drive(service, folder_id):
    """Google Doc içindeki veriyi okur."""
    try:
        query = f"name = 'project_db' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items = results.get('files', [])
        
        if not items: return None
        
        # Doc'u text olarak indir (export)
        request = service.files().export_media(fileId=items[0]['id'], mimeType='text/plain')
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        
        # Text'i JSON'a çevir
        fh.seek(0)
        return json.load(fh)
    except Exception as e:
        st.error(f"Veri Okuma Hatası: {e}")
        return None

def delete_project_folder(service, folder_id):
    """Klasörü siler."""
    try:
        service.files().delete(fileId=folder_id, supportsAllDrives=True).execute()
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
        st.error(f"Ad Değiştirme Hatası: {e}")
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
    if st.button("🚪 Projeleri Listele"):
        st.session_state.aktif_proje = None
        st.rerun()

# --- EKRAN 1: PROJE LİSTESİ ---
if st.session_state.aktif_proje is None:
    st.title("📂 Projelerim")
    
    tabs = st.tabs(["Mevcut Projeler", "Yeni Proje Oluştur"])
    
    with tabs[0]:
        # Klasörleri listele
        results = srv.files().list(q=f"'{ana_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                                   fields="files(id, name, createdTime)", orderBy="createdTime desc", 
                                   supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        projeler = results.get('files', [])
        
        if not projeler:
            st.info("Henüz proje yok.")
        
        for p in projeler:
            with st.container(border=True):
                col_ad, col_islem = st.columns([5, 1])
                
                # Projeye Tıkla Aç
                if col_ad.button(f"📂 {p['name']}", key=f"open_{p['id']}", use_container_width=True):
                    with st.spinner("Yükleniyor..."):
                        data = load_project_from_drive(srv, p['id'])
                        if data:
                            st.session_state.aktif_proje = data
                            st.session_state.aktif_folder_id = p['id']
                            st.rerun()
                        else:
                            st.error("Veri dosyası bulunamadı. Proje bozuk olabilir.")

                # Sil / Düzenle Menüsü
                with col_islem:
                    with st.popover("⚙️"):
                        yeni_ad = st.text_input("Yeni Ad", value=p['name'], key=f"ren_txt_{p['id']}")
                        if st.button("Kaydet", key=f"save_ren_{p['id']}"):
                            rename_project_folder(srv, p['id'], yeni_ad)
                            st.success("Ad Değişti!")
                            time.sleep(1)
                            st.rerun()
                        
                        st.divider()
                        if st.button("🗑️ Sil", key=f"del_btn_{p['id']}", type="primary"):
                            delete_project_folder(srv, p['id'])
                            st.success("Silindi.")
                            time.sleep(1)
                            st.rerun()

    with tabs[1]:
        st.subheader("Yeni Proje")
        proje_adi = st.text_input("Proje Adı")
        dosya_orj = st.file_uploader("1. Orijinal Metin", type=['txt', 'docx', 'pdf'])
        dosya_cev = st.file_uploader("2. Yarım Çeviri (Opsiyonel)", type=['txt', 'docx', 'pdf'])
        
        if st.button("Projeyi Oluştur") and proje_adi and dosya_orj:
            with st.spinner("Oluşturuluyor..."):
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
                
                # Klasör Yarat
                folder_meta = {
                    'name': proje_adi,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [ana_folder_id]
                }
                folder = srv.files().create(body=folder_meta, fields='id', supportsAllDrives=True).execute()
                yeni_id = folder.get('id')
                
                # Dosyayı "Google Doc" olarak kaydet (Kota Harcamaz)
                save_project_to_drive(srv, yeni_id, project_data, proje_adi)
                
                st.success("Oluşturuldu!")
                time.sleep(1)
                st.session_state.aktif_proje = project_data
                st.session_state.aktif_folder_id = yeni_id
                st.rerun()

# --- EKRAN 2: EDİTÖR ---
else:
    proje = st.session_state.aktif_proje
    folder_id = st.session_state.aktif_folder_id
    paragraflar = proje["paragraflar"]
    
    st.markdown(f"## 📝 {proje['meta']['ad']}")
    
    toplam = len(paragraflar)
    biten = len([p for p in paragraflar if p['durum'] == 'onaylandi'])
    st.progress(biten/toplam, text=f"Durum: {biten}/{toplam}")
    
    if "cursor" not in st.session_state:
        st.session_state.cursor = next((i for i, p in enumerate(paragraflar) if p['durum'] == 'bekliyor'), 0)

    # Navigasyon
    c1, c2, c3, c4 = st.columns([1, 1, 3, 1])
    if c1.button("⬅️ Geri"): st.session_state.cursor = max(0, st.session_state.cursor - 1)
    if c2.button("İleri ➡️"): st.session_state.cursor = min(toplam - 1, st.session_state.cursor + 1)
    
    hedef = c3.number_input("Git", 1, toplam, st.session_state.cursor + 1, label_visibility="collapsed") - 1
    if hedef != st.session_state.cursor:
        st.session_state.cursor = hedef
        st.rerun()
        
    if c4.button("⏭️ Boşa Git"):
        st.session_state.cursor = next((i for i, p in enumerate(paragraflar) if p['durum'] == 'bekliyor'), st.session_state.cursor)
        st.rerun()

    # Editör
    idx = st.session_state.cursor
    current_p = paragraflar[idx]
    
    st.divider()
    col_sol, col_sag = st.columns(2)
    
    with col_sol:
        st.caption(f"Orijinal ({idx+1})")
        st.info(current_p['orjinal'])
    
    with col_sag:
        st.caption("Çeviri")
        if not current_p['ceviri'] and api_key:
            with st.spinner("🤖 Çevriliyor..."):
                current_p['ceviri'] = ceviri_yap_gemini(current_p['orjinal'], api_key, "Sen profesyonel çevirmensin.")
        
        yeni_metin = st.text_area("Editör", value=current_p['ceviri'], height=200, label_visibility="collapsed")
        
        if st.button("✅ Onayla", type="primary", use_container_width=True):
            current_p['ceviri'] = yeni_metin
            current_p['durum'] = 'onaylandi'
            
            # Kaydet (Google Doc Güncelle)
            save_project_to_drive(srv, folder_id, proje, proje['meta']['ad'])
            
            if idx < toplam - 1: st.session_state.cursor += 1
            st.toast("Kaydedildi!")
            st.rerun()
            
    st.divider()
    if st.button("📥 Word İndir"):
        doc = Document()
        doc.add_heading(proje['meta']['ad'], 0)
        for p in paragraflar:
            if p['durum'] == 'onaylandi': doc.add_paragraph(p['ceviri'])
            else: doc.add_paragraph("--- ÇEVRİLMEDİ ---")
        bio = io.BytesIO()
        doc.save(bio)
        st.download_button("Dosyayı İndir", bio.getvalue(), f"{proje['meta']['ad']}.docx")
