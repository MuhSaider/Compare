import streamlit as st
import pandas as pd
import re
from io import StringIO

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="SAP Fast Reconcile", layout="wide")

# --- 2. CSS RAHASIA ---
hide_streamlit_style = """
            <style>
            header {visibility: hidden;}
            [data-testid="stHeader"] {display: none;}
            footer {visibility: hidden;}
            #MainMenu {visibility: hidden;}
            .stDeployButton {display: none;}
            .block-container {padding-top: 1rem;}
            textarea {font-size: 12px !important; font-family: monospace;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- 3. FUNGSI HELPER ---

def clean_indo_number(x):
    """Format angka Indo (Koma) ke Python (Titik)"""
    if isinstance(x, str):
        x = x.replace('.', '') # Hapus pemisah ribuan
        x = x.replace(',', '.') # Ganti koma jadi titik
    return pd.to_numeric(x, errors='coerce')

def read_paste_data(text_input):
    if not text_input: return None
    try:
        return pd.read_csv(StringIO(text_input), sep='\t')
    except Exception: return None

def get_last_two_words(text):
    """Ambil 2 kata terakhir dari nama Line"""
    text = str(text).strip()
    words = text.split()
    if len(words) >= 2:
        return ' '.join(words[-2:]) 
    return text 

def find_column(df, keywords):
    df_cols = [c.lower().strip() for c in df.columns]
    for key in keywords:
        key_lower = key.lower()
        if key_lower in df_cols:
            return df.columns[df_cols.index(key_lower)]
        for col in df.columns:
            if key_lower in col.lower():
                return col
    return None

def categorize_line(line_name):
    if not isinstance(line_name, str): return "BS Belakang"
    match = re.search(r'LINE\s*(0[1-9]|[1-2][0-9]|3[0-6])\b', line_name.upper())
    return "BS Depan" if match else "BS Belakang"

# --- 4. JUDUL ---
st.title("⚡ SAP Reconcile: Final Precision Fix")
st.markdown("---")

# --- 5. AREA INPUT ---
tab1, tab2, tab3 = st.tabs(["1️⃣ Paste MB51 (Produksi)", "2️⃣ Paste OZPPR (Mapping)", "3️⃣ Paste Data Manual"])

with tab1:
    st.caption("Header Wajib: Material, Order/Reference, Qty")
    txt_mb51 = st.text_area("Paste Data MB51:", height=200, key="mb51")

with tab2:
    st.caption("Header Wajib: Order, Line (Isi Line boleh panjang, nanti dipotong otomatis)")
    txt_mapping = st.text_area("Paste Data Mapping:", height=200, key="ozppr")

with tab3:
    st.caption("Data Manual (Kolom Kembar akan otomatis dijumlahkan dengan BENAR)")
    txt_manual = st.text_area("Paste Data Manual:", height=200, key="manual")

# --- 6. PROSES ---
if st.button("🚀 PROSES DATA SEKARANG", type="primary", use_container_width=True):
    
    if not txt_mb51 or not txt_mapping or not txt_manual:
        st.error("⚠️ Data belum lengkap!")
        st.stop()

    try:
        # BACA DATA SAP NORMAL
        df_mb51 = read_paste_data(txt_mb51)
        df_mapping = read_paste_data(txt_mapping)
        
        # BACA DATA MANUAL
        raw_manual_io = StringIO(txt_manual)
        df_manual_raw = pd.read_csv(raw_manual_io, sep='\t')

        # --- DETEKSI KOLOM SAP ---
        col_mat = find_column(df_mb51, ['Material', 'Material Number'])
        col_io_a = find_column(df_mb51, ['Reference', 'Order', 'IO', 'Aufnr']) 
        col_qty = find_column(df_mb51, ['Quantity', 'Qty', 'Menge'])
        
        col_io_b = find_column(df_mapping, ['Order', 'IO', 'Reference'])
        col_line = find_column(df_mapping, ['Line', 'Work Center'])

        # Validasi
        missing = []
        if not col_mat: missing.append("Material (MB51)")
        if not col_io_a: missing.append("Reference/Order (MB51)")
        if not col_qty: missing.append("Qty (MB51)")
        if not col_io_b: missing.append("Order (Mapping)")
        if not col_line: missing.append("Line (Mapping)")

        if missing:
            st.error(f"Kolom hilang: {', '.join(missing)}")
            st.stop()

        # --- CLEANING DATA SAP ---
        df_mb51 = df_mb51.rename(columns={col_mat: 'Material', col_io_a: 'IO', col_qty: 'Qty'})
        df_mapping = df_mapping.rename(columns={col_io_b: 'IO', col_line: 'Line'})

        df_mb51['Material'] = df_mb51['Material'].astype(str).str.strip()
        df_mb51['IO'] = df_mb51['IO'].astype(str).str.strip()
        df_mapping['IO'] = df_mapping['IO'].astype(str).str.strip()
        
        # Clean Nama Line
        df_mapping['Line'] = df_mapping['Line'].apply(get_last_two_words)

        # Format Angka & Filter
        df_mb51['Qty'] = df_mb51['Qty'].apply(clean_indo_number).fillna(0)
        df_mb51_clean = df_mb51[df_mb51['Material'].str.startswith(('40', '70'))].copy()

        # Join & Grouping SAP
        df_merged = pd.merge(df_mb51_clean, df_mapping[['IO', 'Line']], on='IO', how='left')
        df_merged['Line'] = df_merged['Line'].fillna('Unknown Line')

        sap_grouped = df_merged.groupby(['Line', 'Material'])['Qty'].sum().reset_index()
        sap_grouped.rename(columns={'Qty': 'Qty_SAP'}, inplace=True)
        sap_grouped['Kategori'] = sap_grouped['Line'].apply(categorize_line)

        # --- CLEANING DATA MANUAL (PERBAIKAN LOGIKA DISINI) ---
        
        # 1. Cari Kolom Line dulu
        found_line_col = False
        for i, col in enumerate(df_manual_raw.columns):
            if 'line' in col.lower():
                cols = list(df_manual_raw.columns)
                cols[i] = 'Line'
                df_manual_raw.columns = cols
                found_line_col = True
                break
        
        if not found_line_col:
            cols = list(df_manual_raw.columns)
            if len(cols) > 1:
                cols[1] = 'Line'
                df_manual_raw.columns = cols
            else:
                st.error("Gagal mendeteksi kolom Line di data manual.")
                st.stop()

        # 2. Set Index Line
        df_manual_raw = df_manual_raw.set_index('Line')
        
        # 3. Siapkan "Kunci Grouping" (Membersihkan suffix .1, .2 TANPA rename dataframe dulu)
        # Ini mencegah duplikasi data saat selection
        group_keys = [re.sub(r'\.\d+$', '', col) for col in df_manual_raw.columns]
        
        # 4. Konversi ke Angka
        df_manual_numeric = df_manual_raw.applymap(clean_indo_number).fillna(0)
        
        # 5. Group by Keys (Jumlahkan kolom berdasarkan nama bersihnya)
        df_manual_grouped = df_manual_numeric.groupby(group_keys, axis=1).sum()
        
        # Reset Index
        df_manual_grouped = df_manual_grouped.reset_index()

        # 6. Unpivot
        manual_long = pd.melt(df_manual_grouped, id_vars=['Line'], var_name='Material', value_name='Qty_Manual')
        manual_long['Material'] = manual_long['Material'].astype(str).str.strip()
        manual_long['Line'] = manual_long['Line'].astype(str).str.strip()

        # --- FINAL MERGE ---
        final_df = pd.merge(sap_grouped, manual_long, on=['Line', 'Material'], how='outer')
        final_df['Qty_SAP'] = final_df['Qty_SAP'].fillna(0)
        final_df['Qty_Manual'] = final_df['Qty_Manual'].fillna(0)
        final_df['Kategori'] = final_df['Kategori'].fillna(final_df['Line'].apply(categorize_line))
        
        # Toleransi float (pembulatan 2 desimal agar 0.000001 tidak dianggap selisih)
        final_df['Qty_SAP'] = final_df['Qty_SAP'].round(3)
        final_df['Qty_Manual'] = final_df['Qty_Manual'].round(3)
        final_df['Selisih'] = final_df['Qty_SAP'] - final_df['Qty_Manual']

        # --- TAMPILAN ---
        st.success(f"✅ Sukses! Perhitungan kolom kembar sudah diperbaiki.")
        
        display_cols = ['Line', 'Kategori', 'Material', 'Qty_SAP', 'Qty_Manual', 'Selisih']
        df_show = final_df[display_cols].sort_values(by=['Kategori', 'Line', 'Material'])

        def color_diff(val):
            return 'color: red; font-weight: bold;' if abs(val) > 0.01 else 'color: green;'

        st.dataframe(
            df_show.style.applymap(color_diff, subset=['Selisih'])
            .format("{:,.2f}", subset=['Qty_SAP', 'Qty_Manual', 'Selisih']),
            use_container_width=True,
            height=600
        )

        total_selisih = df_show['Selisih'].sum()
        st.metric("Total Selisih Global", f"{total_selisih:,.2f}")

    except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
