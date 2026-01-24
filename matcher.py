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
        """执行级联匹配逻辑"""
        results = []
        
        # 按照 (month, bank_name) 分组处理，提高效率并处理重名逻辑
        for (month, name), group in df_bank.groupby(['month', 'bank_name']):
            # 获取系统中该月份该姓名的人
            sys_people = self.df_master[
                (self.df_master['month'] == month) & 
                (self.df_master['sys_name'] == name)
            ].copy()
            
            # 记录银行端该组的数据
            bank_records = group.to_dict('records')
            
            # --- Level 1: Perfect Match ---
            # 尝试把金额完全对上的先消耗掉
            for br in bank_records:
                # 寻找金额一致且未被匹配的系统记录
                matched_sys = sys_people[
                    (~sys_people['_matched']) & 
                    (abs(sys_people['sys_amount'] - br['bank_amount']) < self.epsilon)
                ]
                
                if not matched_sys.empty:
                    # 取第一个匹配项
                    idx = matched_sys.index[0]
                    self.df_master.at[idx, '_matched'] = True
                    sys_people.at[idx, '_matched'] = True
                    
                    # 填充结果
                    res = {**br, **self.df_master.loc[idx].to_dict()}
                    res['match_status'] = 'MATCH_OK'
                    res['diff_val'] = 0.0
                    results.append(res)
                    br['_processed'] = True # 标记该银行记录已处理
                else:
                    br['_processed'] = False

            # --- Level 2 & 3: Remaining in this group ---
            remaining_bank = [br for br in bank_records if not br['_processed']]
            remaining_sys = sys_people[~sys_people['_matched']]
            
            if remaining_bank:
                # 如果系统里根本没这人
                if sys_people.empty:
                    for br in remaining_bank:
                        res = {**br}
                        res['match_status'] = 'GHOST_RECORD'
                        res['diff_val'] = np.nan
                        results.append(res)
                
                # 如果系统里有且唯一，但金额对不上 (Level 2)
                elif len(sys_people) == 1 and len(remaining_bank) == 1:
                    br = remaining_bank[0]
                    idx = sys_people.index[0]
                    self.df_master.at[idx, '_matched'] = True
                    
                    res = {**br, **self.df_master.loc[idx].to_dict()}
                    res['match_status'] = 'DIFF_AMOUNT'
                    res['diff_val'] = br['bank_amount'] - res['sys_amount']
                    results.append(res)
                
                # 如果存在重名冲突 (Level 3)
                else:
                    for br in remaining_bank:
                        res = {**br}
                        res['match_status'] = 'DUPLICATE_NAME_CONFLICT'
                        res['diff_val'] = np.nan
                        # 尝试附带部门信息供人工参考
                        if not sys_people.empty:
                            res['sys_dept_candidates'] = "/".join(sys_people['sys_dept'].unique())
                        results.append(res)

        # --- Level 4: Missing Payment ---
        # 找出系统中完全没有被匹配到的记录
        missing_in_bank = self.df_master[~self.df_master['_matched']].copy()
        for _, row in missing_in_bank.iterrows():
            res = row.to_dict()
            res['match_status'] = 'MISSING_PAYMENT'
            res['bank_name'] = res['sys_name']
            res['bank_amount'] = 0.0
            res['diff_val'] = -res['sys_amount']
            results.append(res)

        df_result = pd.DataFrame(results)
        return df_result

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
