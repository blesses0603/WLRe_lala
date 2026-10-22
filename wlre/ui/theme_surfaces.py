"""Shared wallpaper composition and bounded Tk widget background sampling.

A fixed design canvas keeps foreground artwork aligned between the dashboard
and smaller dialogs, instead of rescaling the image for each window shape.
"""
from PIL import Image, ImageDraw, ImageOps

REFERENCE_SIZE = (1280, 800)


def artwork_canvas(art, size=REFERENCE_SIZE):
    return ImageOps.fit(art, size, method=Image.Resampling.LANCZOS)


def window_background(canvas, width, height, *, main=False, outline=True,
                      dim_amount=None):
    if width < 1 or height < 1:
        raise ValueError("Window background must have positive dimensions")
    cw, ch = canvas.size
    if width <= cw and height <= ch:
        left, top = (cw - width) // 2, (ch - height) // 2
        image = canvas.crop((left, top, left + width, top + height))
    else:
        image = ImageOps.fit(canvas, (width, height), method=Image.Resampling.LANCZOS)
    # Keep the global wallpaper appearance unchanged. A dialog may opt into
    # a stronger tint without changing any other window's shared theme.
    amount = (.46 if main else .60) if dim_amount is None else dim_amount
    if not isinstance(amount, (int, float)) or not 0 <= amount <= 1:
        raise ValueError("Background dim amount must be within 0..1")
    image = Image.blend(image.convert('RGB'),
                        Image.new('RGB', (width, height), '#071526'),
                        amount)
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


def section_layers(boxes):
    """Describe only surfaces that can actually change the shared wallpaper.

    A normal label/button moving or being added needs its own crop refreshed,
    not a repaint of every other Tk PhotoImage in the window. Colored section
    panels, in contrast, affect the pixels behind multiple child controls.
    """
    result = []
    for widget, x, y, width, height, bounds in boxes:
        section = (getattr(widget, '_section_outline', False)
                   or type(widget).__name__ in ('HomeMap', 'GlassGroup', 'RecoveryPage')
                   or widget.winfo_class() == 'TLabelframe')
        fill = getattr(widget, '_surface_fill',
                       (9, 24, 39, 170) if section else None)
        if fill and width > 4 and height > 4:
            result.append((x, y, width, height, bounds, fill))
    return tuple(result)
