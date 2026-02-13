import streamlit as st
import pandas as pd
import re
from io import StringIO

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="SAP Data Reconciliation", layout="wide")

# --- FUNGSI HELPER ---

def find_column(df, keywords):
    """Mencari nama kolom berdasarkan kata kunci (case-insensitive)."""
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
    """Logika: LINE 01-36 = Depan, Lainnya = Belakang."""
    if not isinstance(line_name, str):
        return "BS Belakang"
    match = re.search(r'LINE\s*(0[1-9]|[1-2][0-9]|3[0-6])\b', line_name.upper())
    return "BS Depan" if match else "BS Belakang"

# --- SIDEBAR ---
st.sidebar.header("📂 Data Import")
uploaded_file_a = st.sidebar.file_uploader("1. Upload File MB51 (Produksi)", type=["xlsx", "xls"])
uploaded_file_b = st.sidebar.file_uploader("2. Upload File OZPPR (Mapping)", type=["xlsx", "xls"])

st.title("📊 Aplikasi Rekonsiliasi Data SAP (Copy-Paste)")
st.markdown("---")

# --- MAIN LOGIC ---
if uploaded_file_a and uploaded_file_b:
    try:
        # --- BAGIAN 1: PROSES DATA SAP (OTOMATIS) ---
        df_mb51 = pd.read_excel(uploaded_file_a)
        df_mapping = pd.read_excel(uploaded_file_b)

        # Deteksi Kolom
        col_mat = find_column(df_mb51, ['Material', 'Material Number', 'Matnr'])
        col_io_a = find_column(df_mb51, ['Order', 'IO', 'Process Order', 'Aufnr'])
        col_qty = find_column(df_mb51, ['Quantity', 'Qty', 'Menge'])
        
        col_io_b = find_column(df_mapping, ['Order', 'IO', 'Aufnr'])
        col_line = find_column(df_mapping, ['Line', 'Work Center'])

        # Validasi
        if not all([col_mat, col_io_a, col_qty, col_io_b, col_line]):
            st.error("Gagal mendeteksi kolom SAP. Pastikan header Excel benar.")
            st.stop()

        # Rename & Clean Up SAP
        df_mb51 = df_mb51.rename(columns={col_mat: 'Material', col_io_a: 'IO', col_qty: 'Qty'})
        df_mapping = df_mapping.rename(columns={col_io_b: 'IO', col_line: 'Line'})

        df_mb51['Material'] = df_mb51['Material'].astype(str).str.strip()
        df_mb51['IO'] = df_mb51['IO'].astype(str).str.strip()
        df_mb51['Qty'] = pd.to_numeric(df_mb51['Qty'], errors='coerce').fillna(0)
        df_mapping['IO'] = df_mapping['IO'].astype(str).str.strip()
        df_mapping['Line'] = df_mapping['Line'].astype(str).str.strip()

        # Filter Material '40'
        df_mb51_filtered = df_mb51[df_mb51['Material'].str.startswith('40')].copy()

        # Join MB51 + Mapping
        df_merged = pd.merge(df_mb51_filtered, df_mapping[['IO', 'Line']], on='IO', how='left')
        df_merged['Line'] = df_merged['Line'].fillna('Unknown Line')

        # Grouping (Total Qty SAP)
        sap_grouped = df_merged.groupby(['Line', 'Material'])['Qty'].sum().reset_index()
        sap_grouped.rename(columns={'Qty': 'Qty_SAP'}, inplace=True)
        sap_grouped['Kategori'] = sap_grouped['Line'].apply(categorize_line)

        # --- BAGIAN 2: INPUT MANUAL (COPY-PASTE) ---
        st.subheader("📝 Input Data Manual")
        st.info("Blok data di Excel Anda (termasuk Header Material & Nama Line) -> Copy -> Paste di bawah ini.")
        
        paste_data = st.text_area("Paste Data Excel di sini:", height=150)

        if paste_data:
            # Baca data Paste
            df_manual_raw = pd.read_csv(StringIO(paste_data), sep='\t')
            
            # Rename kolom pertama jadi 'Line'
            df_manual_raw.rename(columns={df_manual_raw.columns[0]: 'Line'}, inplace=True)
            
            # Unpivot (Melebarkan ke Memanjang)
            manual_long = pd.melt(df_manual_raw, id_vars=['Line'], var_name='Material', value_name='Qty_Manual')
            
            # Bersihkan Data Manual
            manual_long['Qty_Manual'] = pd.to_numeric(manual_long['Qty_Manual'], errors='coerce').fillna(0)
            manual_long['Material'] = manual_long['Material'].astype(str).str.strip()
            manual_long['Line'] = manual_long['Line'].astype(str).str.strip()

            # --- BAGIAN 3: COMPARE & RESULT ---
            if st.button("🚀 Proses Compare", type="primary"):
                # Join SAP vs Manual (Outer Join)
                final_df = pd.merge(sap_grouped, manual_long, on=['Line', 'Material'], how='outer')
                
                # Fill NaN & Hitung
                final_df['Qty_SAP'] = final_df['Qty_SAP'].fillna(0)
                final_df['Qty_Manual'] = final_df['Qty_Manual'].fillna(0)
                final_df['Kategori'] = final_df['Kategori'].fillna(final_df['Line'].apply(categorize_line))
                final_df['Selisih'] = final_df['Qty_SAP'] - final_df['Qty_Manual']

                # Tampilan Akhir
                final_cols = ['Line', 'Kategori', 'Material', 'Qty_SAP', 'Qty_Manual', 'Selisih']
                final_display = final_df[final_cols].sort_values(by=['Kategori', 'Line', 'Material'])

                st.subheader("✅ Hasil Rekonsiliasi")
                
                def highlight_diff(row):
                    return ['background-color: #ffcccc; color: black'] * len(row) if abs(row['Selisih']) > 0.001 else [''] * len(row)

                st.dataframe(
                    final_display.style.apply(highlight_diff, axis=1).format("{:,.2f}", subset=['Qty_SAP', 'Qty_Manual', 'Selisih']),
                    use_container_width=True,
                    height=600
                )
                
                diff_sum = final_display['Selisih'].sum()
                st.metric("Total Selisih Global", f"{diff_sum:,.2f}")

        else:
            st.warning("⚠️ Menunggu data Excel dipaste...")

    except Exception as e:
        st.error(f"Terjadi Kesalahan: {e}")

else:
    st.info("👈 Silakan upload file MB51 dan Mapping Line dulu.")
