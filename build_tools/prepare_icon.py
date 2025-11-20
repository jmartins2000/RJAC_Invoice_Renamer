"""
Icon converter for PyInstaller
- Converts the new high-quality PNG to .ico for the executable
"""
from PIL import Image
import os

def convert_icon(input_path, output_ico_path):
    """Convert PNG to .ico with multiple sizes"""
    
    if not os.path.exists(input_path):
        print(f"Error: Input file {input_path} not found!")
        return

    print("Converting PNG to .ico...")
    img = Image.open(input_path)
    
    # Step: Convert to .ico with multiple sizes
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(output_ico_path, format='ICO', sizes=sizes)
    print(f"  ✓ Saved .ico to {output_ico_path}")
    print(f"  Created {len(sizes)} sizes: {', '.join(f'{s[0]}x{s[1]}' for s in sizes)}")
    print("\n✓ Icon preparation complete!")

if __name__ == "__main__":
    convert_icon(
        input_path='assets/RJAC-logo.png',
        output_ico_path='assets/RJAC-logo.ico'
    )
