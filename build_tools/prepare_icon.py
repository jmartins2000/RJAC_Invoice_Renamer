"""
Complete icon preparation script for PyInstaller
- Makes white pixels transparent
- Rounds corners
- Converts to .ico with multiple sizes
"""
from PIL import Image, ImageDraw
import numpy as np

def prepare_icon(input_path, output_png_path, output_ico_path, radius=50, white_threshold=100):
    """Process logo: remove white, round corners, convert to .ico"""
    
    # Step 1: Load image and make white pixels transparent
    print("Step 1: Making white pixels transparent...")
    img = Image.open(input_path).convert("RGBA")
    data = np.array(img)
    
    red, green, blue, alpha = data[:,:,0], data[:,:,1], data[:,:,2], data[:,:,3]
    white_areas = (red > white_threshold) & (green > white_threshold) & (blue > white_threshold)
    data[white_areas] = [255, 255, 255, 0]
    
    img = Image.fromarray(data, 'RGBA')
    
    # Step 2: Apply rounded corners
    print("Step 2: Rounding corners...")
    mask = Image.new('L', img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), img.size], radius=radius, fill=255)
    
    output = Image.new('RGBA', img.size, (0, 0, 0, 0))
    output.paste(img, (0, 0), mask)
    output.save(output_png_path)
    print(f"  ✓ Saved rounded PNG to {output_png_path}")
    
    # Step 3: Convert to .ico with multiple sizes
    print("Step 3: Converting to .ico...")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    output.save(output_ico_path, format='ICO', sizes=sizes)
    print(f"  ✓ Saved .ico to {output_ico_path}")
    print(f"  Created {len(sizes)} sizes: {', '.join(f'{s[0]}x{s[1]}' for s in sizes)}")
    print("\n✓ Icon preparation complete!")

if __name__ == "__main__":
    prepare_icon(
        input_path='assets/logo.png',
        output_png_path='assets/logo_rounded.png',
        output_ico_path='assets/logo.ico',
        radius=50,
        white_threshold=100
    )

