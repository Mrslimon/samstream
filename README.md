# Samstream

Home Assistant integration + Samsung Tizen TV app: control the TV and pop an RTSP camera
stream (with Arabic/English overlay text) on demand from automations, then return to
whatever was playing.

Status: **milestone 1 – skeleton**. See [docs/plan.md](docs/plan.md) for research, architecture and roadmap.

## Layout

| Path | What | Stack |
|---|---|---|
| `custom_components/samstream/` | HA integration | Python 3.14, async |
| `lib/aiosamstream/` | Protocol library (TV control, pure-Python sdb, wgt signing, WoL), published to PyPI | Python, `py.typed` |
| `tv-app/` | Samstream Tizen web app (AVPlay player + overlay) | TypeScript, Vite |
| `card/` | Optional Lovelace card | Lit, TypeScript |
| `tests/` | Integration tests (pytest-homeassistant-custom-component) | |

## Development

```sh
uv sync                       # lib + lint/type tools
uv run pytest lib/aiosamstream/tests
uv run ruff check . && uv run mypy lib/aiosamstream/src

cd tv-app && npm install
npm run typecheck && npm test && npm run build   # dist/ = unsigned wgt contents
```

Integration tests need Home Assistant, which does not install on native Windows:
run `uv sync --all-groups && uv run pytest` in WSL or rely on CI.

`manifest.json` `requirements` stays empty until `aiosamstream` is published (milestone 3);
until then install it into the HA container with `pip install -e lib/aiosamstream`.
