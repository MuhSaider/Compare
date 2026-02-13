import streamlit as st
import pandas as pd
import re
from io import StringIO

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="SAP Fast Reconcile", layout="wide")

# --- 2. CSS RAHASIA (MENGHILANGKAN NAVBAR & FOOTER) ---
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
    """
    Mengubah format angka Indonesia (Koma sebagai desimal) ke Python.
    Contoh: "93,2" -> 93.2 | "1.000" -> 1000
    """
    if isinstance(x, str):
        # Hapus titik (biasanya pemisah ribuan di Indo)
        x = x.replace('.', '')
        # Ganti koma jadi titik (desimal)
        x = x.replace(',', '.')
    return pd.to_numeric(x, errors='coerce')

def read_paste_data(text_input):
    if not text_input: return None
    try:
        return pd.read_csv(StringIO(text_input), sep='\t')
    except Exception: return None

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
    # Cari kata LINE diikuti angka 01-36
    match = re.search(r'LINE\s*(0[1-9]|[1-2][0-9]|3[0-6])\b', line_name.upper())
    return "BS Depan" if match else "BS Belakang"

# --- 4. JUDUL ---
st.title("⚡ SAP Reconcile: Auto Fix Format")
st.markdown("---")

# --- 5. AREA INPUT ---
tab1, tab2, tab3 = st.tabs(["1️⃣ Paste MB51 (Produksi)", "2️⃣ Paste OZPPR (Mapping)", "3️⃣ Paste Data Manual"])

with tab1:
    st.caption("Copy data SAP MB51 (Header: Material, Order/Reference, Qty)")
    txt_mb51 = st.text_area("Paste Data MB51:", height=200, key="mb51")

with tab2:
    st.caption("Copy data SAP OZPPR (Header: Order, Line/Work Center)")
    txt_mapping = st.text_area("Paste Data Mapping:", height=200, key="ozppr")

with tab3:
    st.caption("Copy data Manual (Baris=Line, Kolom=Material)")
    txt_manual = st.text_area("Paste Data Manual:", height=200, key="manual")

# --- 6. PROSES ---
if st.button("🚀 PROSES DATA SEKARANG", type="primary", use_container_width=True):
    
    if not txt_mb51 or not txt_mapping or not txt_manual:
        st.error("⚠️ Data belum lengkap!")
        st.stop()

    try:
        # BACA DATA
        df_mb51 = read_paste_data(txt_mb51)
        df_mapping = read_paste_data(txt_mapping)
        df_manual_raw = read_paste_data(txt_manual)

        # --- DETEKSI KOLOM ---
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

        # --- CLEANING DATA ---
        
        # Rename
        df_mb51 = df_mb51.rename(columns={col_mat: 'Material', col_io_a: 'IO', col_qty: 'Qty'})
        df_mapping = df_mapping.rename(columns={col_io_b: 'IO', col_line: 'Line'})

        # Format String
        df_mb51['Material'] = df_mb51['Material'].astype(str).str.strip()
        df_mb51['IO'] = df_mb51['IO'].astype(str).str.strip()
        df_mapping['IO'] = df_mapping['IO'].astype(str).str.strip()
        df_mapping['Line'] = df_mapping['Line'].astype(str).str.strip()

        # [FIX 1] Format Angka Indonesia (Handle Koma)
        df_mb51['Qty'] = df_mb51['Qty'].apply(clean_indo_number).fillna(0)

        # [FIX 2] Filter Material: Ambil awalan 40 ATAU 70
        # Kita gunakan regex tuple agar bisa multiple prefixes
        df_mb51_clean = df_mb51[df_mb51['Material'].str.startswith(('40', '70'))].copy()

        # Join Line
        df_merged = pd.merge(df_mb51_clean, df_mapping[['IO', 'Line']], on='IO', how='left')
        df_merged['Line'] = df_merged['Line'].fillna('Unknown Line')

        # Grouping SAP
        sap_grouped = df_merged.groupby(['Line', 'Material'])['Qty'].sum().reset_index()
        sap_grouped.rename(columns={'Qty': 'Qty_SAP'}, inplace=True)
        sap_grouped['Kategori'] = sap_grouped['Line'].apply(categorize_line)

        # --- MANUAL DATA PROCESSING ---
        df_manual_raw.rename(columns={df_manual_raw.columns[0]: 'Line'}, inplace=True)
        
        # Unpivot
        manual_long = pd.melt(df_manual_raw, id_vars=['Line'], var_name='Material', value_name='Qty_Manual')
        
        # [FIX 1] Format Angka Indonesia untuk Data Manual juga
        manual_long['Qty_Manual'] = manual_long['Qty_Manual'].apply(clean_indo_number).fillna(0)
        
        manual_long['Material'] = manual_long['Material'].astype(str).str.strip()
        manual_long['Line'] = manual_long['Line'].astype(str).str.strip()

        # Final Compare
        final_df = pd.merge(sap_grouped, manual_long, on=['Line', 'Material'], how='outer')
        final_df['Qty_SAP'] = final_df['Qty_SAP'].fillna(0)
        final_df['Qty_Manual'] = final_df['Qty_Manual'].fillna(0)
        final_df['Kategori'] = final_df['Kategori'].fillna(final_df['Line'].apply(categorize_line))
        final_df['Selisih'] = final_df['Qty_SAP'] - final_df['Qty_Manual']

        # Tampilan
        st.success("✅ Proses Selesai!")
        
        display_cols = ['Line', 'Kategori', 'Material', 'Qty_SAP', 'Qty_Manual', 'Selisih']
        df_show = final_df[display_cols].sort_values(by=['Kategori', 'Line', 'Material'])

        def color_diff(val):
            return 'color: red; font-weight: bold;' if abs(val) > 0.001 else 'color: green;'

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
