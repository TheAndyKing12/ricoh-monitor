from PIL import Image, ImageDraw

for size in [192, 512]:
    img = Image.new('RGB', (size, size), color='#0f172a')
    d = ImageDraw.Draw(img)
    margin = size // 8
    d.ellipse([margin, margin, size-margin, size-margin], fill='#3b82f6')
    img.save(f'icon-{size}.png')
    print(f'icon-{size}.png creado')