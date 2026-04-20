Placeholder for extension icons (16/48/128 PNG).

Not required for the MVP — Chrome falls back to the puzzle-piece icon
when icons are absent or omitted from the manifest. Leaving them out
keeps the unpacked load clean (missing-file warnings would otherwise
appear if we declared icons in the manifest without actual files).

When publishing to the Chrome Web Store, drop in:
  16.png   16x16  toolbar small
  48.png   48x48  extensions page
  128.png  128x128 web store + install prompt

Then add to manifest.json:
  "icons": { "16": "icons/16.png", "48": "icons/48.png", "128": "icons/128.png" }
