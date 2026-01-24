import os
from ocr import AIPDFExtractor
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd

# 加载环境变量
load_dotenv()

def test_qwen_pdf(pdf_path):
    print(f"🚀 开始 Qwen 专项测试 (全量 PDF 转换)...")
    print(f"📂 目标文件: {pdf_path}")
    
    # 用户指定的模型 ID
    model_id = "Qwen/Qwen3-VL-32B-Instruct"
    
    # 1. 初始化提取器，传入自定义模型 ID
    try:
        extractor = AIPDFExtractor(model_id=model_id)
        print(f"🤖 使用模型: {model_id}")
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return

    # 2. 调用并发处理逻辑
    # Qwen3-VL 拥有 80k TPM，建议开启 5 并发以平衡速度与稳定性
    print(f"🧠 正在发起并发识别 (并发数: 5)...")
    try:
        # process_pdf 内部现在会实时打印进度和部分识别内容
        df_result = extractor.process_pdf(pdf_path, max_workers=5, verbose=True)
        
        print("\n✨ --- 转换完成 --- ✨")
        print(f"📊 汇总统计:")
        print(f" - 总计行数: {len(df_result)}")
        
        if not df_result.empty:
            print(f" - 覆盖页数: {df_result['bank_page'].nunique()} 页")
            print(f" - 总计金额: {df_result['bank_amount'].sum():.2f}")
            
            # 3. 构造输出文件名 (遵循系统规则: Month_Filename_Timestamp.xlsx)
            month_str = df_result['month'].iloc[0] if 'month' in df_result.columns else "Unknown"
            pdf_base_name = os.path.basename(pdf_path).replace(".pdf", "").replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            output_filename = f"QWEN_{month_str}_{pdf_base_name}_{timestamp}.xlsx"
            output_path = os.path.join("output", output_filename)
            
            os.makedirs("output", exist_ok=True)
            df_result.to_excel(output_path, index=False)
            print(f"💾 完整 Excel 已导出至: {output_path}")
        else:
            print("⚠️ 警告: 未能提取到任何有效数据。")
            
        print("✨ ------------------ ✨\n")

    except Exception as e:
        print(f"❌ 运行过程中发生错误: {e}")

if __name__ == "__main__":
    # 默认测试路径
    target_pdf = "/Users/breeze/Dev/hr_payment_match/sheets_for_test/2410-2503账单/银行回传/202511.pdf"
    
    if os.path.exists(target_pdf):
        test_qwen_pdf(target_pdf)
    else:
        print(f"❌ 找不到测试 PDF 文件，请确认路径: {target_pdf}")
