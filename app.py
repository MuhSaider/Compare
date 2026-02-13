import streamlit as st
import pandas as pd
import re

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="SAP Data Reconciliation", layout="wide")

# --- FUNGSI HELPER (FLEXIBILITY) ---

def clean_currency(x):
    """Membersihkan format angka jika ada (comma/dot issue)."""
    if isinstance(x, str):
        x = x.replace(',', '').replace('.', '') # Sesuaikan dengan locale jika perlu
        try:
            return float(x)
        except:
            return 0.0
    return x

def find_column(df, keywords):
    """
    Mencari nama kolom asli di DataFrame berdasarkan daftar kata kunci.
    Case-insensitive dan partial match yang cerdas.
    """
    df_cols = [c.lower().strip() for c in df.columns]
    
    for key in keywords:
        key_lower = key.lower()
        # 1. Cek Exact Match (prioritas)
        if key_lower in df_cols:
            return df.columns[df_cols.index(key_lower)]
        
        # 2. Cek Partial Match (jika 'Qty' ada di 'Total Qty')
        # Kita cari yang paling mendekati
        for col in df.columns:
            if key_lower in col.lower():
                return col
    return None

def categorize_line(line_name):
    """
    Logika: LINE 01 s/d LINE 36 = BS Depan, Sisanya = BS Belakang.
    """
    if not isinstance(line_name, str):
        return "BS Belakang"
    
    line_upper = line_name.upper()
    
    # Regex untuk menangkap LINE diikuti angka 01-36
    # \s* mengizinkan spasi berapapun (LINE01 atau LINE 01)
    match = re.search(r'LINE\s*(0[1-9]|[1-2][0-9]|3[0-6])\b', line_upper)
    
    if match:
        return "BS Depan"
    else:
        return "BS Belakang"

# --- SIDEBAR: UPLOAD FILE ---
st.sidebar.header("📂 Data Import")
uploaded_file_a = st.sidebar.file_uploader("Upload File A (MB51 - Data Produksi)", type=["xlsx", "xls"])
uploaded_file_b = st.sidebar.file_uploader("Upload File B (OZPPR0001 - Mapping)", type=["xlsx", "xls"])

st.title("📊 Aplikasi Rekonsiliasi Data SAP")
st.markdown("---")

# --- MAIN LOGIC ---

if uploaded_file_a and uploaded_file_b:
    try:
        # 1. LOAD DATA
        df_mb51 = pd.read_excel(uploaded_file_a)
        df_mapping = pd.read_excel(uploaded_file_b)

        # 2. DETEKSI KOLOM OTOMATIS
        col_map_a = {
            'material': find_column(df_mb51, ['Material', 'Material Number', 'Matnr']),
            'desc': find_column(df_mb51, ['Material Description', 'Description', 'Mat. Desc']),
            'io': find_column(df_mb51, ['Order', 'IO', 'Process Order', 'Aufnr']),
            'qty': find_column(df_mb51, ['Quantity', 'Qty', 'Menge', 'Qty in Un. of Entry'])
        }

        col_map_b = {
            'io': find_column(df_mapping, ['Order', 'IO', 'Process Order', 'Aufnr']),
            'line': find_column(df_mapping, ['Line', 'Work Center', 'Production Line'])
        }

        # Validasi Kolom Ditemukan
        missing_cols = [k for k, v in col_map_a.items() if v is None] + \
                       [k for k, v in col_map_b.items() if v is None]
        
        if missing_cols:
            st.error(f"Kolom berikut tidak ditemukan (cek header Excel anda): {', '.join(missing_cols)}")
            st.stop()

        # 3. PRE-PROCESSING & FILTERING (BACKEND)
        
        # Standardisasi Nama Kolom Sementara untuk kemudahan coding
        df_mb51 = df_mb51.rename(columns={
            col_map_a['material']: 'Material',
            col_map_a['io']: 'IO',
            col_map_a['qty']: 'Qty'
        })
        
        df_mapping = df_mapping.rename(columns={
            col_map_b['io']: 'IO',
            col_map_b['line']: 'Line'
        })

        # Pastikan format data benar
        df_mb51['Material'] = df_mb51['Material'].astype(str).str.strip()
        df_mb51['IO'] = df_mb51['IO'].astype(str).str.strip()
        df_mapping['IO'] = df_mapping['IO'].astype(str).str.strip()
        df_mapping['Line'] = df_mapping['Line'].astype(str).str.strip()
        
        # Bersihkan Qty dari NaN
        df_mb51['Qty'] = pd.to_numeric(df_mb51['Qty'], errors='coerce').fillna(0)

        # --- LANGKAH 1: Filter Material '40' ---
        # Mengambil hanya yang berawalan '40'
        df_mb51_filtered = df_mb51[df_mb51['Material'].str.startswith('40')].copy()
        
        dropped_count = len(df_mb51) - len(df_mb51_filtered)
        if dropped_count > 0:
            st.info(f"ℹ️ Filter aktif: {dropped_count} baris dibuang karena Material tidak berawalan '40'.")

        # --- LANGKAH 2: Left Join dengan Mapping ---
        # Merge MB51 dengan Mapping berdasarkan IO
        df_merged = pd.merge(df_mb51_filtered, df_mapping[['IO', 'Line']], on='IO', how='left')

        # Handle jika ada IO yang tidak punya Line (Isi 'Unknown')
        df_merged['Line'] = df_merged['Line'].fillna('Unknown Line')

        # --- LANGKAH 3: Grouping & Sum ---
        sap_grouped = df_merged.groupby(['Line', 'Material'])['Qty'].sum().reset_index()
        sap_grouped.rename(columns={'Qty': 'Qty_SAP'}, inplace=True)

        # --- LANGKAH 4: Kategorisasi Line ---
        sap_grouped['Kategori'] = sap_grouped['Line'].apply(categorize_line)

        # --- FRONTEND: INPUT MANUAL ---
        st.subheader("📝 Input Data Manual (Data Supporting)")
        st.caption("Silakan copy-paste data manual anda di sini. Tabel ini otomatis mendeteksi Line dan Material dari data SAP untuk memudahkan.")

        # Membuat Template Pivot untuk Editor
        # Baris = Line, Kolom = Material
        # Kita gunakan outer join logic agar semua material/line dari SAP muncul sebagai kerangka
        pivot_template = sap_grouped.pivot(index='Line', columns='Material', values='Qty_SAP')
        # Kosongkan nilainya agar user mengisi manual (atau bisa kita set 0)
        pivot_template[:] = 0 
        
        # Widget Editor
        edited_df = st.data_editor(
            pivot_template.reset_index(), 
            num_rows="dynamic", 
            use_container_width=True,
            hide_index=True
        )

        # --- TOMBOL PROSES ---
        if st.button("🚀 Proses Compare", type="primary"):
            
            # 1. Transformasi Data Manual (Wide to Long)
            # User input adalah tabel lebar (kolom material), kita jadikan baris
            manual_long = pd.melt(
                edited_df, 
                id_vars=['Line'], 
                var_name='Material', 
                value_name='Qty_Manual'
            )
            
            # Pastikan numerik
            manual_long['Qty_Manual'] = pd.to_numeric(manual_long['Qty_Manual'], errors='coerce').fillna(0)
            manual_long['Material'] = manual_long['Material'].astype(str)
            manual_long['Line'] = manual_long['Line'].astype(str)

            # 2. Join Data SAP vs Manual
            # Gunakan outer join agar jika ada di manual tapi tidak ada di SAP (atau sebaliknya) tetap muncul
            final_df = pd.merge(
                sap_grouped, 
                manual_long, 
                on=['Line', 'Material'], 
                how='outer'
            )

            # Isi NaN dengan 0 dan hitung selisih
            final_df['Qty_SAP'] = final_df['Qty_SAP'].fillna(0)
            final_df['Qty_Manual'] = final_df['Qty_Manual'].fillna(0)
            
            # Isi ulang Kategori jika hilang karena Outer Join (data cuma ada di manual)
            final_df['Kategori'] = final_df['Kategori'].fillna(final_df['Line'].apply(categorize_line))
            
            # --- RUMUS SELISIH ---
            final_df['Selisih'] = final_df['Qty_SAP'] - final_df['Qty_Manual']

            # Urutkan kolom
            final_cols = ['Line', 'Kategori', 'Material', 'Qty_SAP', 'Qty_Manual', 'Selisih']
            final_display = final_df[final_cols].sort_values(by=['Kategori', 'Line', 'Material'])

            # --- TAMPILAN HASIL & CONDITIONAL FORMATTING ---
            st.subheader("✅ Hasil Rekonsiliasi")
            
            # Fungsi untuk mewarnai baris
            def highlight_diff(row):
                # Warna Merah Muda jika selisih != 0 (gunakan toleransi kecil untuk float)
                if abs(row['Selisih']) > 0.001: 
                    return ['background-color: #ffcccc; color: black'] * len(row)
                else:
                    return [''] * len(row)

            # Tampilkan dataframe dengan style
            st.dataframe(
                final_display.style.apply(highlight_diff, axis=1)
                .format("{:,.2f}", subset=['Qty_SAP', 'Qty_Manual', 'Selisih']),
                use_container_width=True,
                height=600
            )
            
            # Summary Metrics
            total_diff = final_display['Selisih'].sum()
            col1, col2 = st.columns(2)
            col1.metric("Total Selisih Global", f"{total_diff:,.2f}")
            if total_diff == 0:
                col2.success("Status: MATCH (Data Valid)")
            else:
                col2.warning("Status: UNMATCH (Terdapat Selisih)")

    except Exception as e:
        st.error(f"Terjadi Kesalahan: {e}")
        st.write("Detail Error (untuk debugging):")
        st.exception(e)

else:
    st.info("👈 Silakan upload file MB51 dan Mapping Line di sidebar untuk memulai.")



        # --- FRONTEND: INPUT MANUAL (REVISI: PASTE BEBAS) ---
        st.subheader("📝 Input Data Manual (Paste dari Excel)")
        st.info("Cara Pakai: Blok data di Excel Anda (termasuk Header Material & Nama Line) -> Copy -> Paste di bawah ini.")

        # 1. Kotak untuk Paste
        paste_data = st.text_area("Paste Data Excel di sini:", height=200, placeholder="Contoh:\nLine\t40001\t40002\nLine 01\t100\t50...")

        if paste_data:
            # 2. Konversi Teks Paste menjadi Data Frame
            from io import StringIO
            try:
                # Excel saat di-copy menjadi format "Tab Separated Values" (sep='\t')
                df_manual_raw = pd.read_csv(StringIO(paste_data), sep='\t')
                
                # Asumsi: Kolom pertama adalah Line, Kolom sisanya adalah Material
                # Kita ubah nama kolom pertama jadi 'Line' agar aman
                first_col = df_manual_raw.columns[0]
                df_manual_raw.rename(columns={first_col: 'Line'}, inplace=True)

                # Tampilkan preview agar user yakin datanya benar
                with st.expander("Klik untuk cek hasil bacaan data manual"):
                    st.dataframe(df_manual_raw)

                # 3. Transformasi (Unpivot) Data Manual
                # Mengubah tabel lebar (banyak kolom material) menjadi tabel panjang (Line | Material | Qty)
                manual_long = pd.melt(
                    df_manual_raw, 
                    id_vars=['Line'], 
                    var_name='Material', 
                    value_name='Qty_Manual'
                )

                # Bersihkan data (hapus koma/titik jika ada, pastikan angka)
                manual_long['Qty_Manual'] = pd.to_numeric(manual_long['Qty_Manual'], errors='coerce').fillna(0)
                
                # Pastikan format teks sama dengan SAP
                manual_long['Material'] = manual_long['Material'].astype(str).str.strip()
                manual_long['Line'] = manual_long['Line'].astype(str).str.strip()

                # --- LANJUT KE PROSES COMPARE (LOGIKA SAMA SEPERTI SEBELUMNYA) ---
                
                if st.button("🚀 Proses Compare", type="primary"):
                    
                    # Join Data SAP vs Manual
                    final_df = pd.merge(
                        sap_grouped, 
                        manual_long, 
                        on=['Line', 'Material'], 
                        how='outer'
                    )

                    # Isi NaN dengan 0
                    final_df['Qty_SAP'] = final_df['Qty_SAP'].fillna(0)
                    final_df['Qty_Manual'] = final_df['Qty_Manual'].fillna(0)
                    
                    # Kategori Line
                    final_df['Kategori'] = final_df['Kategori'].fillna(final_df['Line'].apply(categorize_line))
                    
                    # Hitung Selisih
                    final_df['Selisih'] = final_df['Qty_SAP'] - final_df['Qty_Manual']

                    # Filter Tampilan (Hanya kolom penting)
                    final_cols = ['Line', 'Kategori', 'Material', 'Qty_SAP', 'Qty_Manual', 'Selisih']
                    final_display = final_df[final_cols].sort_values(by=['Kategori', 'Line', 'Material'])

                    st.subheader("✅ Hasil Rekonsiliasi")

                    # Fungsi Warna (Merah jika selisih)
                    def highlight_diff(row):
                        if abs(row['Selisih']) > 0.001: 
                            return ['background-color: #ffcccc; color: black'] * len(row)
                        else:
                            return [''] * len(row)

                    st.dataframe(
                        final_display.style.apply(highlight_diff, axis=1)
                        .format("{:,.2f}", subset=['Qty_SAP', 'Qty_Manual', 'Selisih']),
                        use_container_width=True,
                        height=600
                    )
                    
                    # Metric Summary
                    st.metric("Total Selisih", f"{final_display['Selisih'].sum():,.2f}")

            except Exception as e:
                st.error("Gagal membaca data paste. Pastikan Anda meng-copy tabel Excel dengan benar.")
                st.error(f"Error detail: {e}")
        
        else:
            st.warning("Silakan paste data Excel Anda di kotak di atas.")


