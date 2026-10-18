"""Shared wallpaper composition and bounded Tk widget background sampling.

A fixed design canvas keeps foreground artwork aligned between the dashboard
and smaller dialogs, instead of rescaling the image for each window shape.
"""
from PIL import Image, ImageDraw, ImageOps

REFERENCE_SIZE = (1280, 800)


def artwork_canvas(art, size=REFERENCE_SIZE):
    return ImageOps.fit(art, size, method=Image.Resampling.LANCZOS)


def window_background(canvas, width, height, *, main=False, outline=True):
    if width < 1 or height < 1:
        raise ValueError("Window background must have positive dimensions")
    cw, ch = canvas.size
    if width <= cw and height <= ch:
        left, top = (cw - width) // 2, (ch - height) // 2
        image = canvas.crop((left, top, left + width, top + height))
    else:
        image = ImageOps.fit(canvas, (width, height), method=Image.Resampling.LANCZOS)
    image = Image.blend(image.convert('RGB'),
                        Image.new('RGB', (width, height), '#071526'),
                        .46 if main else .60)
    result = image.convert('RGBA')
    if outline and width >= 5 and height >= 5:
        border = Image.new('RGBA', result.size)
        ImageDraw.Draw(border).rounded_rectangle(
            (1, 1, width - 2, height - 2), radius=20,
            outline=(98, 201, 224, 200), width=1)
        result = Image.alpha_composite(result, border)
    return result


def visible_bounds(x, y, width, height, viewport, ancestors=()):
    """Intersect the widget, window and all enclosing parent frames."""
    left, top = max(0, x), max(0, y)
    right, bottom = min(viewport[0], x + width), min(viewport[1], y + height)
    for ax, ay, aw, ah in ancestors:
        left, top = max(left, ax), max(top, ay)
        right, bottom = min(right, ax + aw), min(bottom, ay + ah)
    return (left, top, right, bottom) if left < right and top < bottom else None


def widget_crop(backing, x, y, width, height, bounds, *, base='#101c2b'):
    """Never sample pixels outside the window or clipped parent widgets."""
    tile = Image.new('RGBA', (width, height), base)
    if bounds:
        left, top, right, bottom = bounds
        tile.paste(backing.crop(bounds), (left - x, top - y))
    return tile


def draw_section(layer, x, y, width, height, bounds, fill):
    """Round the original panel corners, then clip drawing to ancestors."""
    if bounds is None or width <= 4 or height <= 4:
        return
    tile = Image.new('RGBA', (width, height))
    ImageDraw.Draw(tile).rounded_rectangle(
        (1, 1, width - 2, height - 2), radius=14, fill=fill)
    left, top, right, bottom = bounds
    layer.alpha_composite(tile.crop((left-x, top-y, right-x, bottom-y)),
                          dest=(left, top))
