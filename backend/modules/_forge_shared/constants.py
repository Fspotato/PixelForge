"""PixelForge 共用常數。"""

DEFAULT_PROCESSORS = ["bg_remover", "perfect_pixel", "upscaler"]
SELECTABLE_PROCESSORS = [
    "bg_remover",
    "alpha_trimmer",
    "perfect_pixel",
    "palette_mapper",
    "color_quantizer",
    "upscaler",
]
DISABLED_PROCESSORS = {"grid_slicer"}
SYSTEM_PROCESSORS = {"thumbnail"}

SUPPORTED_VIEWS = {"top-down", "side-view", "isometric"}
SUPPORTED_MODES = {"single", "grid"}
SUPPORTED_UPSCALE_FACTORS = [5, 10, 20]

BASE_NEGATIVE_PROMPT = (
    "blurry, gradient, anti-aliased, 3D render, photorealistic, "
    "detailed background, scenery, environment, multiple objects, "
    "text, watermark, particles, complex lighting"
)
