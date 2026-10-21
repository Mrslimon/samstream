# Icons: what to replace

All of these are placeholders written by `scripts/make_placeholder_icons.py`.
Overwrite the files with your artwork; keep the names, formats and sizes.

## Home Assistant (integration page, device page, Add integration dialog)

HA 2026.5+ loads brand images straight from the integration folder:
`custom_components/samstream/brand/`

| File | Size | Notes |
|---|---|---|
| `icon.png` | 256×256 | Square, transparent background. Required. |
| `icon@2x.png` | 512×512 | Same icon, hDPI. |
| `logo.png` | landscape preferred, shortest side 128–256 px | Icon + wordmark. Falls back to `icon.png`. |
| `logo@2x.png` | double of `logo.png` | Falls back to `logo.png`, then `icon.png`. |
| `dark_icon.png`, `dark_logo.png`, `dark_icon@2x.png`, `dark_logo@2x.png` | as above | Optional versions for HA's dark theme. Missing ones fall back to the light images. |

PNG only, trimmed (no empty margins), transparent background. After replacing:
`uv run python scripts/ha_dev.py deploy`, then reload the browser tab (the
frontend caches brand images).

## Samsung TV (Apps row and app launcher)

| File | Size | Notes |
|---|---|---|
| `tv-app/public/icon.png` | 512×423 | Samsung's TV app icon size. Opaque background works best on the TV's Apps panel. |

The icon is part of the app package, so it reaches the TV with the next
install. Bump `version` in `tv-app/public/config.xml`, then run
`uv run python scripts/bundle_tv_app.py` and deploy; the Samstream TV app
update entity in HA offers the new version.
