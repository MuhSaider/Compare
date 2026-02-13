import streamlit as st
import pandas as pd
import re
from io import StringIO

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="SAP Fast Reconcile", layout="wide")
# --- HILANGKAN NAVBAR & FOOTER ---
hide_streamlit_style = """
            <style>
            /* Menghilangkan Header Atas (Navbar) */
            header {visibility: hidden;}
            [data-testid="stHeader"] {display: none;}
            
            /* Menghilangkan Footer Bawah */
            footer {visibility: hidden;}
            
            /* Menghilangkan Menu Hamburger (Garis Tiga) & Tombol Deploy */
            #MainMenu {visibility: hidden;}
            .stDeployButton {display: none;}
            
            /* Menyesuaikan padding atas agar tidak ada celah kosong */
            .block-container {
                padding-top: 0rem;
            }
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- CSS SEDERHANA AGAR TAMPILAN LEBIH LUAS ---
st.markdown("""
    <style>
        .block-container {padding-top: 1rem; padding-bottom: 0rem;}
        textarea {font-size: 12px !important; font-family: monospace;}
    </style>
""", unsafe_allow_html=True)

# --- FUNGSI HELPER ---
def read_paste_data(text_input):
    """Membaca text copy-paste dari Excel/SAP menjadi DataFrame"""
    if not text_input:
        return None
    try:
        # SAP biasanya dipisahkan oleh Tab (\t)
        return pd.read_csv(StringIO(text_input), sep='\t')
    except Exception:
        return None

def find_column(df, keywords):
    """Mencari nama kolom (Case Insensitive)"""
    df_cols = [c.lower().strip() for c in df.columns]
    for key in keywords:
        key_lower = key.lower()
        # Cek exact match
        if key_lower in df_cols:
            return df.columns[df_cols.index(key_lower)]
        # Cek partial match
        for col in df.columns:
            if key_lower in col.lower():
                return col
    return None

def categorize_line(line_name):
    """Logika: LINE 01-36 = BS Depan, Lainnya = BS Belakang"""
    if not isinstance(line_name, str):
        return "BS Belakang"
    # Cari kata LINE diikuti angka 01-36
    match = re.search(r'LINE\s*(0[1-9]|[1-2][0-9]|3[0-6])\b', line_name.upper())
    return "BS Depan" if match else "BS Belakang"

# --- JUDUL ---
st.title("⚡ SAP Reconcile: Full Copy-Paste")
st.markdown("---")

# --- AREA INPUT (MENGGUNAKAN TABS) ---
tab1, tab2, tab3 = st.tabs(["1️⃣ Paste MB51 (Produksi)", "2️⃣ Paste OZPPR (Mapping)", "3️⃣ Paste Data Manual"])

with tab1:
    st.caption("Copy data dari T-Code MB51 (Termasuk Header: Material, Order/IO, Qty)")
    txt_mb51 = st.text_area("Paste Data MB51 di sini:", height=200, key="mb51")

with tab2:
    st.caption("Copy data dari T-Code OZPPR0001 (Termasuk Header: Order/IO, Line)")
    txt_mapping = st.text_area("Paste Data Mapping di sini:", height=200, key="ozppr")

with tab3:
    st.caption("Copy data Manual Anda (Format: Kolom Line, Kolom Material...)")
    txt_manual = st.text_area("Paste Data Manual di sini:", height=200, key="manual")

# --- TOMBOL EKSEKUSI ---
if st.button("🚀 PROSES DATA SEKARANG", type="primary", use_container_width=True):
    
    # 1. CEK KETERSEDIAAN DATA
    if not txt_mb51 or not txt_mapping or not txt_manual:
        st.error("⚠️ Data belum lengkap! Pastikan ketiga kotak (MB51, Mapping, Manual) sudah diisi.")
        st.stop()

    try:
        # 2. BACA DATA DARI TEXT AREA
        df_mb51 = read_paste_data(txt_mb51)
        df_mapping = read_paste_data(txt_mapping)
        df_manual_raw = read_paste_data(txt_manual)

        # 3. DETEKSI KOLOM MB51 & MAPPING
        # Cari kolom MB51
        col_mat = find_column(df_mb51, ['Material', 'Material Number', 'Matnr'])
        col_io_a = find_column(df_mb51, ['Reference', 'Order', 'IO', 'Aufnr'])
        col_qty = find_column(df_mb51, ['Quantity', 'Qty', 'Menge'])
        
        # Cari kolom Mapping
        col_io_b = find_column(df_mapping, ['Order', 'IO', 'Aufnr'])
        col_line = find_column(df_mapping, ['Line', 'Work Center'])

        # Validasi Header
        missing = []
        if not col_mat: missing.append("Material (MB51)")
        if not col_io_a: missing.append("Order/IO (MB51)")
        if not col_qty: missing.append("Qty (MB51)")
        if not col_io_b: missing.append("Order/IO (Mapping)")
        if not col_line: missing.append("Line (Mapping)")

        if missing:
            st.error(f"Gagal mendeteksi kolom: {', '.join(missing)}. Pastikan Anda meng-copy Header kolomnya juga.")
            st.stop()

        # 4. DATA CLEANING & PREPARATION
        
        # Rename kolom ke standar
        df_mb51 = df_mb51.rename(columns={col_mat: 'Material', col_io_a: 'IO', col_qty: 'Qty'})
        df_mapping = df_mapping.rename(columns={col_io_b: 'IO', col_line: 'Line'})

        # Format Text & Angka
        df_mb51['Material'] = df_mb51['Material'].astype(str).str.strip()
        df_mb51['IO'] = df_mb51['IO'].astype(str).str.strip()
        # Handle angka (ribuan koma/titik bisa tricky, kita asumsi standar format komputer)
        df_mb51['Qty'] = pd.to_numeric(df_mb51['Qty'], errors='coerce').fillna(0)
        
        df_mapping['IO'] = df_mapping['IO'].astype(str).str.strip()
        df_mapping['Line'] = df_mapping['Line'].astype(str).str.strip()

        # --- LOGIKA 1: FILTER MATERIAL '40' ---
        # Hanya ambil yang depannya '40'
        df_mb51_clean = df_mb51[df_mb51['Material'].str.startswith('40')].copy()

        # --- LOGIKA 2: JOIN LINE ---
        df_merged = pd.merge(df_mb51_clean, df_mapping[['IO', 'Line']], on='IO', how='left')
        df_merged['Line'] = df_merged['Line'].fillna('Unknown Line')

        # --- LOGIKA 3: GROUPING SAP ---
        sap_grouped = df_merged.groupby(['Line', 'Material'])['Qty'].sum().reset_index()
        sap_grouped.rename(columns={'Qty': 'Qty_SAP'}, inplace=True)
        
        # Tambah Kategori (Depan/Belakang)
        sap_grouped['Kategori'] = sap_grouped['Line'].apply(categorize_line)

        # 5. DATA MANUAL PROCESSING
        # Rename kolom pertama di data manual jadi 'Line' apapun namanya
        df_manual_raw.rename(columns={df_manual_raw.columns[0]: 'Line'}, inplace=True)
        
        # Unpivot Data Manual
        manual_long = pd.melt(df_manual_raw, id_vars=['Line'], var_name='Material', value_name='Qty_Manual')
        manual_long['Qty_Manual'] = pd.to_numeric(manual_long['Qty_Manual'], errors='coerce').fillna(0)
        manual_long['Material'] = manual_long['Material'].astype(str).str.strip()
        manual_long['Line'] = manual_long['Line'].astype(str).str.strip()

        # 6. FINAL COMPARE
        final_df = pd.merge(sap_grouped, manual_long, on=['Line', 'Material'], how='outer')
        
        # Isi Kosong dengan 0
        final_df['Qty_SAP'] = final_df['Qty_SAP'].fillna(0)
        final_df['Qty_Manual'] = final_df['Qty_Manual'].fillna(0)
        
        # Isi Kategori yg hilang karena outer join
        final_df['Kategori'] = final_df['Kategori'].fillna(final_df['Line'].apply(categorize_line))
        
        # Hitung Selisih
        final_df['Selisih'] = final_df['Qty_SAP'] - final_df['Qty_Manual']

        # 7. TAMPILKAN HASIL
        st.success("✅ Proses Selesai!")
        
        # Urutkan: Kategori -> Line -> Material
        display_cols = ['Line', 'Kategori', 'Material', 'Qty_SAP', 'Qty_Manual', 'Selisih']
        df_show = final_df[display_cols].sort_values(by=['Kategori', 'Line', 'Material'])

        # Style Warna (Merah jika selisih != 0)
        def color_diff(val):
            return 'color: red; font-weight: bold;' if abs(val) > 0.001 else 'color: green;'

        # Tampilkan Tabel
        st.dataframe(
            df_show.style.applymap(color_diff, subset=['Selisih'])
            .format("{:,.2f}", subset=['Qty_SAP', 'Qty_Manual', 'Selisih']),
            use_container_width=True,
            height=600
        )

        # Summary
        total_selisih = df_show['Selisih'].sum()
        st.metric("Total Selisih Global", f"{total_selisih:,.2f}")

    except Exception as e:
        st.error(f"Terjadi kesalahan saat memproses data: {e}")
        st.warning("Tips: Pastikan saat copy dari SAP, header kolom ikut terbawa.")
