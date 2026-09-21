# Deprecated: the former Core Registry (frozen)

The OneShelf Source Registry now lives in **IPurplel/OneShelf-Adapters**, on its `registry` branch:
`https://raw.githubusercontent.com/IPurplel/OneShelf-Adapters/registry/index.json`.

This directory is a frozen snapshot, kept only so installations older than that move keep a working Registry.
It is no longer rebuilt. Current OneShelf reads the old default URL
(`https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json`) as the new one, without
changing anyone's `.env`. It will be removed in a later release.
