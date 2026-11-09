import shutil
import os
import re

class FileManager:
    """Service to handle file operations (copy, move, delete)"""
    
    @staticmethod
    def rename_invoice(source_path, dest_folder, new_filename, delete_original=False):
        """
        Renames (copies/moves) the invoice to the destination.
        
        Args:
            source_path (str): Full path to original file
            dest_folder (str): Target directory
            new_filename (str): New name (e.g. "2023-10-01_150.0.pdf")
            delete_original (bool): Whether to delete the source file after copying
            
        Returns:
            str | None: the new path if successful, None otherwise
        """
        try:
            # Ensure destination exists
            if not os.path.exists(dest_folder):
                os.makedirs(dest_folder)
            
            # Clean filename
            clean_name = FileManager._sanitize_filename(new_filename)
            ext = os.path.splitext(source_path)[1].lower() or ".pdf"
            if not clean_name.lower().endswith(ext):
                clean_name += ext
                
            dest_path = os.path.join(dest_folder, clean_name)
            if os.path.abspath(dest_path) == os.path.abspath(source_path):
                return dest_path  # already has this name
            
            # Handle duplicate names (append counter)
            counter = 1
            base_name = os.path.splitext(clean_name)[0]
            while os.path.exists(dest_path):
                dest_path = os.path.join(dest_folder, f"{base_name}_{counter}{ext}")
                counter += 1
            
            # Copy file
            shutil.copy2(source_path, dest_path)
            print(f"Processed: {dest_path}")
            
            # Delete original if requested
            if delete_original:
                os.remove(source_path)
                print(f"  Deleted original: {source_path}")
                
            return dest_path

        except Exception as e:
            print(f"Error renaming file {source_path}: {e}")
            return None

    @staticmethod
    def _sanitize_filename(filename):
        """Remove invalid characters from filename"""
        # Replace invalid chars with underscore
        return re.sub(r'[<>:"/\\|?*]', '_', filename)
