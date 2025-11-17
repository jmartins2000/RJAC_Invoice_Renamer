import tkinter as tk
import sys
import os

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

def main():
    # Create the main window
    root = tk.Tk()
    root.title("RJAC Invoice Renamer")
    root.geometry("800x600")
    
    # Set window icon
    icon_path = get_resource_path("assets/logo_rounded.png")
    icon = tk.PhotoImage(file=icon_path)
    root.iconphoto(True, icon)
    
    # Add a simple label
    label = tk.Label(root, text="Welcome to RJAC Invoice Renamer", font=("Arial", 16))
    label.pack(pady=20)
    
    # Start the GUI event loop
    root.mainloop()

if __name__ == "__main__":
    main()

