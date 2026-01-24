📝 产品需求文档 (PRD): 银行流水与薪资自动核对系统
Project Code: PayMatch-Reconcile

Version: v1.0 (MVP)

Owner: You

1. 项目背景 & 痛点
目前需要核对 2024.10 - 2026.01 期间，每月 500-700 人的工资发放情况。

输入 A（真理端）: 内部系统导出的 Excel（含工号、部门、实发金额），分散在 16 个月、数十个分表中。

输入 B（核对端）: 银行流水 PDF（含扫描件），只有姓名、金额，无工号，存在重名。

核心痛点: 手工核对量大（约 1 万条数据）、扫描件识别难、重名无法区分、金额差异查找困难。

2. 产品目标
自动化清洗: 一键合并所有历史系统 Excel，建立标准数据库。

AI 数字化: 利用多模态大模型（LLM）精准提取扫描件 PDF 数据。

智能匹配: 自动关联“银行流水”与“系统数据”，自动填充工号。

异常驱动: 只输出差异报告。实现“无消息就是好消息”，仅需人工处理 <5% 的异常数据。

3. 系统架构与流程
技术栈: Python, Pandas, Streamlit (UI), Gemini/GPT-4o (Vision API)

核心流程:数据摄入 -> AI 提取与自检 -> 多级匹配引擎 -> 差异可视化

4. 功能模块详情
模块一：系统数据治理 (Master Data Loader)
目标: 将零散的 Excel 变为可检索的“真理库”。

输入: 包含所有月份、部门 Excel 的文件夹路径。

处理逻辑:

遍历读取所有 .xlsx。

字段标准化: 强制重命名关键列 -> sys_name (姓名), sys_amount (实发), sys_id (工号), sys_dept (部门)。

标签注入: 根据文件名/文件夹名，自动添加 month (月份) 列。

数据指纹: 生成唯一 Key sys_uid = month + sys_name + sys_dept。

输出: df_master (全量系统数据表)。

模块二：AI 智能提取器 (AI PDF Extractor)
目标: 解决扫描件识别，并确保数据可信。

输入: 银行流水 PDF (扫描件/电子件)。

核心功能:

PDF 转图: 将 PDF 切割为图片。

Vision API 调用: 发送图片给 AI。

Prompt 重点: 要求返回 JSON；要求提取页脚的“本页合计金额”。

置信度校验 (The Trust Gate):

逻辑: Sum(提取的所有行金额) 是否等于 页脚合计金额？

Pass: 进入下一步。

Fail: 标记该页为 OCR_ERROR，直接在 UI 报错，不进入核对流程。

输出: df_bank (清洗后的银行流水表)。

模块三：级联匹配引擎 (Cascade Matching Engine) —— 核心算法
目标: 在没有工号的情况下，把银行流水对上人，并找出差异。

匹配逻辑 (按优先级执行):

Level 1: 完美匹配 (Confidence: High)

条件: 在同月份中，银行姓名 == 系统姓名 且 银行金额 == 系统金额。

动作: 视为匹配成功，自动填入工号，标记状态 MATCH_OK。

注意: 如果同名且同金额的人有多个（极其罕见），只要数量对得上（2个银行记录 vs 2个系统记录），也视为 OK。

Level 2: 金额差异匹配 (Confidence: Medium)

条件: 在同月份中，银行姓名 == 系统姓名，但金额对不上。且该姓名在当月系统中仅出现一次。

动作: 视为匹配成功（找到了人），但金额错误。标记状态 DIFF_AMOUNT。

Level 3: 重名冲突 (Confidence: Low)

条件: 在同月份中，银行姓名 在系统中对应多个人（重名），且金额都无法完美匹配 Level 1。

动作: 无法确定是谁。标记状态 DUPLICATE_NAME，留给人工。

Level 4: 幽灵数据 (Confidence: None)

条件: 银行里有这人，系统里完全找不到。

动作: 标记状态 GHOST_RECORD（可能是离职补发或名字打错）。

模块四：交互界面 (Streamlit UI)
目标: 让你只处理红色的部分。

Page 1: 数据准备

按钮: "加载系统历史数据" (显示读取了多少个文件，共多少人)。

上传: "上传本月银行流水 PDF"。

Page 2: 核对看板 (Dashboard)

概览卡片: 总笔数 / 匹配成功数 / 异常笔数(重点)。

异常详情表 (可编辑):

筛选器: 只看 DIFF_AMOUNT, DUPLICATE_NAME, GHOST_RECORD。

显示列: 姓名, 银行金额, 系统金额, 差额, 系统部门(供参考)。

导出: 按钮 "下载差异报告 (.xlsx)"。
5. 数据结构设计 (Reference)
建议在 Pandas 中维护这两张宽表：

表 A: Master_System_Table (参考库) | Month | Dept | Name | Emp_ID | Amount | Unique_Key | | :--- | :--- | :--- | :--- | :--- | :--- | | 2024-10 | 销售部 | 张三 | 1001 | 5000.0 | 202410_张三_销售 |

表 B: Bank_Transaction_Table (工作流表) | Month | Bank_Name | Bank_Amount | Matched_Sys_ID | Match_Status | Diff_Val | | :--- | :--- | :--- | :--- | :--- | :--- | | 2024-10 | 张三 | 4800.0 | 1001 | DIFF_AMOUNT | -200 | | 2024-10 | 李四 | 6000.0 | None | GHOST_RECORD | N/A |

6. 开发实施计划 (Roadmap)
鉴于你只有一个人，我们分两步走：

Phase 1: 脚本跑通 (Day 1)

不写界面。

写好 loader.py (读 Excel) 和 ocr.py (读 PDF)。

写好 matcher.py 跑出结果到 Excel。

验收标准: 能跑通一个月的数据，并生成 Excel 差异表。

Phase 2: 界面交互 (Day 2)

套用 Streamlit。

增加“页脚金额校验”的可视化报错。

验收标准: 哪怕扫描件识别错了，系统能报警提示你。

💡 给开发者的特别备注
关于 PDF 识别: 扫描件识别是最大瓶颈。建议使用 Gemini 1.5 Pro (免费额度够用且 Token 窗口大) 或 GPT-4o。Prompt 一定要包含：“如果数字模糊不清，请标记为 null，不要瞎猜”。

隐私脱敏: 虽然是自己用，但发给 AI API 前，最好确认代码里没有把类似“身份证号”这种极度敏感字段发出去（银行流水通常只有名字金额账号，相对安全）。