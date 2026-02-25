import pandas as pd
import os
import re
from pathlib import Path
from typing import List, Tuple
from logger_config import setup_logger

# 初始化日志记录器
logger = setup_logger("loader")

class MasterDataLoader:
    def __init__(self, folder_path: str):
        self.folder_path = folder_path
        self.required_columns = {
            '姓名': 'sys_name',
            '实发金额': 'sys_amount',
            '工号': 'sys_id',
            '部门': 'sys_dept'
        }

    def _extract_info_from_filename(self, file_path: str) -> Tuple[str, str]:
        """从文件名中提取月份和部门信息
        文件名格式示例: CH65961-触点南区-202412账单-1212.xlsx
        """
        filename = os.path.basename(file_path)
        
        # 1. 提取月份 (优先寻找 202xxxxx 格式的 6 位数字)
        month = "Unknown"
        # 匹配 202101 - 202912 这种格式
        month_match = re.search(r'(20[2-3]\d[0-1]\d)', filename)
        if month_match:
            raw_month = month_match.group(0)
            month = f"{raw_month[:4]}-{raw_month[4:]}"
        else:
            # 次选：匹配 4 位数字 (YYMM)
            month_match_short = re.search(r'(\d{4})', filename)
            if month_match_short:
                raw_month = month_match_short.group(0)
                month = f"20{raw_month[:2]}-{raw_month[2:]}"
        
        # 2. 提取部门 (通常在第一个和第二个 '-' 之间)
        # 针对 CH65961-触点南区-202412账单...
        dept = "Unknown"
        dept_match = re.search(r'-(.*?)-', filename)
        if dept_match:
            dept = dept_match.group(1).strip()
            
        return month, dept

    def load_all_excel(self) -> pd.DataFrame:
        """遍历文件夹，加载并合并所有 Excel 文件"""
        all_dfs = []
        path_list = list(Path(self.folder_path).glob("**/*.xlsx"))
        
        for path in path_list:
            logger.info(f"Loading: {path}")
            try:
                # 读取 Excel，确保工号是字符串
                df = pd.read_excel(path, dtype={'工号': str, '实发金额': float})
                
                # 1. 字段标准化
                column_mapping = {}
                for col in df.columns:
                    for key, val in self.required_columns.items():
                        if key in str(col):
                            column_mapping[col] = val
                
                df = df.rename(columns=column_mapping)
                
                # 2. 从文件名提取月份和部门 (优先级高于文件内容，或作为补充)
                file_month, file_dept = self._extract_info_from_filename(str(path))
                
                if 'month' not in df.columns or df['month'].isnull().all():
                    df['month'] = file_month
                
                if 'sys_dept' not in df.columns or df['sys_dept'].isnull().all():
                    df['sys_dept'] = file_dept

                # 检查必要列
                missing_cols = [v for v in self.required_columns.values() if v not in df.columns]
                if 'sys_name' not in df.columns or 'sys_amount' not in df.columns:
                    logger.warning(f"Warning: {path} missing critical columns")
                    continue
                
                # 3. 数据清洗
                df['sys_name'] = df['sys_name'].astype(str).str.strip()
                df['sys_dept'] = df['sys_dept'].astype(str).str.strip()
                
                # 4. 生成唯一指纹
                df['sys_uid'] = df['month'].astype(str) + "_" + df['sys_name'] + "_" + df['sys_dept']
                
                # 选出需要的列
                final_cols = ['month', 'sys_dept', 'sys_name', 'sys_id', 'sys_amount', 'sys_uid']
                # 补齐缺失列
                for col in final_cols:
                    if col not in df.columns:
                        df[col] = "Unknown"
                
                all_dfs.append(df[final_cols])
            except Exception as e:
                logger.error(f"Error loading {path}: {e}")
            
        if not all_dfs:
            return pd.DataFrame(columns=['month', 'sys_dept', 'sys_name', 'sys_id', 'sys_amount', 'sys_uid'])
            
        master_df = pd.concat(all_dfs, ignore_index=True)
        # 确保金额精度
        master_df['sys_amount'] = master_df['sys_amount'].round(2)
        return master_df

class BankExcelLoader:
    """处理用户通过 WPS 等工具自行转换后的银行 Excel 流水"""
    def __init__(self):
        self.column_mapping = {
            '姓名': 'bank_name',
            '金额': 'bank_amount',
            '账号': 'bank_account_no',
            '收/支': 'type', # 仅供过滤参考
        }

    def load_excel(self, file_path_or_buffer, month: str = None) -> pd.DataFrame:
        """加载银行 Excel 并标准化"""
        df = pd.read_excel(file_path_or_buffer)
        
        # 尝试从文件名提取日期
        file_date = "Unknown"
        if hasattr(file_path_or_buffer, 'name'):
            filename = file_path_or_buffer.name
            date_match = re.search(r'(\d+)', filename)
            if date_match:
                file_date = date_match.group(0)
            
            if not month:
                # 尝试提取月份
                if len(file_date) == 4:
                    month = f"20{file_date[:2]}-{file_date[2:]}"
                elif len(file_date) == 6:
                    month = f"{file_date[:4]}-{file_date[4:]}"
                else:
                    month = file_date

        # 模糊匹配列名
        mapping = {}
        for col in df.columns:
            for key, val in self.column_mapping.items():
                if key in str(col):
                    mapping[col] = val
        
        df = df.rename(columns=mapping)
        
        # 必须包含姓名和金额
        if 'bank_name' not in df.columns or 'bank_amount' not in df.columns:
            raise ValueError("银行 Excel 必须包含'姓名'和'金额'列")
        
        # 清洗数据
        df['bank_name'] = df['bank_name'].astype(str).str.strip()
        df['bank_amount'] = pd.to_numeric(df['bank_amount'], errors='coerce').fillna(0).round(2)
        if 'bank_account_no' in df.columns:
            df['bank_account_no'] = df['bank_account_no'].astype(str).str.strip().replace('nan', '')
        else:
            df['bank_account_no'] = ""
            
        df['month'] = month or "Unknown"
        df['bank_page'] = "Excel" # 标记来源
        df['pdf_date'] = file_date # 保持与 OCR 输出一致的列名
        
        return df[['month', 'bank_name', 'bank_amount', 'bank_account_no', 'bank_page', 'pdf_date']]

if __name__ == "__main__":
    # 测试代码
    loader = MasterDataLoader("data/system_data")
    df = loader.load_all_excel()
    logger.info(f"Total records loaded: {len(df)}")
    if not df.empty:
        logger.info(df.head())
