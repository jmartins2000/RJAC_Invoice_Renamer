"""Writes invoice rows to an .xlsx with the user's chosen columns."""
import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


FILE_COLUMNS = [("original_name", "Original name"), ("file_name", "File name"), ("folder", "Folder")]


def chosen_file_columns():
    from src.services import settings
    on = settings.load().get("excel_columns") or {}
    return [(label, key) for key, label in FILE_COLUMNS if on.get(key)]


class ExcelExporter:
    @staticmethod
    def export(rows, field_defs, output_path, extra_columns=None):
        """rows: dicts with 'values' (field key → value) plus original_name / file_name / folder."""
        if extra_columns is None:
            extra_columns = chosen_file_columns()
        try:
            cols = [f for f in field_defs if f.enabled and f.in_excel]
            wb = Workbook()
            ws = wb.active
            ws.title = "Invoices"
            ws.append([f.label for f in cols] + [name for name, _ in extra_columns])
            for cell in ws[1]:
                cell.fill = PatternFill(start_color="204E27", end_color="204E27", fill_type="solid")
                cell.font = Font(bold=True, color="FFFFFF")
                cell.alignment = Alignment(horizontal="center", vertical="center")
            for row in rows:
                vals = row.get("values", {})
                out = []
                for f in cols:
                    v = vals.get(f.key)
                    if f.type == "date" and v:
                        try:
                            v = datetime.date.fromisoformat(str(v)[:10])
                        except ValueError:
                            pass
                    out.append(v if v not in (None, "") else None)
                ws.append(out + [row.get(k, "") for _, k in extra_columns])
            for i, f in enumerate(cols, start=1):
                for cell in ws.iter_cols(min_col=i, max_col=i, min_row=2):
                    for c in cell:
                        if f.type == "date":
                            c.number_format = "yyyy-mm-dd"
                        elif f.type == "number":
                            c.number_format = "#,##0.00"
            for column in ws.columns:
                width = max((len(str(c.value)) for c in column if c.value is not None), default=8)
                ws.column_dimensions[column[0].column_letter].width = min(width + 2, 50)
            ws.freeze_panes = "A2"
            wb.save(output_path)
            return True
        except Exception as e:
            print(f"Error exporting to Excel: {e}")
            return False
