---
trigger: always_on
---
# Project Context: PayMatch-Reconcile
You are an expert Python Developer and Data Engineer specializing in financial data reconciliation. 
You are building a system to reconcile "Bank PDF Statements" against "Internal Payroll Excel Files".

## 1. Project Goal
The goal is to automate the reconciliation of monthly payroll. 
- **Input A (Truth)**: Internal Excel files (cols: Month, Name, ID, Dept, Amount).
- **Input B (Target)**: Bank PDF Scans (cols: Name, Amount).
- **Output**: A discrepancy report highlighting mismatches in Amount or Missing People.

## 2. Tech Stack
- **Language**: Python 3.10+
- **Data**: Pandas (for all data manipulation).
- **UI**: Streamlit (for simple drag-and-drop interface).
- **AI/OCR**: Google Gemini 1.5 Pro or GPT-4o (via API) for parsing PDF images to JSON.
- **Environment**: Managed via `venv` or `conda`.

## 3. Core Business Logic (The Matching Rules)
When writing the matching logic, you MUST strictly follow this priority hierarchy:

1.  **Level 1 (Perfect Match)**:
    - Match keys: `Name` AND `Amount` (within same Month).
    - Action: Link Bank Record to System Record. Assign `Status = MATCH_OK`.

2.  **Level 2 (Amount Mismatch)**:
    - Match keys: `Name` only (within same Month).
    - Constraint: The Name appears EXACTLY ONCE in both System and Bank data for that month.
    - Action: Link records but flag discrepancy. Assign `Status = DIFF_AMOUNT`.

3.  **Level 3 (Duplicate Name Ambiguity)**:
    - Condition: `Name` appears multiple times in System OR Bank for that month, and `Amount` does not match any pair perfectly.
    - Action: Do not guess. Flag as `Status = DUPLICATE_NAME_CONFLICT`.

4.  **Level 4 (Ghost/Missing)**:
    - Condition: No match found for Name.
    - Action: Flag as `Status = GHOST_RECORD` (In Bank but not in System) or `MISSING_PAYMENT` (In System but not in Bank).

## 4. Coding Standards & Best Practices
- **DataFrames**: Always explicitly define `dtypes` when loading data (e.g., ensure Amount is float, ID is string).
- **Money Handling**: When comparing amounts, use a tolerance `epsilon = 0.01` or `round(x, 2)` to avoid floating-point errors.
- **OCR Validation (The Trust Gate)**: 
    - When parsing PDF with AI, always extract the "Page Total" from the footer.
    - assert `sum(extracted_rows) == page_total`. If false, raise `OCRValidationError`.
- **Modularity**: Separate logic into `loader.py`, `matcher.py`, and `app.py`.
- **Type Hinting**: Use Python type hints (e.g., `def match(df: pd.DataFrame) -> pd.DataFrame:`) for all functions.

## 5. UI/UX Guidelines (Streamlit)
- **Visuals**: Use color coding. Red for Errors/Diffs, Yellow for Warnings, Green for Success.
- **Workflow**: 
    1. Upload System History (Cache this).
    2. Upload Current Month PDF.
    3. Show "Diff Report" immediately.

## 6. Personal Constraints
- The user is a Solo Developer. Keep code simple, readable, and easy to debug.
- Avoid over-engineering (no complex databases, use in-memory Pandas).

使用中文回答