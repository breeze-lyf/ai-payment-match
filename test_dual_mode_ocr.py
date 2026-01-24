import os
from ocr import AIPDFExtractor
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd

# 加载环境变量
load_dotenv()

def test_dual_mode(pdf_path):
    print(f"🚀 开始双通道 PDF 解析测试 (自动判断电子版/扫描版)...")
    print(f"📂 目标文件: {pdf_path}")
    
    # 初始化提取器 (默认模型: GLM-4.6V 用于扫描版，代码内固定 DeepSeek-V3 用于电子版)
    try:
        extractor = AIPDFExtractor()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return

    # 调用处理逻辑 (内部会自动判断模式并并行处理)
    # 设置 verbose=True 实时查看识别出的内容预览
    print(f"🧠 正在启动并行解析流水线...")
    try:
        # 根据 TPM 动态调整并发数：
        # - 电子版 (DeepSeek-V3, TPM=100k)：并发 10
        # - 扫描版 (GLM-4V, TPM=20k)：并发 3
        df_result = extractor.process_pdf(pdf_path, max_workers=10, verbose=True)
        
        print("\n✨ --- 处理完成 --- ✨")
        print(f"📊 任务统计:")
        print(f" - 总计行数: {len(df_result)}")
        
        if not df_result.empty:
            print(f" - 覆盖页数: {df_result['bank_page'].nunique()} 页")
            print(f" - 总计金额: {df_result['bank_amount'].sum():.2f}")
            
            # 导出结果
            month_str = df_result['month'].iloc[0] if 'month' in df_result.columns else "Unknown"
            pdf_base = os.path.basename(pdf_path).replace(".pdf", "").replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            output_filename = f"DUAL_{month_str}_{pdf_base}_{timestamp}.xlsx"
            output_path = os.path.join("output", output_filename)
            
            os.makedirs("output", exist_ok=True)
            df_result.to_excel(output_path, index=False)
            print(f"💾 完整数据已保存至: {output_path}")
        else:
            print("⚠️ 未能提取到任何有效数据。")
            
        print("✨ ------------------ ✨\n")

    except Exception as e:
        print(f"❌ 运行报错: {e}")

if __name__ == "__main__":
    # 可以通过修改此路径测试不同的 PDF (电子版 vs 扫描版)
    target_pdf = "/Users/breeze/Dev/hr_payment_match/sheets_for_test/2410-2503账单/银行回传/202411.pdf"
    
    if os.path.exists(target_pdf):
        test_dual_mode(target_pdf)
    else:
        print(f"❌ 找不到测试文件: {target_pdf}")
