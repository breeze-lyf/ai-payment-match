import os
from ocr import AIPDFExtractor
from dotenv import load_dotenv
from pdf2image import convert_from_path
from datetime import datetime
import pandas as pd

# 加载环境变量 (API Key)
load_dotenv()

def test_full_pdf(pdf_path):
    print(f"🚀 开始全量测试文件: {pdf_path}")
    
    # 1. 初始化提取器
    try:
        extractor = AIPDFExtractor()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return

    # 2. 调用并发处理逻辑
    # 考虑到 TPM 为 20,000，将 max_workers 设为 3 以保证稳定 (配合 ocr.py 的自动重试)
    print(f"🧠 正在调用 AI ({os.getenv('MODEL_ID')}) 进行并发识别 (并发数: 3)...")
    try:
        df_result = extractor.process_pdf(pdf_path, month="2025-11", max_workers=3)
        
        print("\n✨ --- 处理完成 --- ✨")
        print(f"📊 数据统计:")
        print(f" - 总提取行数: {len(df_result)}")
        if not df_result.empty:
            print(f" - 覆盖页数: {df_result['bank_page'].nunique()} 页")
            print(f" - 总金额汇总: {df_result['bank_amount'].sum():.2f}")
            if 'bank_account_no' in df_result.columns:
                valid_accounts = df_result['bank_account_no'].apply(lambda x: len(str(x)) > 5).sum()
                print(f" - 已提取账号行数: {valid_accounts}")
            
            # 预览数据
            print("\n👀 数据预览 (前 5 行):")
            cols_to_show = ['bank_name', 'bank_amount', 'bank_account_no', 'bank_page']
            print(df_result[cols_to_show].head().to_string(index=False))
            
            # 3. 构造与正式系统一致的文件名
            # 规则: {月份}_{原文件名}_{时间戳}.xlsx
            month_str = df_result['month'].iloc[0] if 'month' in df_result.columns else "Unknown"
            pdf_name = os.path.basename(pdf_path).replace(".pdf", "").replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            output_filename = f"{month_str}_{pdf_name}_{timestamp}.xlsx"
            output_path = os.path.join("output", output_filename)
            
            os.makedirs("output", exist_ok=True)
            df_result.to_excel(output_path, index=False)
            print(f"💾 详细结果已保存至: {output_path}")
        else:
            print("⚠️ 未提取到任何有效数据。")
        print("✨ ------------------ ✨\n")

    except Exception as e:
        print(f"❌ 处理过程出错: {e}")

if __name__ == "__main__":
    target_pdf = "/Users/breeze/Dev/hr_payment_match/sheets_for_test/2410-2503账单/银行回传/202511.pdf"
    if os.path.exists(target_pdf):
        test_full_pdf(target_pdf)
    else:
        print(f"❌ 找不到文件: {target_pdf}")
