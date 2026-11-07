# Official skill icon snapshot

`wlre/resources/assets/skill-icons/skill-icons.sqlite3` stores 306 original official
Sprite PNGs from the public 1.3.23 MainPackage atlas. It contains three tables:

- `metadata`: source URL, version, source bundle SHA-256, schema, mapping evidence.
- `provenance`: exact asset path, bundle, Unity path ID, dimensions, byte length,
  and PNG SHA-256 for each sprite name.
- `images`: original PNG bytes keyed by sprite name.

The reviewed `SkillData.lua` plaintext SHA-256 is
`962e95717ddce2c8d56da622df0e578afbf7bd6c63a19e53a809fb4a283f3228`.
Its `GetSkillIcon` maps `GId` to `icon_sk{GId}s`. Skill ID is not a substitute.
The reviewed decoder checked the encrypted source and plaintext hashes; no
client Lua or codec secrets are packaged with these images.

The loader opens SQLite read-only, bounds database and image sizes, validates
schema, PNG byte count, SHA-256 and dimensions, and retains at most 128 decoded
images. Missing or corrupt assets return no icon. UI scaling retains original
colors and transparency; no synthetic fallback artwork is used.

`SkillIcons(master).get(skill_data, size=64)` returns a Tk image or `None`.
Callers retain image references for visible cards and call `close()` when done.
`skill_icon_image` returns an independent PIL image for headless tests.

The separate combat catalog resolves `Desc` through official TextData as
`description`. Its normalized cache version is `combat-reviewed-v2`.
