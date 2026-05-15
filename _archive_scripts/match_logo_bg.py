from rembg import remove
from PIL import Image

# Setup paths
input_path = 'static/img/vestiq_original.png'
output_path = 'static/img/vestiq_logo_matched.png'
bg_color = (10, 25, 41)  # #0A1929 - The homepage background color

print(f"Processing {input_path}...")

try:
    # 1. Open original image
    with open(input_path, 'rb') as i:
        input_data = i.read()
    
    # 2. Remove background to get transparent version first
    # This ensures we lose the old blue gradient background completely
    subject_only_data = remove(input_data)
    
    # Save temp transparent to load as Image object
    with open("temp_transparent.png", "wb") as o:
        o.write(subject_only_data)
        
    # 3. Create background image
    foreground = Image.open("temp_transparent.png").convert("RGBA")
    background = Image.new("RGBA", foreground.size, bg_color + (255,)) # Fully opaque background
    
    # 4. Composite
    # Paste foreground on background using foreground alpha as mask
    combined = Image.alpha_composite(background, foreground)
    
    # 5. Save
    combined.save(output_path)
    print(f"✅ Created logo with matched background: {output_path}")

except Exception as e:
    print(f"❌ Error: {e}")
