# GUI icons

The following SVG icons are from the KDE Breeze icon theme, copyright KDE
and licensed under GNU LGPL version 3 or later:

- `labplot-xy-interpolation-curve.svg`
- `run-build-clean.svg`
- `system-run.svg`

See `COPYING-ICONS` and https://develop.kde.org/frameworks/breeze-icons/.

The structure-creation icons (`bulk_crystal.png`,
`structure_interface.png`, `surface_2d.svg`, and `database.svg`)
were created for Ase2sprkkr. They are not KDE Breeze icons.

The `sprkkr-orbital.svg` application icon is an original vector rendering of
the approved SPR-KKR artwork: glowing dotted `SPR`, a central three-dot
separator, and dotted `KKR` in front of a teal atomic-orbital background.
It is used as the Qt application icon for all top-level windows.

The structure editor tab icons (`structure-sites.svg`,
`structure-lattice.svg`, and `structure-transform.svg`) are also
original Ase2sprkkr artwork. They follow the existing structure-creation
icons' navy outlines, teal atomic highlights, and lightly shaded cells,
while remaining legible at the editor's 22 px tab size. The Overview and
The Embedded tab and embedding action reuse the existing packaged embedding
icon from the Guided workflow (currently `bulk_crystal.png`).

The run monitor's copy and save-as actions use original packaged fallback icons
(`copy-output.svg` and `save-output-as.svg`) when the desktop theme does not
supply `edit-copy` or `document-save-as`.

The Guided workflow's `calculation-gear.svg` and `result-graph.svg` are
original Ase2sprkkr icons, with the same navy, teal, and lightly shaded
palette as the structure editor. The `badge_icon` helper overlays one
common badge position on the unchanged object artwork: a clock for recent
structures/inputs/results, a circular arrow for SCF reconvergence, or a
plus for starting a new SCF calculation from the existing potential.
