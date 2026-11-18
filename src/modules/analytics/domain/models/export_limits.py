"""Row ceilings for generated workbooks (well below Excel's 1,048,576 rows).

Checked before the full result is loaded so a broad export fails fast instead of
exhausting memory while building the file.
"""

MAX_SHEET_DATA_ROWS = 200_000
MAX_WORKBOOK_DATA_ROWS = 500_000
