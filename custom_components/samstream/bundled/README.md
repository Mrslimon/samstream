The built, unsigned Samstream TV app (`samstream-<version>.wgt`) is copied here by
`npm run bundle` in `tv-app/`. The integration signs it per TV and installs it over sdb.

`notifier.tpk` is the unsigned native notifier (notifications and the corner camera), built
and copied here by `python scripts/bundle_notifier.py`. The integration writes the TV's key
into it and signs it together with the web app.
