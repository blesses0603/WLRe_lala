"""CPU transcription of reviewed UI_ProfilePhotoWithMask (1296 default variant).
No game code executes. Input textures must be verified by the caller.
The explicit gamma projection follows the verified official mobile UI profile,
which is the user's reference. It does NOT assert that every PC Unity project
uses gamma rendering, nor claim GPU/framebuffer screenshot equivalence.
The returned image stores straight alpha (reviewed SrcAlpha/OneMinusSrcAlpha).
"""
import math

COLOR_PROFILE = "official-mobile-gamma-1296"

PARTS = (
    "_1_0_c_Color", "_1_1_HairColor", "_1_2_SkinColor",
    "_2_0_e_Color0", "_2_1_e_Color1", "_2_2_e_Color2",
    "_3_0_e_Color3", "_3_1_e_Color4", "_4_2_a_Color",
    "_3_2_s_Color", "_4_0_w_Color0", "_4_1_w_Color1", "_5_0_p_Color",
)
GROUPS = {
    1: PARTS[:3], 2: PARTS[3:6],
    3: ("_3_0_e_Color3", "_3_1_e_Color4", "_3_2_s_Color"),
    4: ("_4_0_w_Color0", "_4_1_w_Color1", "_4_2_a_Color"),
    5: ("_5_0_p_Color", "_13_EyeColor_"),
}
def sat(x):
    return min(1.0, max(0.0, x))

def palette_vectors(palettes, defaults=None):
    result = {p: (4.0, 4.0, 4.0) for p in (*PARTS, "_13_EyeColor_")}
    if defaults:
        for key, value in defaults.items():
            if key in result:
                if len(value) < 3 or not all(math.isfinite(float(v)) for v in value[:3]):
                    raise ValueError("Invalid material color")
                result[key] = tuple(float(v) for v in value[:3])
    for group, value in palettes.items():
        if type(group) is not int or group not in GROUPS or type(value) is not int or not 0 <= value <= 999999999:
            raise ValueError("Invalid portrait palette")
        chunks = (value // 1000000, value // 1000 % 1000, value % 1000)
        for key, chunk in zip(GROUPS[group], chunks):
            result[key] = (chunk // 100, chunk // 10 % 10, chunk % 10)
    return result

def shade_pixel(base, mask, vectors):
    """Normalized RGBA source/mask to shader output before circular UI mask."""
    color = [0.4, 0.4, 0.4]
    labels = [(0, x) for x in (.196, .392, .588, .784, .980)]
    labels += [(1, x) for x in (.196, .392, .588, .784, .980)]
    labels += [(2, x) for x in (.196, .392, .588)]
    for part, (channel, label) in zip(PARTS, labels):
        weight = sat(1.0 - (math.sqrt(3.0 * (label - mask[channel]) ** 2) - .15) * 100000.0)
        color = [c + weight * (v * .1 - c) for c, v in zip(color, vectors[part])]
    normal = []
    eye = []
    for b, c, e in zip(base[:3], color, vectors["_13_EyeColor_"]):
        overlay = 1.0 - (2.0 - 2.4*c)*(1.0-b) if c > .416667 else 2.4*c*b
        normal.append(b + .55*(overlay-b))
        eye_overlay = 1.0-(2.0-.22*e)*(1.0-b) if .11*e > .5 else .22*e*b
        eye.append(sat(b + .55*(eye_overlay-b)))
    normal.append(.45*base[3])
    eye.append(sat(.45*base[3]))
    eye_weight = sat(1.0 - (math.sqrt(mask[0]**2+mask[1]**2+(1.0-mask[2])**2)-.5)*3.333333)
    mixed = [n*base[3]+eye_weight*(e-n*base[3]) for n,e in zip(normal,eye)]
    output = [sat(x+.2*(3.0*x*x-2.0*x*x*x-x)) for x in mixed]
    output[3] += base[3]
    return output

def circle_mask(u, v, mask_clip, edge_length):
    inward = 1.0-math.hypot((u-.5)*2.0, (v-.5)*2.0)
    if edge_length == 0:
        return float(inward > mask_clip), 0.0
    def smooth(x):
        x = sat(x)
        return x*x*(3.0-2.0*x)
    outer = smooth((inward-(mask_clip-edge_length))/edge_length)
    inner = smooth((inward-(mask_clip-.5*edge_length))/(.5*edge_length))
    return outer, sat(2.0*(outer-inner))

def render(base, mask, palettes, material):
    """Return native-size RGBA. Only the verified unkeyworded shader is supported."""
    from PIL import Image
    if (base.mode != "RGBA" or mask.mode != "RGBA" or base.size != mask.size
            or base.size != (256,256)):
        raise ValueError("Unsupported portrait texture geometry")
    if (material.get("color_profile") != COLOR_PROFILE
            or material.get("shader") != "UI_ProfilePhotoWithMask"
            or material.get("keywords") not in ([], ())
            or material.get("use_shape_mask") != 0):
        raise ValueError("Portrait shader variant is not reviewed")
    clip = float(material["mask_clip"])
    edge = float(material["edge_length"])
    if not math.isfinite(clip) or not -1 <= clip <= 1 or not math.isfinite(edge) or not 0 <= edge <= 1:
        raise ValueError("Invalid portrait circular mask")
    vectors = palette_vectors(palettes, material.get("colors"))
    pixels = []
    width,height = base.size
    base_pixels = base.get_flattened_data() if hasattr(base, "get_flattened_data") else base.getdata()
    mask_pixels = mask.get_flattened_data() if hasattr(mask, "get_flattened_data") else mask.getdata()
    for i,(b,m) in enumerate(zip(base_pixels, mask_pixels)):
        out = shade_pixel([v/255.0 for v in b],[v/255.0 for v in m],vectors)
        alpha, border = circle_mask((i%width+.5)/width,(i//width+.5)/height,clip,edge)
        out[:3] = [v+border*(1.0-v) for v in out[:3]]
        out[3] *= alpha
        pixels.append(tuple(round(sat(v)*255) for v in out))
    result = Image.new("RGBA",base.size)
    result.putdata(pixels)
    return result
