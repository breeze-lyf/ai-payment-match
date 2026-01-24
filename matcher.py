import pandas as pd
import numpy as np
from typing import Tuple

class CascadeMatcher:
    def __init__(self, df_master: pd.DataFrame, epsilon: float = 0.01):
        """
        :param df_master: 真理库 (Master Data)
        :param epsilon: 金额比较的容差
        """
        self.df_master = df_master.copy()
        self.epsilon = epsilon
        # 初始化匹配标记列
        self.df_master['_matched'] = False

    def match(self, df_bank: pd.DataFrame) -> pd.DataFrame:
        """执行增强版级联匹配逻辑 (优先卡号，次选姓名)"""
        results = []
            
        # 1. 准备系统端数据：确保卡号是字符串且去空格
        if 'bank_card' in self.df_master.columns:
            self.df_master['bank_card'] = self.df_master['bank_card'].astype(str).str.strip().replace('nan', '')
    
        # 2. 准备银行端数据：确保卡号是字符串且去空格
        df_bank = df_bank.copy()
        df_bank['bank_account_no'] = df_bank['bank_account_no'].astype(str).str.strip().replace('nan', '')
    
        # --- 策略 A: 优先通过【银行卡号】进行绝对匹配 ---
        # 这种方式可以完美解决重名和多项目混合问题
        for idx_bank, br in df_bank.iterrows():
            br_processed = False
                
            # 如果银行流水中有账号信息，先按账号找
            if br['bank_account_no'] and len(br['bank_account_no']) > 5:
                # 寻找卡号一致的系统记录 (支持后 4 位或全号匹配，取决于 AI 识别质量)
                # 这里我们先尝试全号匹配
                matched_sys = self.df_master[
                    (~self.df_master['_matched']) & 
                    (self.df_master['bank_card'].str.contains(br['bank_account_no']) | 
                     (br['bank_account_no'].str.contains(self.df_master['bank_card']) & (self.df_master['bank_card'] != "")))
                ]
                    
                if not matched_sys.empty:
                    # 如果卡号匹配到了，再看金额
                    # 精确匹配金额
                    perfect_match = matched_sys[abs(matched_sys['sys_amount'] - br['bank_amount']) < self.epsilon]
                        
                    if not perfect_match.empty:
                        target_idx = perfect_match.index[0]
                        status = 'MATCH_OK'
                    else:
                        # 卡号对，但金额错
                        target_idx = matched_sys.index[0]
                        status = 'DIFF_AMOUNT'
                        
                    self.df_master.at[target_idx, '_matched'] = True
                    res = {**br.to_dict(), **self.df_master.loc[target_idx].to_dict()}
                    res['match_status'] = status
                    res['diff_val'] = br['bank_amount'] - res['sys_amount']
                    results.append(res)
                    df_bank.at[idx_bank, '_processed'] = True
                    br_processed = True
    
            if br_processed: continue
    
        # --- 策略 B: 姓名 + 金额 兜底匹配 (处理卡号没识别清的情况) ---
        remaining_bank = df_bank[~df_bank.get('_processed', False)]
        for idx_bank, br in remaining_bank.iterrows():
            name = br['bank_name']
            amount = br['bank_amount']
                
            # 寻找同名且未匹配的系统人员
            sys_people = self.df_master[
                (~self.df_master['_matched']) & 
                (self.df_master['sys_name'] == name)
            ]
                
            if sys_people.empty:
                # 方案 1: 系统里完全没这人 -> 无关人员 (Ghost)
                res = br.to_dict()
                res['match_status'] = 'GHOST_RECORD'
                results.append(res)
            elif len(sys_people) == 1:
                # 方案 2: 唯一同名
                target_idx = sys_people.index[0]
                self.df_master.at[target_idx, '_matched'] = True
                res = {**br.to_dict(), **self.df_master.loc[target_idx].to_dict()}
                if abs(res['sys_amount'] - amount) < self.epsilon:
                    res['match_status'] = 'MATCH_OK'
                else:
                    res['match_status'] = 'DIFF_AMOUNT'
                res['diff_val'] = amount - res['sys_amount']
                results.append(res)
            else:
                # 方案 3: 重名冲突 (无法根据金额和姓名唯一确定)
                # 尝试看金额是否唯一
                amount_match = sys_people[abs(sys_people['sys_amount'] - amount) < self.epsilon]
                if len(amount_match) == 1:
                    target_idx = amount_match.index[0]
                    self.df_master.at[target_idx, '_matched'] = True
                    res = {**br.to_dict(), **self.df_master.loc[target_idx].to_dict()}
                    res['match_status'] = 'MATCH_OK'
                    res['diff_val'] = 0.0
                    results.append(res)
                else:
                    res = br.to_dict()
                    res['match_status'] = 'DUPLICATE_NAME_CONFLICT'
                    results.append(res)
    
        # --- 策略 C: 找出系统中漏发的 (Missing) ---
        missing_in_bank = self.df_master[~self.df_master['_matched']]
        for _, row in missing_in_bank.iterrows():
            res = row.to_dict()
            res['match_status'] = 'MISSING_PAYMENT'
            res['bank_name'] = res['sys_name']
            res['bank_amount'] = 0.0
            res['diff_val'] = -res['sys_amount']
            results.append(res)
    
        return pd.DataFrame(results)
    
if __name__ == "__main__":
    # 模拟测试
    df_sys = pd.DataFrame([
        {'month': '2024-10', 'sys_name': '张三', 'sys_amount': 5000.0, 'sys_id': '1001', 'sys_dept': '销售', 'sys_uid': '1'},
        {'month': '2024-10', 'sys_name': '李四', 'sys_amount': 6000.0, 'sys_id': '1002', 'sys_dept': '技术', 'sys_uid': '2'},
        {'month': '2024-10', 'sys_name': '王五', 'sys_amount': 7000.0, 'sys_id': '1003', 'sys_dept': '技术', 'sys_uid': '3'},
    ])
    
    df_bank = pd.DataFrame([
        {'month': '2024-10', 'bank_name': '张三', 'bank_amount': 5000.0, 'bank_page': 1}, # OK
        {'month': '2024-10', 'bank_name': '李四', 'bank_amount': 5800.0, 'bank_page': 1}, # DIFF
        {'month': '2024-10', 'bank_name': '赵六', 'bank_amount': 2000.0, 'bank_page': 2}, # GHOST
    ])
    
    matcher = CascadeMatcher(df_sys)
    result = matcher.match(df_bank)
    print(result[['bank_name', 'bank_amount', 'sys_amount', 'match_status', 'diff_val']])
