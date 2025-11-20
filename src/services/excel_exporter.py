from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
import os

class ExcelExporter:
    """Service to export invoice data to Excel spreadsheet"""
    
    @staticmethod
    def export_to_excel(data_list, output_path):
        """
        Export invoice data to an Excel file.
        
        Args:
            data_list: List of dicts with keys: 'date', 'supplier', 'total_value'
            output_path: Full path to output .xlsx file
            
        Returns:
            bool: True if successful
        """
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Invoice Data"
            
            # Headers
            headers = ["Date", "Supplier", "Value"]
            ws.append(headers)
            
            # Style headers
            header_fill = PatternFill(start_color="3d9d46", end_color="3d9d46", fill_type="solid")
            header_font = Font(bold=True, color="FFFFFF")
            
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            
            # Data rows
            for item in data_list:
                ws.append([
                    item.get('date', ''),
                    item.get('supplier', ''),
                    item.get('total_value', '')
                ])
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Save
            wb.save(output_path)
            print(f"✓ Excel exported: {output_path}")
            return True
            
        except Exception as e:
            print(f"Error exporting to Excel: {e}")
            return False

