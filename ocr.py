import os
import json
import pandas as pd
import base64
import re
import io
import time
import pdfplumber
from typing import List, Dict, Any, Tuple
from pdf2image import convert_from_path
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

class OCRValidationError(Exception):
    """OCR 校验失败异常"""
    pass

class AIPDFExtractor:
    def __init__(self, api_key: str = None, base_url: str = None, model_id: str = None):
        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        self.base_url = base_url or os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
        self.model_id = model_id or os.getenv("MODEL_ID", "zai-org/GLM-4.6V")
        
        if not self.api_key:
            raise ValueError("API Key not found. Please set SILICONFLOW_API_KEY in .env")
            
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _encode_image(self, image: Image.Image) -> str:
        """将 PIL 图片转换为 base64 字符串"""
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

    def pdf_to_images(self, pdf_path: str) -> List[Image.Image]:
        """将 PDF 每一页转为图片"""
        return convert_from_path(pdf_path)

    def extract_from_image(self, image: Image.Image, page_num: int = 0, max_retries: int = 3) -> List[Dict[str, Any]]:
        """使用硅基流动的视觉模型提取单页数据 (包含 429 自动重试)"""
        # 根据用户要求，不再对图片进行任何质量压缩或尺寸缩放
        base64_image = self._encode_image(image)
        
        prompt = """
        你是一个专业的财务审计助手。请从这张银行流水截图中提取所有交易记录。
        你需要提取：
        1. 姓名 (Name)
        2. 金额 (Amount)
        3. 收款方账号 (Account Number)

        输出要求：
        - 必须返回纯 JSON 格式。
        - 格式如下：
          {
            "rows": [
                {"name": "张三", "amount": 5000.00, "account_no": "622202******1234"},
                {"name": "李四", "amount": 4500.50, "account_no": "621700******5678"}
            ]
          }
        - 只提取表格内的正式交易行数据，不要提取表头、页码、广告或其他杂项文字。
        - 如果数字模糊，请标记为 null。
        - 不要输出任何解释性文字。
        """
        
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ]
                )
                
                content = response.choices[0].message.content.strip()
                
                # 更加健壮的 JSON 提取逻辑
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(0))
                    rows = data.get("rows", [])
                    for r in rows:
                        r['bank_page'] = page_num
                    return rows
                else:
                    print(f"⚠️ 第 {page_num} 页未找到 JSON 结构。")
                    return []
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg:
                    wait_time = (attempt + 1) * 5 
                    print(f"⏳ 第 {page_num} 页触发速率限制 (429)，正在进行第 {attempt+1} 次重试，等待 {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ 第 {page_num} 页解析失败: {error_msg}")
                    return []
        
        print(f"❌ 第 {page_num} 页在重试 {max_retries} 次后仍然失败。")
        return []

    def is_electronic_pdf(self, pdf_path: str) -> bool:
        """检查 PDF 是否为电子版 (原生带文本层)"""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # 检查前 3 页，如果有任何一页提取出的文字超过 50 个字符，视为电子版
                for i in range(min(3, len(pdf.pages))):
                    text = pdf.pages[i].extract_text()
                    if text and len(text.strip()) > 50:
                        return True
            return False
        except Exception:
            return False

    def extract_from_text(self, text: str, page_num: int = 0, model_id: str = "deepseek-ai/DeepSeek-V3", max_retries: int = 3) -> List[Dict[str, Any]]:
        """使用 DeepSeek-V3 处理电子版 PDF 提取出的原始文本 (带全错误自动重试)"""
        prompt = f"请从以下银行流水文本中提取交易记录（姓名、金额、收款方账号），仅输出 JSON 格式：\n\n{text}"
        
        system_prompt = """
        你是一个专业的财务审计助手。请从原始文本中提取所有交易行数据。
        输出 JSON 格式: {"rows": [{"name": "xxx", "amount": 0.0, "account_no": "xxx"}]}
        只保留正式交易行，不要表头和无关文字。
        """

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"} if "DeepSeek" in model_id else None
                )
                
                content = response.choices[0].message.content.strip()
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    try:
                        data = json.loads(json_match.group(0))
                        rows = data.get("rows", [])
                        valid_rows = []
                        for r in rows:
                            if isinstance(r, dict):
                                r['bank_page'] = page_num
                                valid_rows.append(r)
                        if valid_rows:
                            return valid_rows
                    except json.JSONDecodeError:
                        pass
                
                # 如果代码运行到这里，说明解析出的内容有问题，触发重试
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"🔄 第 {page_num} 页解析内容无效，正在进行第 {attempt+1} 次重试...")
                    time.sleep(wait_time)
                    continue

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    error_type = "速率限制" if "429" in str(e) else "网络错误"
                    print(f"⏳ 第 {page_num} 页触发{error_type}，等待 {wait_time}s 后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ 第 {page_num} 页文本解析彻底失败: {e}")
                    return []
        return []

    def process_pdf(self, pdf_path: str, month: str = None, max_workers: int = 5, progress_bar=None, verbose: bool = False) -> pd.DataFrame:
        """处理整个 PDF 并返回 DataFrame (自动检测电子版/扫描版)"""
        filename = os.path.basename(pdf_path)
        file_date_match = re.search(r'(\d+)', filename)
        file_date = file_date_match.group(0) if file_date_match else filename.split('.')[0]
        
        if not month:
            if len(file_date) == 4:
                month = f"20{file_date[:2]}-{file_date[2:]}"
            elif len(file_date) == 6:
                month = f"{file_date[:4]}-{file_date[4:]}"
            else:
                month = file_date

        is_elec = self.is_electronic_pdf(pdf_path)
        print(f"🔍 检测到 PDF 类型: {'电子版 (原生)' if is_elec else '扫描版 (图片)'}")
        
        total_pages = 0
        page_results = {}
        all_rows = []

        if is_elec:
            # --- 方案 A: 电子版处理 (pdfplumber + DeepSeek-V3) ---
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                # 电子版使用更高并发（DeepSeek-V3 TPM=100k），若 max_workers < 5，自动提升为 8
                actual_workers = max(max_workers, 8) if max_workers < 10 else max_workers
                print(f"🚀 开始并发解析 {total_pages} 页电子版 PDF，使用 DeepSeek-V3 (并发数: {actual_workers})...")
                
                with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                    future_to_page = {
                        executor.submit(self.extract_from_text, p.extract_text(), i + 1, "deepseek-ai/DeepSeek-V3"): i + 1 
                        for i, p in enumerate(pdf.pages)
                    }
                    
                    for future in as_completed(future_to_page):
                        page_num = future_to_page[future]
                        rows = future.result()
                        page_results[page_num] = rows
                        print(f"✅ 第 {page_num} 页解析完成 (电子版，提取到 {len(rows)} 条)")
                        if verbose and rows:
                            for r in rows[:2]: print(f"   - {r.get('name')}: {r.get('amount')}")
                        
                        if progress_bar: progress_bar.progress(len(page_results)/total_pages)
        else:
            # --- 方案 B: 扫描版处理 (原来的视觉 AI 逻辑) ---
            images = self.pdf_to_images(pdf_path)
            total_pages = len(images)
            # 根据模型的 TPM 调整并发数
            # GLM-4.6V (TPM=20k): 2-3 并发
            # Qwen3-VL (TPM=80k): 6-8 并发
            actual_workers = max_workers
            if "Qwen" in self.model_id and max_workers < 5:
                actual_workers = 8
            elif "GLM" in self.model_id and max_workers > 3:
                actual_workers = 3
            
            print(f"🚀 开始并发解析 {total_pages} 页扫描版 PDF，使用 {self.model_id} (并发数: {actual_workers})...")
            
            with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                future_to_page = {
                    executor.submit(self.extract_from_image, img, i + 1): i + 1 
                    for i, img in enumerate(images)
                }
                
                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    rows = future.result() or []
                    page_results[page_num] = rows
                    print(f"✅ 第 {page_num} 页解析完成 (扫描版，提取到 {len(rows)} 条)")
                    if verbose and rows:
                        for r in rows[:2]: print(f"   - {r.get('name')}: {r.get('amount')}")
                    
                    if progress_bar: progress_bar.progress(len(page_results)/total_pages)
        
        # --- 按顺序组装 ---
        failed_pages = []
        for i in range(1, total_pages + 1):
            rows = page_results.get(i, [])
            if not rows:
                failed_pages.append(i)
            for r in rows:
                r['pdf_source_file'] = filename
                r['pdf_date'] = file_date
            all_rows.extend(rows)
        
        if failed_pages:
            print(f"\n⚠️ 任务完成，但以下页面未能提取到任何数据: {failed_pages}")
            print("💡 建议：请检查这些页面是否为空白页、汇总页，或者尝试手动处理。")
        
        if not all_rows:
            return pd.DataFrame(columns=['month', 'bank_name', 'bank_amount', 'bank_account_no', 'bank_page', 'pdf_date'])

        df_bank = pd.DataFrame(all_rows)
        df_bank['month'] = month
        df_bank = df_bank.rename(columns={
            'name': 'bank_name', 
            'amount': 'bank_amount',
            'account_no': 'bank_account_no'
        })
        
        df_bank['bank_amount'] = pd.to_numeric(df_bank['bank_amount'], errors='coerce').fillna(0).round(2)
        df_bank['bank_account_no'] = df_bank['bank_account_no'].astype(str).replace('None', '').replace('null', '')
        df_bank = df_bank.sort_values(by=['bank_page'])
        
        return df_bank[['month', 'bank_name', 'bank_amount', 'bank_account_no', 'bank_page', 'pdf_date']]
