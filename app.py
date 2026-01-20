import streamlit as st
from pdf2image import convert_from_bytes
from PIL import Image
import io
import zipfile
import os
import re

def sanitize_filename(filename):
    """
    Windowsなどで問題になりやすい記号をサニタイズする
    """
    # NTFS禁止文字や記号をアンダースコアに置換
    s = re.sub(r'[\\/:*?"<>|：「」]', '_', filename)
    # スペースも置換
    s = re.sub(r'\s+', '_', s)
    # 長すぎると問題になるのでカット（拡張子考慮して100文字程度）
    return s[:100]

# --- 設定 ---
import platform

# OSに応じてPopplerのパスを切り替え
if platform.system() == "Windows":
    # ローカル（Windows）の場合
    POPPLER_PATH = os.path.join(os.getcwd(), "poppler", "bin")
else:
    # Streamlit Cloud（Linux）などの場合、システムパスのPopplerを使用
    POPPLER_PATH = None

st.set_page_config(page_title="PDF画像化 & 圧縮ツール", page_icon="📄")

st.title("📄 PDF画像化 & 圧縮ツール")
st.write("PDFをアップロードすると、ページごとに分割・圧縮してJPG化します。")

# 1. ファイルアップロード
uploaded_files = st.file_uploader("PDFファイルをドラッグ＆ドロップしてください（複数可）", type="pdf", accept_multiple_files=True)

# サイドバーで画質設定
st.sidebar.header("設定")

# 1. 出力形式の選択
format_option = st.sidebar.radio(
    "出力形式",
    ["JPG", "WebP"],
    index=1,
    help="WebPはJPGより軽量で高品質ですが、古いソフトでは開けない場合があります。"
)

# 2. リサイズ設定
max_dim = st.sidebar.select_slider(
    "長辺の最大サイズ (px)",
    options=[1024, 1280, 1920, 2560, 3840, "制限なし"],
    value=1920,
    help="画像をこのサイズ以下にリサイズします。1920（フルHD相当）がおすすめです。"
)

dpi_setting = st.sidebar.slider("解像度 (DPI)", 100, 400, 200, step=50, help="変換時の密度です。リサイズを併用する場合は200程度で十分です。")
quality_setting = st.sidebar.slider("圧縮画質 (Quality)", 50, 100, 85, step=5, help="数値が低いほど容量が減ります。80-90がバランスが良いです。")

# セッション状態の初期化
if 'conversion_results' not in st.session_state:
    st.session_state['conversion_results'] = {}

if uploaded_files:
    if st.button("全ファイルの変換を開始"):
        # 古い結果をクリア
        st.session_state['conversion_results'] = {}
        
        for uploaded_file in uploaded_files:
            # 拡張子を除いたベース名
            base_file_name = os.path.splitext(uploaded_file.name)[0]
            
            with st.status(f"📁 {uploaded_file.name} を処理中...", expanded=True) as status:
                pdf_bytes = uploaded_file.getvalue()
                
                try:
                    # 1. PDFを画像に変換
                    images = convert_from_bytes(
                        pdf_bytes, 
                        dpi=dpi_setting, 
                        poppler_path=POPPLER_PATH
                    )

                    # 2. 圧縮済みPDFを手配
                    processed_pdf_images = []
                    for img in images:
                        if max_dim != "制限なし":
                            w, h = img.size
                            if max(w, h) > max_dim:
                                ratio = max_dim / max(w, h)
                                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
                        processed_pdf_images.append(img.convert("RGB"))

                    pdf_output_buffer = io.BytesIO()
                    processed_pdf_images[0].save(
                        pdf_output_buffer, 
                        save_all=True, 
                        append_images=processed_pdf_images[1:], 
                        format='PDF',
                        optimize=True
                    )
                    compressed_pdf_bytes = pdf_output_buffer.getvalue()

                    # 3. 画像ZIP（圧縮PDFも同梱）の作成
                    zip_buffer = io.BytesIO()
                    ext = "webp" if format_option == "WebP" else "jpg"
                    pil_format = "WEBP" if format_option == "WebP" else "JPEG"

                    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                        # 圧縮済みPDFをZIPの最初に入れる
                        zip_file.writestr(f"{base_file_name}_compressed.pdf", compressed_pdf_bytes)

                        for i, image in enumerate(images):
                            if max_dim != "制限なし":
                                w, h = image.size
                                if max(w, h) > max_dim:
                                    ratio = max_dim / max(w, h)
                                    image = image.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

                            img_byte_arr = io.BytesIO()
                            save_params = {"quality": quality_setting, "optimize": True}
                            if pil_format == "JPEG":
                                save_params["progressive"] = True
                            
                            image.save(img_byte_arr, format=pil_format, **save_params)
                            sanitized_base_name = sanitize_filename(base_file_name)
                            zip_file.writestr(f"{sanitized_base_name}_p_{i + 1:03}.{ext}", img_byte_arr.getvalue())

                    final_zip_bytes = zip_buffer.getvalue()
                    width, height = processed_pdf_images[0].size
                    
                    # ファイル名のサニタイゼーション
                    sanitized_base_name = sanitize_filename(base_file_name)

                    # 結果をセッション状態に保存
                    st.session_state['conversion_results'][uploaded_file.name] = {
                        "final_zip_bytes": final_zip_bytes,
                        "compressed_pdf_bytes": compressed_pdf_bytes,
                        "base_file_name": sanitized_base_name,
                        "num_pages": len(images),
                        "width": width,
                        "height": height,
                        "format_option": format_option
                    }
                    status.update(label=f"✅ {uploaded_file.name} の変換完了", state="complete", expanded=False)

                except Exception as e:
                    st.error(f"エラー ({uploaded_file.name}): {e}")

    # 保存された結果がある場合は表示
    if st.session_state['conversion_results']:
        st.divider()
        st.subheader("変換結果")
        for file_name, res in st.session_state['conversion_results'].items():
            with st.expander(f"📁 {file_name} の処理結果", expanded=True):
                st.success(f"完了！ 全{res['num_pages']}ページ")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("解像度", f"{res['width']} x {res['height']}")
                with col2:
                    st.metric("ZIPサイズ", f"{len(res['final_zip_bytes']) / (1024*1024):.2f} MB")
                with col3:
                    st.metric("圧縮PDF", f"{len(res['compressed_pdf_bytes']) / (1024*1024):.2f} MB")

                btn_c1, btn_c2 = st.columns(2)
                with btn_c1:
                    st.download_button(
                        label=f"📥 全部まとめZIP ({res['format_option']} + PDF)",
                        data=res['final_zip_bytes'],
                        file_name=f"{res['base_file_name']}_bundle.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key=f"zip_{file_name}"
                    )
                with btn_c2:
                    st.download_button(
                        label="📄 圧縮PDF単体 (AI用)",
                        data=res['compressed_pdf_bytes'],
                        file_name=f"{res['base_file_name']}_compressed.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"pdf_{file_name}"
                    )
