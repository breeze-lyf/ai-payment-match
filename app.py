import streamlit as st
import pandas as pd
import os
import re
from loader import MasterDataLoader, BankExcelLoader
from ocr import AIPDFExtractor, OCRValidationError
from matcher import CascadeMatcher
from database import DatabaseManager
from datetime import datetime
import io
import subprocess

# --- 版本信息 ---
VERSION = "v2.1.0"  # 手动版本号
try:
    # 尝试获取 Git commit hash（前 7 位）
    git_hash = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], 
                                       cwd=os.path.dirname(__file__)).decode('utf-8').strip()
    VERSION_INFO = f"{VERSION} ({git_hash})"
except:
    VERSION_INFO = VERSION

# --- 页面配置 ---
st.set_page_config(page_title="PayMatch Reconcile", layout="wide")

# --- 初始化 Session State ---
if 'api_key' not in st.session_state:
    st.session_state['api_key'] = os.getenv("GOOGLE_API_KEY", "")

# 初始化数据库
db = DatabaseManager()

# --- 侧边栏导航 (参照草图) ---
with st.sidebar:
    st.title("💳 PayMatch")
    st.markdown("---")
    
    # 顶部导航
    menu = st.radio(
        "导航菜单",
        ["员工信息维护", "实发账单合并", "发薪数据比对", "AI 转表格"],
        index=2 # 默认进入比对页
    )
    
    # 撑开空间将设置推到底部
    st.markdown("<br>" * 10, unsafe_allow_html=True)
    st.markdown("---")
    
    # 底部设置
    if st.button("⚙️ 系统设置"):
        st.session_state['menu_selection'] = "系统设置"
        st.rerun() if 'menu_selection' in st.session_state else None
    
    # 版本号显示
    st.caption(f"🏷️ 版本: {VERSION_INFO}")
    
    # 处理系统设置的特殊跳转
    current_menu = st.session_state.get('menu_selection', menu)
    if menu != st.session_state.get('last_menu'):
        st.session_state['menu_selection'] = menu
        st.session_state['last_menu'] = menu
        current_menu = menu

# --- 共享工具函数 ---
def parse_payroll_excel(uploaded_file):
    """解析单个发薪 Excel，自动提取年月和片区"""
    filename = uploaded_file.name
    # 1. 提取月份
    file_month = "Unknown"
    month_match = re.search(r'(20\d{4})', filename)
    if month_match:
        raw_month = month_match.group(0)
        file_month = f"{raw_month[:4]}-{raw_month[4:]}"
    
    # 2. 提取片区
    file_dept = "未知片区"
    if '-' in filename:
        parts = filename.split('-')
        if len(parts) >= 2:
            file_dept = parts[1].strip()
    
    df_raw = pd.read_excel(uploaded_file)
    
    # 过滤对照行
    if not df_raw.empty and '姓名' in df_raw.columns:
        first_name = str(df_raw.iloc[0]['姓名'])
        if first_name.lower() in ['name', '姓名']:
            df_raw = df_raw.iloc[1:].reset_index(drop=True)

    # 优先精确匹配，再进行模糊匹配（避免误读相似列）
    mapping = {
        '姓名': 'sys_name', 
        '工号': 'sys_id', 
        '部门': 'sys_dept',
        '身份证号': 'sys_id_card'
    }
    
    # 金额列单独处理（优先级从高到低，使用精确匹配）
    amount_candidates = [
        '员工实发合计',                  # 最高优先级（精确匹配）
        'After-taxtotalIncome',        # 英文列名（去空格）
        'After-tax total Income',      # 带空格版本
        '实发合计',
        '员工实发',
        '实发金额',
        '实发工资'
    ]
    
    # 排除干扰列（这些列虽然包含关键字，但不是我们要的）
    exclude_keywords = ['五险一金', '个人所得税', '社保', '公积金', '税前', '税后增加', '税后扣减']
    
    rename_dict = {}
    amount_col_found = False
    
    # 第一步：精确匹配基础列
    for col in df_raw.columns:
        col_str = str(col).replace('\n', '').replace(' ', '').strip()
        for k, v in mapping.items():
            if k == col_str or k in col_str:
                rename_dict[col] = v
                break
    
    # 第二步：精确匹配金额列（排除干扰列）
    for candidate in amount_candidates:
        if amount_col_found:
            break
        for col in df_raw.columns:
            col_str = str(col).replace('\n', '').replace(' ', '').strip()
            
            # 先检查是否是干扰列
            is_excluded = any(exc in col_str for exc in exclude_keywords)
            if is_excluded:
                continue
            
            # 精确匹配或包含匹配
            if candidate == col_str or candidate in col_str:
                rename_dict[col] = 'sys_amount'
                amount_col_found = True
                break
    
    df_mapped = df_raw.rename(columns=rename_dict)
    
    if 'sys_name' not in df_mapped.columns or 'sys_amount' not in df_mapped.columns:
        return None, f"文件 {filename} 缺少关键列"
    
    # --- 数据清洗：过滤空行和汇总行 ---
    # 1. 删除"姓名"为空的行
    df_mapped = df_mapped[df_mapped['sys_name'].notna()]
    df_mapped = df_mapped[df_mapped['sys_name'].astype(str).str.strip() != '']
    
    # 2. 删除包含"合计"、"小计"、"总计"等关键字的行
    summary_keywords = ['合计', '小计', '总计', '汇总', '总额', '共计']
    mask = df_mapped['sys_name'].astype(str).str.contains('|'.join(summary_keywords), case=False, na=False)
    df_mapped = df_mapped[~mask]
    
    # 3. 填充字段并清洗金额
    df_mapped['month'] = file_month
    df_mapped['sys_dept'] = file_dept
    df_mapped['sys_amount'] = pd.to_numeric(df_mapped['sys_amount'], errors='coerce').fillna(0).round(2)
    
    # 4. 再次过滤金额为 0 或异常大的数据（可能是误读的汇总行）
    df_mapped = df_mapped[df_mapped['sys_amount'] > 0]
    df_mapped = df_mapped[df_mapped['sys_amount'] < 500000]  # 单人实发通常不超过 50 万
    
    cols = [c for c in ['month', 'sys_name', 'sys_id', 'sys_amount', 'sys_dept', 'sys_id_card'] if c in df_mapped.columns]
    return df_mapped[cols].reset_index(drop=True), None

# --- 页面逻辑分发 ---

# 1. 员工信息维护
if current_menu == "员工信息维护":
    st.header("👥 员工信息维护")
    st.info("存储员工基础档案（身份证、姓名、工号、电脑号、银行卡号、项目、部门/片区）。相同身份证号将自动覆盖更新。")
    
    # --- 导入功能 ---
    with st.expander("📥 导入员工基础数据", expanded=True):
        uploaded_excel = st.file_uploader("选择员工 Excel 文件", type=["xlsx", "xls"])
        if uploaded_excel:
            try:
                # 预读取检查列名
                df_upload = pd.read_excel(uploaded_excel)
                # 适配用户要求的字段
                required = ['姓名', '身份证号', '工号', '电脑号', '银行卡号', '项目', '部门']
                missing = [c for c in required if c not in df_upload.columns]
                
                # 特殊处理：部门也可以叫片区
                if '部门' in missing and '片区' in df_upload.columns:
                    missing.remove('部门')
                
                if missing:
                    st.error(f"Excel 缺少必要列: {', '.join(missing)}")
                else:
                    if st.button("🚀 确认导入/更新"):
                        db.upsert_employees(df_upload)
                        st.success(f"成功导入/更新 {len(df_upload)} 条员工记录！")
                        st.rerun()
            except Exception as e:
                st.error(f"读取文件出错: {e}")

    # --- 数据展示与导出 ---
    df_employees = db.get_all_employees()
    
    if not df_employees.empty:
        st.markdown("---")
        c1, c2 = st.columns([3, 1])
        c1.subheader(f"📋 员工档案库 ({len(df_employees)} 人)")
        
        # 导出 Excel
        output = io.BytesIO()
        df_employees.to_excel(output, index=False)
        c2.download_button(
            "📥 导出全量数据",
            output.getvalue(),
            f"Employee_Master_{datetime.now().strftime('%Y%m%d')}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # 展示
        display_df = df_employees.rename(columns={
            'id_card': '身份证号',
            'name': '姓名',
            'emp_id': '工号',
            'pc_id': '电脑号',
            'bank_card': '银行卡号',
            'project': '项目',
            'dept': '部门/片区',
            'last_updated': '最后更新'
        })
        st.dataframe(display_df, width="stretch")
        
        if st.button("🗑️ 清空档案库"):
            if st.checkbox("确认清空所有数据？"):
                db.delete_all_employees()
                st.success("已清空。")
                st.rerun()
    else:
        st.warning("📭 档案库中暂无数据，请先导入。")

# 2. 实发账单合并 (纯工具页)
elif current_menu == "实发账单合并":
    st.header("📂 实发账单合并")
    st.write("一次性上传多个片区的 Excel 发薪表，系统将自动识别片区和月份并合并为一个文件。")
    
    files = st.file_uploader("上传一个或多个片区 Excel", type=["xlsx", "xls"], accept_multiple_files=True)
    
    if files:
        all_dfs = []
        summary = []
        for f in files:
            df, error = parse_payroll_excel(f)
            if df is not None:
                all_dfs.append(df)
                summary.append({
                    "文件名": f.name,
                    "月份": df['month'].iloc[0] if not df.empty else "未知",
                    "片区": df['sys_dept'].iloc[0] if not df.empty else "未知",
                    "总人数": len(df),
                    "总金额": df['sys_amount'].sum()
                })
            else:
                st.warning(f"跳过 {f.name}: {error}")
        
        if all_dfs:
            df_merged = pd.concat(all_dfs, ignore_index=True)
            st.success(f"✅ 成功合并 {len(all_dfs)} 个文件，共 {len(df_merged)} 条记录。")
            
            st.subheader("📊 解析摘要")
            st.table(pd.DataFrame(summary))
            
            st.subheader("👀 数据预览 (前 50 条)")
            st.dataframe(df_merged.head(50), width="stretch")
            
            # 导出
            output = io.BytesIO()
            df_merged.to_excel(output, index=False)
            
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                "📥 下载合并后的 Excel",
                output.getvalue(),
                f"合并账单_{ts}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# 3. 发薪数据比对 (核心功能)
elif current_menu == "发薪数据比对":
    st.header("📊 发薪数据比对")
    
    col_sys, col_bank = st.columns(2)
    
    with col_sys:
        st.subheader("1. 内部发薪明细 (真理库)")
        st.info("支持一次性上传多个片区的 Excel 表格，系统会自动识别并合并数据。")
        sys_files = st.file_uploader("上传一个或多个发薪 Excel", type=["xlsx", "xls"], accept_multiple_files=True, key="sys_up")
        
    with col_bank:
        st.subheader("2. 银行流水数据 (核对目标)")
        bank_source = st.radio("流水来源:", ["扫描件 PDF (AI 识别)", "电子版 Excel"], key="bank_src")
        bank_file = st.file_uploader(f"选择银行流水 {bank_source.split(' ')[0]}", type=["pdf", "xlsx"], key="bank_up")
    
    st.markdown("---")

    if sys_files and bank_file and st.button("🔍 开始自动化比对", width="stretch"):
        try:
            # 1. 加载并合并多个内部发薪数据 (Input A)
            all_sys_dfs = []
            detected_months = set()
            with st.spinner(f"正在处理 {len(sys_files)} 个片区表格..."):
                for uploaded_sys in sys_files:
                    df_p, error = parse_payroll_excel(uploaded_sys)
                    if df_p is not None:
                        all_sys_dfs.append(df_p)
                        if df_p['month'].iloc[0] != "Unknown":
                            detected_months.add(df_p['month'].iloc[0])
                        st.write(f"📄 已解析：{uploaded_sys.name} → [月份: {df_p['month'].iloc[0]}, 片区: {df_p['sys_dept'].iloc[0]}]")
                    else:
                        st.warning(f"跳过文件 {uploaded_sys.name}：{error}")
                
                if not all_sys_dfs:
                    st.error("没有一个有效的文件被加载。")
                    st.stop()
                
                df_sys = pd.concat(all_sys_dfs, ignore_index=True)
                # 如果某个文件没识别出月份，填充一个默认值
                if 'month' not in df_sys.columns: df_sys['month'] = "Auto"
                df_sys['month'] = df_sys['month'].fillna("Auto")
                
                st.info(f"✅ 已成功合并 {len(all_sys_dfs)} 个片区数据，共 {len(df_sys)} 条发薪记录。识别到月份: {', '.join(detected_months) if detected_months else '自动'}")
            
            # 2. 加载银行数据 (Input B)
            df_bank = None
            primary_month = list(detected_months)[0] if detected_months else None
            
            if bank_source == "扫描件 PDF (AI 识别)":
                temp_path = f"data/bank_pdf/temp_{bank_file.name}"
                with open(temp_path, "wb") as f:
                    f.write(bank_file.getbuffer())
                
                extractor = AIPDFExtractor(api_key=st.session_state['api_key'])
                progress_bar = st.progress(0, text="AI 正在解析 PDF 页面...")
                # 传入 primary_month 作为一个参考 hint，如果银行文件名没月份则用它
                df_bank = extractor.process_pdf(temp_path, primary_month, max_workers=5, progress_bar=progress_bar)
            else:
                bank_loader = BankExcelLoader()
                with st.spinner("正在读取银行 Excel 流水..."):
                    df_bank = bank_loader.load_excel(bank_file, primary_month)
            
            # 3. 执行级联匹配
            if df_bank is not None and not df_bank.empty:
                matcher = CascadeMatcher(df_sys)
                with st.spinner("正在执行级联匹配算法..."):
                    df_result = matcher.match(df_bank)
                    
                    # 4. 可选：关联员工档案库 (ID Card, PC ID, 项目, 部门等)
                    df_emp_db = db.get_all_employees()
                    if not df_emp_db.empty:
                        # 优先尝试通过身份证号关联，次选姓名
                        if 'sys_id_card' in df_result.columns:
                            # 转换为字符串并去空格
                            df_result['sys_id_card'] = df_result['sys_id_card'].astype(str).str.strip()
                            df_emp_db['id_card'] = df_emp_db['id_card'].astype(str).str.strip()
                            
                            df_result = pd.merge(df_result, df_emp_db[['id_card', 'pc_id', 'bank_card', 'project', 'dept']], 
                                                 left_on='sys_id_card', right_on='id_card', how='left')
                        else:
                            df_result = pd.merge(df_result, df_emp_db[['name', 'id_card', 'pc_id', 'bank_card', 'project', 'dept']], 
                                                 left_on='sys_name', right_on='name', how='left')
                    
                    st.session_state['df_result'] = df_result
                st.success("🎉 比对分析完成！")
            else:
                st.error("未能从银行流水中提取到有效数据。")
        except Exception as e:
            st.error(f"比对过程中出错: {e}")
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
            width="stretch"
        )
        
        # 导出报告
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_res.to_excel(writer, index=False)
        
        # 优化报告文件名：核对报告_月份_时间戳.xlsx
        report_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_month = "-".join(detected_months) if 'detected_months' in locals() and detected_months else "Auto识别"
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
                st.dataframe(df_extracted, width="stretch")
                
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
    new_key = st.text_input("Gemini/视觉 AI API Key", value=st.session_state['api_key'], type="password")
    
    if st.button("💾 保存设置"):
        st.session_state['api_key'] = new_key
        st.success("设置已保存！")
