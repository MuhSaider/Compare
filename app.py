import streamlit as st
import pandas as pd
import re
from io import StringIO, BytesIO

# ==============================
# 1. PAGE CONFIG
# ==============================
st.set_page_config(page_title="SAP Fast Reconcile", layout="wide")

# ==============================
# 2. HIDE STREAMLIT UI
# ==============================
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

# ==============================
# 3. HELPER FUNCTIONS
# ==============================

def clean_indo_number(x):
    if isinstance(x, str):
        x = x.replace('.', '')
        x = x.replace(',', '.')
    return pd.to_numeric(x, errors='coerce')

def read_paste_data(text_input):
    if not text_input:
        return None
    try:
        return pd.read_csv(StringIO(text_input), sep='\t')
    except:
        return None

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
    if not isinstance(line_name, str):
        return "BS Belakang"
    match = re.search(r'LINE\s*(0[1-9]|[1-2][0-9]|3[0-6])\b', line_name.upper())
    return "BS Depan" if match else "BS Belakang"

# ==============================
# 4. TITLE
# ==============================
st.title("⚡ SAP Reconcile - Production vs Timbangan")
st.markdown("---")

# ==============================
# 5. INPUT AREA
# ==============================
tab1, tab2, tab3 = st.tabs([
    "1️⃣ Paste MB51 (Produksi)",
    "2️⃣ Paste OZPPR (Mapping)",
    "3️⃣ Paste Data Manual"
])

with tab1:
    txt_mb51 = st.text_area("Paste Data MB51:", height=200)

with tab2:
    txt_mapping = st.text_area("Paste Data Mapping:", height=200)

with tab3:
    txt_manual = st.text_area("Paste Data Manual:", height=200)

# ==============================
# 6. PROCESS BUTTON
# ==============================
if st.button("🚀 PROSES DATA SEKARANG", type="primary", use_container_width=True):

    if not txt_mb51 or not txt_mapping or not txt_manual:
        st.error("⚠️ Semua data wajib diisi!")
        st.stop()

    try:

        # ======================================
        # PROCESS SAP
        # ======================================
        df_mb51 = read_paste_data(txt_mb51)
        df_mapping = read_paste_data(txt_mapping)

           # ======================================
        # DETEKSI KOLOM SESUAI HEADER KAMU
        # ======================================
        col_mat = find_column(df_mb51, [
        'Material'
        ])

        col_io = find_column(df_mb51, [
        'Order'
        ])

        col_qty = find_column(df_mb51, [
        'Qty'
        ])

        col_map_io = find_column(df_mapping, [
        'Order'
        ])

        col_line = find_column(df_mapping, [
        'Work Center'
        ])

        if not all([col_mat, col_io, col_qty, col_map_io, col_line]):
            st.error("Header SAP/Mapping tidak terdeteksi.")
            st.stop()

        df_mb51 = df_mb51.rename(columns={
            col_mat: 'Material',
            col_io: 'IO',
            col_qty: 'Qty'
        })

        df_mapping = df_mapping.rename(columns={
            col_map_io: 'IO',
            col_line: 'Line'
        })

        df_mb51['Qty'] = df_mb51['Qty'].apply(clean_indo_number).fillna(0)
        df_mb51['Material'] = df_mb51['Material'].astype(str).str.strip()

        df_merge = pd.merge(df_mb51, df_mapping[['IO','Line']], on='IO', how='left')
        df_merge['Line'] = df_merge['Line'].fillna("Unknown")

        sap_grouped = df_merge.groupby(['Material','Line'], as_index=False)['Qty'].sum()
        sap_grouped.rename(columns={'Qty':'QTY GR PRD'}, inplace=True)

        # ======================================
        # PROCESS MANUAL
        # ======================================
        df_manual = pd.read_csv(StringIO(txt_manual), sep='\t')

        df_manual.columns = [re.sub(r'\.\d+$','',c) for c in df_manual.columns]

        if 'Line' not in df_manual.columns:
            df_manual.columns.values[1] = 'Line'

        df_manual = df_manual.set_index('Line')
        df_manual = df_manual.applymap(clean_indo_number).fillna(0)

        df_manual = df_manual.groupby(level=0, axis=1).sum().reset_index()

        manual_long = pd.melt(
            df_manual,
            id_vars=['Line'],
            var_name='Material',
            value_name='Qty_Manual'
        )

        manual_grouped = manual_long.groupby(
            ['Material','Line'],
            as_index=False
        )['Qty_Manual'].sum()

        # ======================================
        # FINAL MERGE
        # ======================================
        final_df = pd.merge(
            sap_grouped,
            manual_grouped,
            on=['Material','Line'],
            how='outer'
        ).fillna(0)

        final_df['Kategori'] = final_df['Line'].apply(categorize_line)

        final_df['QTY POS TIMBANG ZONA DEPAN'] = final_df.apply(
            lambda x: x['Qty_Manual'] if x['Kategori']=='BS Depan' else 0, axis=1)

        final_df['QTY POS TIMBANG ZONA BELAKANG'] = final_df.apply(
            lambda x: x['Qty_Manual'] if x['Kategori']=='BS Belakang' else 0, axis=1)

        grouped = final_df.groupby(['Material','Line'],as_index=False).agg({
            'QTY GR PRD':'sum',
            'QTY POS TIMBANG ZONA DEPAN':'sum',
            'QTY POS TIMBANG ZONA BELAKANG':'sum'
        })

        grouped['TOTAL POST TIMBANG'] = (
            grouped['QTY POS TIMBANG ZONA DEPAN'] +
            grouped['QTY POS TIMBANG ZONA BELAKANG']
        )

        grouped['GR PRODUKSI'] = grouped['QTY GR PRD']
        grouped['SELISIH'] = grouped['GR PRODUKSI'] - grouped['TOTAL POST TIMBANG']

        grouped['Material Description'] = ''
        grouped['Reference'] = ''
        grouped['SKU'] = ''

        result = grouped[[
            'Material',
            'Material Description',
            'QTY GR PRD',
            'Reference',
            'Line',
            'SKU',
            'QTY POS TIMBANG ZONA DEPAN',
            'QTY POS TIMBANG ZONA BELAKANG',
            'TOTAL POST TIMBANG',
            'GR PRODUKSI',
            'SELISIH'
        ]]

        result = result[
            ~((result['QTY GR PRD']==0) &
              (result['TOTAL POST TIMBANG']==0))
        ]

        # ======================================
        # DISPLAY
        # ======================================
        st.success("✅ Reconcile Berhasil!")

        def highlight(val):
            return "color:red;font-weight:bold;" if abs(val)>0.001 else "color:green;"

        st.dataframe(
            result.style.applymap(highlight,subset=['SELISIH'])
            .format("{:,.2f}",subset=[
                'QTY GR PRD',
                'QTY POS TIMBANG ZONA DEPAN',
                'QTY POS TIMBANG ZONA BELAKANG',
                'TOTAL POST TIMBANG',
                'GR PRODUKSI',
                'SELISIH'
            ]),
            use_container_width=True,
            height=600
        )

        st.metric("Total Selisih Global",
                  f"{result['SELISIH'].sum():,.2f}")

        # ======================================
        # DOWNLOAD EXCEL
        # ======================================
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result.to_excel(writer, index=False)

        st.download_button(
            label="📥 Download Excel",
            data=output.getvalue(),
            file_name="SAP_Reconcile_Result.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"Terjadi kesalahan sistem: {e}")

