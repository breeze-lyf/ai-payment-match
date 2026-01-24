import streamlit as st
import pandas as pd
import os
from loader import MasterDataLoader, BankExcelLoader
from ocr import AIPDFExtractor, OCRValidationError
from matcher import CascadeMatcher
from database import DatabaseManager
from datetime import datetime
import io

# --- 页面配置 ---
st.set_page_config(page_title="PayMatch Reconcile", layout="wide")

# --- 初始化 Session State ---
if 'api_key' not in st.session_state:
    st.session_state['api_key'] = os.getenv("GOOGLE_API_KEY", "")
if 'system_data_path' not in st.session_state:
    st.session_state['system_data_path'] = "data/system_data"
if 'df_master' not in st.session_state:
    st.session_state['df_master'] = None

# 初始化数据库
db = DatabaseManager()

# --- 侧边栏导航 (参照草图) ---
with st.sidebar:
    st.title("💳 PayMatch")
    st.markdown("---")
    
    # 顶部导航
    menu = st.radio(
        "导航菜单",
        ["员工信息维护", "发薪数据比对", "AI 转表格"],
        index=1 # 默认进入比对页
    )
    
    # 撑开空间将设置推到底部
    st.markdown("<br>" * 10, unsafe_allow_html=True)
    st.markdown("---")
    
    # 底部设置
    if st.button("⚙️ 系统设置"):
        st.session_state['menu_selection'] = "系统设置"
        st.rerun() if 'menu_selection' in st.session_state else None
    
    # 处理系统设置的特殊跳转
    current_menu = st.session_state.get('menu_selection', menu)
    if menu != st.session_state.get('last_menu'):
        st.session_state['menu_selection'] = menu
        st.session_state['last_menu'] = menu
        current_menu = menu

# --- 页面逻辑分发 ---

# 1. 员工信息维护
if current_menu == "员工信息维护":
    st.header("👥 员工信息维护")
    st.info("从系统 Excel 真理库加载所有历史数据。")
    
    col_path, col_btn = st.columns([3, 1])
    path = col_path.text_input("真理库路径", value=st.session_state['system_data_path'])
    
    if col_btn.button("🚀 加载/刷新数据", use_container_width=True):
        if not os.path.exists(path):
            st.error("路径不存在")
        else:
            loader = MasterDataLoader(path)
            with st.spinner("正在同步数据..."):
                df = loader.load_all_excel()
                st.session_state['df_master'] = df
                st.session_state['system_data_path'] = path
                st.success(f"同步成功！共加载 {len(df)} 条记录。")
    
    if st.session_state['df_master'] is not None:
        st.dataframe(st.session_state['df_master'], use_container_width=True)

# 2. 发薪数据比对 (核心功能)
elif current_menu == "发薪数据比对":
    st.header("📊 发薪数据比对")
    
    if st.session_state['df_master'] is None:
        st.warning("⚠️ 请先到「员工信息维护」页面加载系统数据。")
    else:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("1. 准备银行流水数据")
            data_source = st.radio("流水来源:", ["扫描件 PDF (AI 识别)", "电子版 Excel"])
            
            if data_source == "扫描件 PDF (AI 识别)":
                uploaded_file = st.file_uploader("选择银行流水 PDF 文件", type="pdf")
            else:
                uploaded_file = st.file_uploader("选择银行流水 Excel 文件", type="xlsx")
                
            target_month = st.text_input("核对月份 (可选，留空将从文件名提取)", value="")
            
        if uploaded_file and st.button("🔍 开始核对"):
            try:
                df_bank = None
                # 清除旧结果
                if 'df_result' in st.session_state: del st.session_state['df_result']
                
                if data_source == "扫描件 PDF (AI 识别)":
                    temp_path = f"data/bank_pdf/temp_{uploaded_file.name}"
                    with open(temp_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    extractor = AIPDFExtractor(api_key=st.session_state['api_key'])
                    progress_bar = st.progress(0, text="准备解析 PDF...")
                    df_bank = extractor.process_pdf(temp_path, target_month if target_month else None, max_workers=3, progress_bar=progress_bar)
                    st.session_state['df_bank'] = df_bank
                else:
                    bank_loader = BankExcelLoader()
                    with st.spinner("正在读取 Excel 流水..."):
                        df_bank = bank_loader.load_excel(uploaded_file, target_month if target_month else None)
                        st.session_state['df_bank'] = df_bank
                
                # 执行匹配
                matcher = CascadeMatcher(st.session_state['df_master'])
                with st.spinner("正在执行级联匹配..."):
                    df_result = matcher.match(df_bank)
                    st.session_state['df_result'] = df_result
                
                st.success("核对完成！")
            except Exception as e:
                st.error(f"核对出错: {e}")
                st.exception(e)

        # --- 结果展示 (看板) ---
        if 'df_result' in st.session_state:
            df_res = st.session_state['df_result']
            st.markdown("---")
            st.subheader("📊 核对结果看板")
            
            # 汇总卡片
            m1, m2, m3, m4 = st.columns(4)
            total = len(df_res)
            ok_count = len(df_res[df_res['match_status'] == 'MATCH_OK'])
            diff_count = total - ok_count
            
            m1.metric("总笔数", total)
            m2.metric("完全匹配 ✅", ok_count)
            m3.metric("异常笔数 ⚠️", diff_count, delta_color="inverse")
            m4.metric("匹配率", f"{(ok_count/total*100):.1f}%" if total > 0 else "0%")
            
            # 异常详情
            st.subheader("🚩 异常详情")
            status_filter = st.multiselect(
                "筛选异常类型",
                options=['DIFF_AMOUNT', 'GHOST_RECORD', 'DUPLICATE_NAME_CONFLICT', 'MISSING_PAYMENT'],
                default=['DIFF_AMOUNT', 'GHOST_RECORD', 'DUPLICATE_NAME_CONFLICT', 'MISSING_PAYMENT']
            )
            df_filtered = df_res[df_res['match_status'].isin(status_filter)]
            
            def highlight_status(val):
                color = 'white'
                if val == 'DIFF_AMOUNT': color = '#ff4b4b'
                elif val == 'GHOST_RECORD': color = '#ffa500'
                elif val == 'DUPLICATE_NAME_CONFLICT': color = '#f0f2f6'
                elif val == 'MISSING_PAYMENT': color = '#778da9'
                return f'background-color: {color}; color: black'

            st.dataframe(
                df_filtered.style.applymap(highlight_status, subset=['match_status']),
                use_container_width=True
            )
            
            # 导出报告
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_res.to_excel(writer, index=False)
            
            # 优化报告文件名：核对报告_月份_时间戳.xlsx
            report_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_month = target_month if target_month else "Auto"
            st.download_button("📥 下载完整报告 (.xlsx)", output.getvalue(), f"核对报告_{report_month}_{report_ts}.xlsx")

# 3. AI 转表格 (纯工具页)
elif current_menu == "AI 转表格":
    st.header("🪄 AI 转表格")
    st.write("仅使用 AI 提取 PDF 数据并导出为 Excel，不进行薪资比对。")
    
    # 持久化目录初始化
    HISTORY_DIR = "output/ocr_history"
    os.makedirs(HISTORY_DIR, exist_ok=True)
    
    tab1, tab2 = st.tabs(["✨ 开始转换", "🕒 历史记录"])
    
    with tab1:
        pdf_file = st.file_uploader("上传扫描件 PDF", type="pdf")
        tool_month = st.text_input("标记月份 (可选，留空将从文件名提取)", value="")
        
        if pdf_file and st.button("🪄 开始转换"):
            temp_path = f"data/bank_pdf/tool_{pdf_file.name}"
            with open(temp_path, "wb") as f:
                f.write(pdf_file.getbuffer())
            
            extractor = AIPDFExtractor(api_key=st.session_state['api_key'])
            prog = st.progress(0, "AI 转换中...")
            # 并发数设置为 3 以匹配 TPM 限制
            df_extracted = extractor.process_pdf(temp_path, tool_month if tool_month else None, max_workers=3, progress_bar=prog)
            
            if not df_extracted.empty:
                # 获取提取到的月份（可能从文件名提取）
                final_month = df_extracted['month'].iloc[0] if 'month' in df_extracted.columns else tool_month
                st.success("转换成功！")
                st.dataframe(df_extracted, use_container_width=True)
                
                # --- 持久化保存 ---
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_filename = pdf_file.name.replace(".pdf", "").replace(" ", "_")
                output_filename = f"{final_month}_{safe_filename}_{timestamp}.xlsx"
                save_path = os.path.join(HISTORY_DIR, output_filename)
                df_extracted.to_excel(save_path, index=False)
                
                # 记录到数据库
                db.add_record(
                    original_filename=pdf_file.name,
                    output_filename=output_filename,
                    month=final_month,
                    total_rows=len(df_extracted),
                    total_amount=float(df_extracted['bank_amount'].sum())
                )
                
                st.info(f"💾 数据已自动保存至历史记录：{output_filename}")
                
                # 导出 Excel
                output = io.BytesIO()
                df_extracted.to_excel(output, index=False)
                st.download_button("📥 立即下载 Excel", output.getvalue(), output_filename)
            else:
                st.error("未能提取到有效数据，请检查 API Key 或 PDF 质量。")

    with tab2:
        st.subheader("📋 历史解析记录")
        history = db.get_history()
        
        if not history:
            st.write("暂无历史记录。")
        else:
            # 转换为 DataFrame 展示更美观
            df_h = pd.DataFrame(history)
            df_h = df_h.rename(columns={
                'original_filename': '原始文件名',
                'month': '发薪月份',
                'total_rows': '笔数',
                'total_amount': '总金额',
                'timestamp': '转换时间'
            })
            
            # 遍历记录，提供下载按钮
            for index, row in df_h.iterrows():
                with st.expander(f"📄 {row['原始文件名']} ({row['发薪月份']}) - {row['转换时间'][:19]}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("总笔数", row['笔数'])
                    c2.metric("总金额", f"¥{row['总金额']:.2f}")
                    
                    # 读取文件供下载
                    file_path = os.path.join(HISTORY_DIR, history[index]['output_filename'])
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as f:
                            c3.download_button(
                                label="📥 下载 Excel",
                                data=f.read(),
                                file_name=history[index]['output_filename'],
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"dl_{history[index]['id']}"
                            )
                    else:
                        c3.error("文件已丢失")

# 4. 系统设置
elif current_menu == "系统设置":
    st.header("⚙️ 系统设置")
    new_key = st.text_input("Gemini API Key", value=st.session_state['api_key'], type="password")
    new_path = st.text_input("默认系统数据文件夹", value=st.session_state['system_data_path'])
    
    if st.button("💾 保存设置"):
        st.session_state['api_key'] = new_key
        st.session_state['system_data_path'] = new_path
        st.success("设置已保存！")
