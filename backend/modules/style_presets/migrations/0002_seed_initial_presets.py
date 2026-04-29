from django.db import migrations

PRESETS = [
    {
        "key": "forest",
        "name": "forest",
        "description": "森林、自然、奇幻 RPG 物件，明亮綠色系。",
        "resolution": "16x16 resolution",
        "palette_hex": [
            "#0c120a",
            "#263020",
            "#728068",
            "#f0eade",
            "#1e4010",
            "#58a830",
            "#483018",
            "#a07840",
            "#184038",
            "#48a088",
            "#b8c848",
            "#6890a0",
            "#d05830",
            "#c8a878",
            "#182018",
            "#e8d820",
        ],
        "primary_palette": (
            "forest green (#58a830), deep forest (#1e4010), "
            "mid olive (#263020), lime green (#b8c848)"
        ),
        "shadow_palette": "near black (#0c120a), deep shadow (#182018), dark earth (#483018)",
        "accent_palette": (
            "parchment (#f0eade), sandy earth (#c8a878), "
            "tawny brown (#a07840), autumn orange (#d05830)"
        ),
        "effect_palette": "teal water (#48a088), sky blue (#6890a0), sunlight yellow (#e8d820)",
        "art_direction": (
            "single nature or forest themed item with vibrant green tones, fantasy RPG game asset"
        ),
        "negative": (
            "dark atmosphere, urban elements, technology, modern buildings, "
            "realistic rendering, trees, grass field, forest scenery, landscape, "
            "environment, multiple items"
        ),
    },
    {
        "key": "dungeon",
        "name": "dungeon",
        "description": "地城物件或道具，深色氣氛、石材與復古 RPG 感。",
        "resolution": "16x16 resolution",
        "palette_hex": [
            "#0e0c11",
            "#2c2733",
            "#6a6275",
            "#ece3d5",
            "#3b2314",
            "#9a6838",
            "#6d2d0c",
            "#e0701e",
            "#293040",
            "#667888",
            "#c88e5e",
            "#4e5668",
            "#961e1e",
            "#c89e7e",
            "#1a1320",
            "#ff4a00",
        ],
        "primary_palette": "dark stone gray (#6a6275), slate gray (#4e5668), warm brown (#9a6838)",
        "shadow_palette": (
            "near black (#0e0c11), deep void (#1a1320), "
            "dark purple-black (#2c2733), dark earth (#3b2314)"
        ),
        "accent_palette": (
            "aged parchment (#ece3d5), worn leather (#c89e7e), "
            "burnt sienna (#c88e5e), dark rust (#6d2d0c)"
        ),
        "effect_palette": "ember orange (#e0701e), fire red (#ff4a00), blood red (#961e1e)",
        "art_direction": (
            "single dungeon item or prop with dark atmospheric lighting and stone texture, "
            "retro RPG game asset"
        ),
        "negative": (
            "modern graphics, 3D rendering, realistic lighting, photorealistic, "
            "room, corridor, wall, floor tiles, scenery, environment, multiple items"
        ),
    },
    {
        "key": "scifi",
        "name": "scifi",
        "description": "科幻資產，科技、金屬、能源效果方向。",
        "resolution": "16x16 resolution",
        "palette_hex": [
            "#080e1c",
            "#1c2840",
            "#506888",
            "#e0e8f0",
            "#004858",
            "#00c8e8",
            "#580040",
            "#e8006c",
            "#1a3060",
            "#4080c8",
            "#2840a8",
            "#384858",
            "#a060d0",
            "#a0a0b8",
            "#0c0818",
            "#40ff80",
        ],
        "primary_palette": (
            "dark steel (#506888), metallic blue-gray (#a0a0b8), mid space blue (#1c2840)"
        ),
        "shadow_palette": "void black (#080e1c), deep indigo (#0c0818), midnight blue (#1a3060)",
        "accent_palette": (
            "cold white (#e0e8f0), deep teal (#004858), electric blue (#2840a8), "
            "medium blue (#4080c8)"
        ),
        "effect_palette": (
            "neon cyan (#00c8e8), neon green (#40ff80), neon magenta (#e8006c), "
            "neon purple (#a060d0)"
        ),
        "art_direction": (
            "single futuristic sci-fi item or prop with neon glow and metallic surfaces, "
            "cyberpunk game asset"
        ),
        "negative": (
            "natural elements, organic textures, medieval, fantasy, realistic rendering, "
            "photorealistic, room interior, space station, floor, wall panels, scenery, "
            "environment, multiple items"
        ),
    },
    {
        "key": "arcane_craft",
        "name": "arcane_craft x16",
        "description": "魔法工藝與奧術製作感的 16x16 像素風資產。",
        "resolution": "16x16 resolution",
        "palette_hex": [
            "#9040d8",
            "#786898",
            "#3c1878",
            "#0e0818",
            "#281840",
            "#e8a820",
            "#604008",
            "#d83030",
            "#00b8c8",
        ],
        "primary_palette": "royal purple (#9040d8), soft lavender (#786898), deep violet (#3c1878)",
        "shadow_palette": "near-black purple (#0e0818), dark indigo (#281840)",
        "accent_palette": "antique gold (#e8a820), dark bronze (#604008), arcane crimson (#d83030)",
        "effect_palette": "bright arcane cyan (#00b8c8)",
        "art_direction": (
            "fantasy entity or object with soft, organic shapes, subtle mystical patterns "
            "inspired by ancient architecture and nature, gentle color palette with warm "
            "highlights, smooth surfaces, fantasy RPG aesthetic"
        ),
        "negative": (
            "modern technology, realistic rendering, photorealistic, room interior, "
            "workshop, table, floor"
        ),
    },
]


def seed_presets(apps, schema_editor):
    StylePreset = apps.get_model("style_presets", "StylePreset")
    for preset in PRESETS:
        StylePreset.objects.update_or_create(
            key=preset["key"],
            defaults={**preset, "is_active": True},
        )


def unseed_presets(apps, schema_editor):
    StylePreset = apps.get_model("style_presets", "StylePreset")
    StylePreset.objects.filter(key__in=[preset["key"] for preset in PRESETS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("style_presets", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_presets, unseed_presets),
    ]
