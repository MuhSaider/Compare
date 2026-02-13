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
st.title("⚡ SAP Reconcile: Auto Merge & Fix Duplicates")
st.markdown("---")

# --- 5. AREA INPUT ---
tab1, tab2, tab3 = st.tabs(["1️⃣ Paste MB51 (Produksi)", "2️⃣ Paste OZPPR (Mapping)", "3️⃣ Paste Data Manual"])

with tab1:
    st.caption("Header Wajib: Material, Order/Reference, Qty")
    txt_mb51 = st.text_area("Paste Data MB51:", height=200, key="mb51")

with tab2:
    st.caption("Header Wajib: Order, Line")
    txt_mapping = st.text_area("Paste Data Mapping:", height=200, key="ozppr")

with tab3:
    st.caption("Data Manual (Kolom & Baris kembar akan otomatis dijumlahkan)")
    txt_manual = st.text_area("Paste Data Manual:", height=200, key="manual")

# --- 6. PROSES ---
if st.button("🚀 PROSES DATA SEKARANG", type="primary", use_container_width=True):
    
    if not txt_mb51 or not txt_mapping or not txt_manual:
        st.error("⚠️ Data belum lengkap!")
        st.stop()

    try:
        # ==========================================
        # 1. PROSES DATA SAP (MB51 & MAPPING)
        # ==========================================
        df_mb51 = read_paste_data(txt_mb51)
        df_mapping = read_paste_data(txt_mapping)
        
        # Deteksi Kolom SAP
        col_mat = find_column(df_mb51, ['Material', 'Material Number'])
        col_io_a = find_column(df_mb51, ['Reference', 'Order', 'IO', 'Aufnr']) 
        col_qty = find_column(df_mb51, ['Quantity', 'Qty', 'Menge'])
        
        col_io_b = find_column(df_mapping, ['Order', 'IO', 'Reference'])
        col_line = find_column(df_mapping, ['Line', 'Work Center'])

        if not all([col_mat, col_io_a, col_qty, col_io_b, col_line]):
            st.error("Gagal mendeteksi kolom SAP/Mapping. Cek Header data Anda.")
            st.stop()

        # Rename & Clean SAP
        df_mb51 = df_mb51.rename(columns={col_mat: 'Material', col_io_a: 'IO', col_qty: 'Qty'})
        df_mapping = df_mapping.rename(columns={col_io_b: 'IO', col_line: 'Line'})

        df_mb51['Material'] = df_mb51['Material'].astype(str).str.strip()
        df_mb51['IO'] = df_mb51['IO'].astype(str).str.strip()
        df_mapping['IO'] = df_mapping['IO'].astype(str).str.strip()
        df_mapping['Line'] = df_mapping['Line'].astype(str).str.strip()

        # Filter & Convert
        df_mb51['Qty'] = df_mb51['Qty'].apply(clean_indo_number).fillna(0)
        df_mb51_clean = df_mb51[df_mb51['Material'].str.startswith(('40', '70'))].copy()

        # Join Line SAP
        df_merged = pd.merge(df_mb51_clean, df_mapping[['IO', 'Line']], on='IO', how='left')
        df_merged['Line'] = df_merged['Line'].fillna('Unknown Line')

        # Grouping SAP (Hasil Akhir Sisi Kiri)
        sap_grouped = df_merged.groupby(['Line', 'Material'])['Qty'].sum().reset_index()
        sap_grouped.rename(columns={'Qty': 'Qty_SAP'}, inplace=True)
        sap_grouped['Kategori'] = sap_grouped['Line'].apply(categorize_line)

        # ==========================================
        # 2. PROSES DATA MANUAL (FIXING BUG HERE)
        # ==========================================
        
        # Baca Raw Data Manual
        raw_manual_io = StringIO(txt_manual)
        df_manual_raw = pd.read_csv(raw_manual_io, sep='\t')

        # A. FIX NAMA KOLOM KEMBAR (Hapus suffix .1, .2)
        clean_cols = [re.sub(r'\.\d+$', '', c) for c in df_manual_raw.columns]
        df_manual_raw.columns = clean_cols
        
        # B. CARI KOLOM LINE
        found_line_col = False
        for i, col in enumerate(df_manual_raw.columns):
            if 'line' in col.lower():
                cols = list(df_manual_raw.columns)
                cols[i] = 'Line'
                df_manual_raw.columns = cols
                found_line_col = True
                break
        
        # Fallback jika tidak ada header 'Line', ambil kolom kedua
        if not found_line_col:
            cols = list(df_manual_raw.columns)
            if len(cols) > 1:
                cols[1] = 'Line'
                df_manual_raw.columns = cols
            else:
                st.error("Error: Kolom Line tidak ditemukan di data manual.")
                st.stop()

        # C. SET INDEX & BERSIHKAN ANGKA
        df_manual_raw = df_manual_raw.set_index('Line')
        
        # Konversi semua isi menjadi angka (kecuali index Line)
        # Kolom teks (misal Tanggal) akan jadi NaN -> 0
        df_manual_numeric = df_manual_raw.applymap(clean_indo_number).fillna(0)

        # D. PENJUMLAHAN HORIZONTAL (Kolom Kembar)
        # 700002 + 700002 (Kanan-Kiri)
        df_manual_grouped_cols = df_manual_numeric.groupby(level=0, axis=1).sum()
        df_manual_grouped_cols = df_manual_grouped_cols.reset_index()

        # E. UNPIVOT (WIDE TO LONG)
        manual_long = pd.melt(df_manual_grouped_cols, id_vars=['Line'], var_name='Material', value_name='Qty_Manual')
        
        manual_long['Material'] = manual_long['Material'].astype(str).str.strip()
        manual_long['Line'] = manual_long['Line'].astype(str).str.strip()

        # F. PENJUMLAHAN VERTIKAL (Baris Kembar) -> INI PERBAIKANNYA
        # Line 10 (Tgl 1) + Line 10 (Tgl 2) -> Total Line 10
        manual_final = manual_long.groupby(['Line', 'Material'], as_index=False)['Qty_Manual'].sum()

        # ==========================================
        # 3. FINAL MERGE & DISPLAY
        # ==========================================
        
        final_df = pd.merge(sap_grouped, manual_final, on=['Line', 'Material'], how='outer')
        
        # Isi NaN dengan 0
        final_df['Qty_SAP'] = final_df['Qty_SAP'].fillna(0)
        final_df['Qty_Manual'] = final_df['Qty_Manual'].fillna(0)
        
        # Isi Kategori yang kosong (karena data cuma ada di Manual)
        final_df['Kategori'] = final_df['Kategori'].fillna(final_df['Line'].apply(categorize_line))
        
        # Hitung Selisih
        final_df['Selisih'] = final_df['Qty_SAP'] - final_df['Qty_Manual']

        # TAMPILAN
        st.success("✅ Sukses! Data baris & kolom ganda sudah dirapikan.")
        
        display_cols = ['Line', 'Kategori', 'Material', 'Qty_SAP', 'Qty_Manual', 'Selisih']
        df_show = final_df[display_cols].sort_values(by=['Kategori', 'Line', 'Material'])

        def color_diff(val):
            # Merah jika selisih > 0.001 atau < -0.001 (bukan nol)
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
        st.error(f"Terjadi kesalahan sistem: {e}")
        st.write("Tips: Pastikan Header data manual tidak berantakan.")
