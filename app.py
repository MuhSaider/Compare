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

def process_duplicate_columns(df):
    """
    Fungsi Sakti: Menggabungkan kolom dengan nama kembar.
    Misal ada 5 kolom '700002', nilainya akan dijumlahkan jadi 1 kolom '700002'.
    """
    # 1. Ambil nama kolom pertama sebagai 'Line' (Kunci grouping)
    key_col = df.columns[0] 
    
    # 2. Transpose (Putar) data agar Kolom jadi Baris sementara
    # Ini trik paling aman untuk handle kolom kembar di Pandas
    df = df.set_index(key_col)
    
    # 3. Group by Index (Nama Kolom) dan Sum
    # Axis=1 artinya kita menjumlahkan ke samping (antar kolom)
    df_grouped = df.groupby(level=0, axis=1).sum()
    
    # 4. Kembalikan index 'Line' jadi kolom biasa
    df_grouped = df_grouped.reset_index()
    
    return df_grouped

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
st.title("⚡ SAP Reconcile: Auto Merge Columns")
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
    st.caption("Data Manual (Kolom Kembar akan otomatis dijumlahkan)")
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
        
        # BACA DATA MANUAL (KHUSUS)
        # Kita baca header saja dulu untuk cek duplikat
        # header=None agar pandas tidak bingung, nanti kita set sendiri
        raw_manual_io = StringIO(txt_manual)
        
        # Trik: Baca CSV apa adanya, kolom kembar akan otomatis diberi suffix .1, .2 oleh pandas
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
        df_mapping['Line'] = df_mapping['Line'].astype(str).str.strip()

        # Format Angka Indo & Filter Material (40/70)
        df_mb51['Qty'] = df_mb51['Qty'].apply(clean_indo_number).fillna(0)
        df_mb51_clean = df_mb51[df_mb51['Material'].str.startswith(('40', '70'))].copy()

        # Join Line & Grouping SAP
        df_merged = pd.merge(df_mb51_clean, df_mapping[['IO', 'Line']], on='IO', how='left')
        df_merged['Line'] = df_merged['Line'].fillna('Unknown Line')

        sap_grouped = df_merged.groupby(['Line', 'Material'])['Qty'].sum().reset_index()
        sap_grouped.rename(columns={'Qty': 'Qty_SAP'}, inplace=True)
        sap_grouped['Kategori'] = sap_grouped['Line'].apply(categorize_line)

        # --- CLEANING DATA MANUAL (THE MAGIC PART) ---
        
        # 1. Bersihkan Nama Kolom dari suffix (.1, .2) yg dibuat pandas
        # Contoh: "700002.1" -> "700002"
        clean_cols = []
        for col in df_manual_raw.columns:
            # Regex: Ambil nama depan sebelum titik jika formatnya "Nama.Angka"
            col_clean = re.sub(r'\.\d+$', '', col) 
            clean_cols.append(col_clean)
        
        df_manual_raw.columns = clean_cols # Pasang nama kolom baru yg kembar
        
        # 2. Cari kolom 'Line' (Biasanya di kolom ke-2 pada data Anda, setelah Tanggal)
        # Kita cari kolom yg mengandung kata 'Line'
        found_line_col = False
        for i, col in enumerate(df_manual_raw.columns):
            if 'line' in col.lower():
                # Ubah nama kolom ini jadi 'Line' yang baku
                cols = list(df_manual_raw.columns)
                cols[i] = 'Line'
                df_manual_raw.columns = cols
                found_line_col = True
                break
        
        if not found_line_col:
            # Jika tidak ketemu header 'Line', asumsi kolom ke-2 adalah Line (Sesuai contoh data Anda: TANGGAL, Line, ...)
            cols = list(df_manual_raw.columns)
            if len(cols) > 1:
                cols[1] = 'Line'
                df_manual_raw.columns = cols
            else:
                st.error("Gagal mendeteksi kolom Line di data manual.")
                st.stop()

        # 3. Set Index 'Line' lalu Bersihkan Angka
        # Kita buang kolom Tanggal/Lainnya yg tidak perlu, hanya ambil Line dan Material Angka
        df_manual_raw = df_manual_raw.set_index('Line')
        
        # Hapus kolom yg bukan angka/material (misal Tanggal)
        # Trik: Coba convert ke numerik, kalau error berarti bukan kolom data
        valid_data_cols = []
        for col in df_manual_raw.columns:
            # Cek apakah nama kolomnya berupa angka (Material) atau teks tertentu yg diinginkan
            # Disini kita ambil semua, nanti yg gagal convert jadi 0
            valid_data_cols.append(col)
            
        df_manual_numeric = df_manual_raw[valid_data_cols].applymap(clean_indo_number).fillna(0)

        # 4. SUM KOLOM KEMBAR (HORIZONTAL)
        # Ini langkah krusial: menjumlahkan 700002 + 700002 + 700002
        df_manual_grouped = df_manual_numeric.groupby(level=0, axis=1).sum()
        
        # Reset index agar 'Line' kembali jadi kolom
        df_manual_grouped = df_manual_grouped.reset_index()

        # 5. Unpivot (Wide to Long)
        manual_long = pd.melt(df_manual_grouped, id_vars=['Line'], var_name='Material', value_name='Qty_Manual')
        manual_long['Material'] = manual_long['Material'].astype(str).str.strip()
        manual_long['Line'] = manual_long['Line'].astype(str).str.strip()

        # --- FINAL MERGE ---
        final_df = pd.merge(sap_grouped, manual_long, on=['Line', 'Material'], how='outer')
        final_df['Qty_SAP'] = final_df['Qty_SAP'].fillna(0)
        final_df['Qty_Manual'] = final_df['Qty_Manual'].fillna(0)
        final_df['Kategori'] = final_df['Kategori'].fillna(final_df['Line'].apply(categorize_line))
        final_df['Selisih'] = final_df['Qty_SAP'] - final_df['Qty_Manual']

        # --- TAMPILAN ---
        st.success("✅ Sukses! Kolom kembar sudah dijumlahkan otomatis.")
        
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
        st.write("Cek format data manual Anda. Pastikan copy-paste rapi.")
