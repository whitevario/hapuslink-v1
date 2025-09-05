import streamlit as st
import io
import fitz  # PyMuPDF
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# -----------------------------
# Konfigurasi Google OAuth
# -----------------------------
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

client_config = {
    "web": {
        "client_id": st.secrets["google_oauth"]["client_id"],
        "project_id": st.secrets["google_oauth"]["project_id"],
        "auth_uri": st.secrets["google_oauth"]["auth_uri"],
        "token_uri": st.secrets["google_oauth"]["token_uri"],
        "client_secret": st.secrets["google_oauth"]["client_secret"],
        "redirect_uris": st.secrets["google_oauth"]["redirect_uris"],
    }
}

# Folder Shared Drive tujuan
PARENT_FOLDER_ID = "1H87XOKnCFfBPW70-YUwSCF5SdPldhzHd"

# Redirect URI Streamlit Cloud
REDIRECT_URI = "https://hapuslink.streamlit.app/"

st.set_page_config(page_title="Hapus Link Disposisi", page_icon="📝")
st.title("📝 Hapus Hyperlink 'Link Disposisi' dan Upload ke Shared Drive")

# -----------------------------
# Step 1: Autentikasi
# -----------------------------
if "credentials" not in st.session_state:
    st.session_state.credentials = None

query_params = st.experimental_get_query_params()
if "code" in query_params and st.session_state.credentials is None:
    code = query_params["code"][0]

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    flow.fetch_token(code=code)

    creds = flow.credentials
    st.session_state.credentials = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "id_token": creds.id_token,
        "scopes": creds.scopes,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri,
    }
    st.rerun()

if st.session_state.credentials is None:
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    st.markdown(f"👉 [Klik di sini untuk login Google]({auth_url})")
    st.stop()
else:
    creds = Credentials.from_authorized_user_info(st.session_state.credentials)
    st.success("✅ Sudah login ke Google Drive")

# -----------------------------
# Step 2: Upload File PDF
# -----------------------------
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "processed_files" not in st.session_state:
    st.session_state.processed_files = []

uploaded_files = st.file_uploader(
    "Upload file PDF",
    type="pdf",
    accept_multiple_files=True,
    key=st.session_state.uploader_key
)

# simpan uploaded_files ke session_state supaya bisa dihapus saat reset
st.session_state.uploaded_files = uploaded_files

if st.session_state.uploaded_files and st.session_state.credentials:
    creds = Credentials.from_authorized_user_info(st.session_state.credentials)
    service = build("drive", "v3", credentials=creds)

    success, not_found = 0, 0

    for uploaded_file in st.session_state.uploaded_files:
        if uploaded_file.name in st.session_state.processed_files:
            continue  # skip kalau sudah pernah diproses

        input_pdf = uploaded_file.read()
        doc = fitz.open(stream=input_pdf, filetype="pdf")
        deleted = False

        for page in doc:
            # cari teks "Link Disposisi" (case-insensitive)
            rects = page.search_for("Link Disposisi", quads=False)
            if rects:
                for rect in rects:
                    # hapus teks (isi area dengan putih)
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    page.apply_redactions()

                    # hapus link annotation di area itu
                    annots = page.annots()
                    if annots:
                        for annot in annots:
                            if rect.intersects(annot.rect):
                                page.delete_annot(annot)
                deleted = True

        # simpan hasil ke buffer
        output_buffer = io.BytesIO()
        doc.save(output_buffer)
        doc.close()
        output_buffer.seek(0)

        # upload ke Shared Drive
        file_metadata = {"name": uploaded_file.name, "parents": [PARENT_FOLDER_ID]}
        media = MediaIoBaseUpload(output_buffer, mimetype="application/pdf")
        service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True
        ).execute()

        if deleted:
            success += 1
            st.success(f"✅ {uploaded_file.name} → berhasil diproses & diupload ke Shared Drive")
        else:
            not_found += 1
            st.warning(f"⚠️ {uploaded_file.name} → teks 'Link Disposisi' tidak ditemukan (tetap diupload)")

        # tandai file sudah diproses
        st.session_state.processed_files.append(uploaded_file.name)

    st.markdown("### 📊 Ringkasan")
    st.markdown(f"- Total PDF diproses : **{len(st.session_state.uploaded_files)}**")
    st.markdown(f"- Berhasil dihapus   : **{success}**")
    st.markdown(f"- Dilewati (tidak ada): **{not_found}**")

    # contoh: auto-reset setelah selesai (seolah tombol diklik)
    # st.session_state.reset_trigger = True

# -----------------------------
# Step 3: Lihat daftar file di Shared Drive
# -----------------------------
if st.session_state.credentials:
    creds = Credentials.from_authorized_user_info(st.session_state.credentials)
    service = build("drive", "v3", credentials=creds)

    st.write("### 📂 File terbaru di Shared Drive")
    results = service.files().list(
        q=f"'{PARENT_FOLDER_ID}' in parents and mimeType='application/pdf' and trashed=false",
        orderBy="createdTime desc",
        pageSize=10,
        fields="files(id, name, webViewLink, createdTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    items = results.get("files", [])
    if not items:
        st.info("Belum ada file di folder ini.")
    else:
        for idx, file in enumerate(items, start=1):
            created_dt = datetime.fromisoformat(file['createdTime'].replace("Z", "+00:00"))
            local_dt = created_dt.astimezone(timezone(timedelta(hours=7)))
            formatted_date = local_dt.strftime("%d %b %Y, %H:%M")
            st.markdown(f"{idx}. 📄 [{file['name']}]({file['webViewLink']}) (dibuat {formatted_date})")

# -----------------------------
# Step 4: Reset Upload (manual atau otomatis)
# -----------------------------
if st.button("❌ Reset Upload"):
    st.session_state.reset_trigger = True

if st.session_state.get("reset_trigger", False):
    st.session_state.uploader_key += 1
    st.session_state.processed_files = []
    if "uploaded_files" in st.session_state:
        del st.session_state["uploaded_files"]
    st.session_state.reset_trigger = False
    st.rerun()