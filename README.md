# ASE2SPRKKR GUI

A PyQt6 desktop interface for creating and editing ASE structures, configuring
SPR-KKR calculations, and exploring calculation results through ASE2SPRKKR.

## Install

Install this beta alongside the matching released ASE2SPRKKR and KKRunner packages:

```bash
python -m pip install --pre ase2sprkkr-gui
```

## Run

```bash
ase2sprkkr-gui
ase2sprkkr-gui Fe.cif             # open a structure or potential file
ase2sprkkr-gui calculation.out    # open a SPR-KKR calculation result
ase2sprkkr-gui results/           # import output files from a directory
ase2sprkkr-gui --open-last        # open the latest existing recent structure
ase2sprkkr-gui --job RUN_ID       # follow an active persistent job or open its result
ase2sprkkr-gui --output data.txt  # disambiguate a nonstandard file extension
```

The same options work with `ase2sprkkr gui`. A positional filename is
interpreted as an output for `.out`/`.log`, input parameters for
`.inp`/`.in`, and otherwise as a structure. Use `--structure FILE`,
`--input FILE`, or `--output PATH` to choose explicitly. `--open-last`
uses the recent **structure** history (skipping files that no longer exist),
even when a calculation output was opened more recently. Use `--job ID`
to resume monitoring an unfinished persistent calculation or open the
saved result of a finished one. The monitor displays the job ID when it
is available.

The GUI requires the ASE2SPRKKR Python backend. Running actual SPR-KKR
calculations also requires a separately installed SPR-KKR executable.

If a calculation cannot start, for example because its executable is missing
or not executable, the GUI shows the reason and returns to execution-profile
selection with the previous profile, directory and run names preserved.
Choosing another profile requires confirming a new launch.

## Development

Source: https://github.com/ase2sprkkr/ase2sprkkr-gui

## Embedded cluster editor (development)

The GUI `cluster` branch requires the matching ASE2SPRKKR backend `cluster`
branch, which provides `HostSite`, `EmbeddingSymmetry` and
`SPRKKRAtoms.from_embedding`.

From a loaded 3D host or a supported 2D host, choose
**Structure → Build Embedded Cluster** (or the Guided workflow action). The
dialog edits explicit host-site occupations and displacements, supports
centre-preserving symmetry, and adds surrounding host sites by distance or
coordination shell. Cancel does not change the current structure.

The two previews have distinct scopes. The editable detail and the site table
show the **selected host cell**. For a 2D host this includes the complete
transition region of that one in-plane cell, excluding the left/right leads
and vacuum. The context preview shows the surrounding periodic cells and the
entire cluster, including cluster sites outside the displayed host box. Its
scope can be restricted to the current **cell layer** in 3D (all basis sites
with the fixed n1/n2/n3 index for the chosen map plane, not a single atomic plane),
or to the repeated transition region in 2D. The bulk host box shows at most five layers;
the underlying host remains infinite. When cluster sites or symmetry previews
extend beyond this box, their host cells and neighbouring cells are also shown,
so the highlighted sites are not detached markers outside the host context.
For a 2D host the gaps between those cells are filled to produce a continuous
host region, rather than separate patches surrounding individual markers.

The map stays centred at **(0,0)**. **Wigner–Seitz rings** counts steps in the
Voronoi adjacency graph of the actual translation lattice: two translation
points are neighbours when their Wigner–Seitz cells share an edge, rather than
just a vertex. Zero shows one cell; one shows seven cells for the triangular
GeTe lattice, or five for an orthogonal lattice, including unequal rectangular
axes. Successive rings add neighbours of the preceding rings. Neighbourhoods
use the physical lattice metric, independently of the display projection;
the drawn primitive cells remain their actual parallelograms. This is separate
from **Use as symmetry centre**, which chooses a physical host site for point symmetry and
radius/shell expansion. A cell can contain many inequivalent sites, so choosing
that physical centre remains meaningful even within cell (0,0).

The upper row has three resizable columns: host cells, sites in the selected
cell, and site editing. Include, Exclude and Use as symmetry centre sit beneath
the site table. Changing the ring count updates the map and context preview
together immediately; the detail remains on the selected cell.

Select a cell in the lattice map, then sites in its table or detail preview. The
map preserves projected lattice angles and length ratios; the longer projected
vector has length one. In 2D it uses an orthonormal basis of the surface plane.
In 3D, **XY**, **XZ**, and **YZ** are Cartesian projections of cell planes varying
respectively n1/n2, n1/n3, and n2/n3; the remaining index is controlled by the
layer spinbox. Switching planes preserves the selected cell and site. An edge-on
plane is identified explicitly instead of showing overlapping clickable cells.
The 2D cell outline retains the central region's actual shear and its offset
after the left lead, using the same Cartesian coordinates as the native atoms.
Site numbers match between the table and detail; the outlined reference cell also
locates the detail within the context. Gold and purple rings indicate the
selected site and its symmetry preview, independently of blue/orange fills for
included/modified cluster sites. Both previews support 3D rotation and
Cartesian XY/XZ/YZ projections. Dragging rotates without changing the selected
site; a click selects the nearest marker (the frontmost one if they overlap).
The wheel zooms and a middle-button drag pans. For obscured sites, change
projection or select the table row. The selected site's number is always shown;
**All site numbers** labels the other sites as well. The vertical divider lets
you enlarge the previews, and **Fit** restores their framing. Projection and
Fit controls sit on the outer sides: left of the detail, right of the context.
The context scope selector sits above its projection and Fit controls; a shared
colour legend runs below both previews. The orthographic
camera fits the actual projected geometry to the full rectangular canvas on
resize, preserving physical aspect without the unused 3D bounding cube.

Focusing the radius, coordination-shell count, or its Add button previews that
expansion in both views. New sites have green fills; already included sites keep
their blue/orange fills. The expansion panel reports the candidate and new-site
counts. Previewing uses the same site selection as Add and does not modify the
cluster. Values update after a short debounce, and leaving these controls clears
the preview. Oversized or invalid selections show an inline message.

The site table supports Ctrl/Shift multiple selection. Occupation and
displacement have independent frames; their edits apply to every selected site
(and their symmetry targets when enabled). Mixed values are identified and the
controls show the active site's values until edited. Displacement assigns the
same Cartesian vector, rotated for symmetry targets; inconsistent overlapping
orbits reject the entire edit. **Restore original** restores each target's own
host occupation. A pending displacement is committed to its existing selection
before selection changes.

**Undo / Redo** in the footer keeps up to 100 cluster-edit steps, including
occupations, displacements, inclusion/exclusion, expansions and centre changes.
Repeated edits of the same field during one focus visit form a single step,
even across preview updates. Enter, leaving the field, or changing the selected
sites or symmetry starts a new group. A multi-site or symmetry edit is undone
as a whole, including normalization of other occupation components. Standard
Undo/Redo keyboard shortcuts also work inside the editing fields. Undo includes
pending displacement values and cancels unfinished occupation input; a cancelled
buffer alone does not undo an earlier unrelated command. History stores only
editable cluster values, keeping the host and original radial data shared.
Changing the view or previewing an expansion does not add history steps.

When building an embedded cluster from a plain ASE structure, the GUI creates
a START host Potential before opening the editor. An existing host Potential
is reused with its radial data; every newly built cluster references its native
host before calculation setup. Cancelling the editor leaves the original
workspace unchanged. **Save Structure** exports the native CLUPOT and its host
POTFIL together. Complete radial data are retained where supported;
partially available radial data cause a validation error rather than a lossy export. Generic ASE exports are disabled for embedded clusters
because they would lose their host-site mapping. The native **Load from File** action recognizes CLUPOT and reopens it with
an existing host Potential or asks for the host POTFIL if none is active.
An embedded cluster with an actual SPR-KKR host Potential can be run
through the ordinary execution/profile workflow. The backend selects the native
cluster executables (such as `embscf` or `embgen`) using
`CONTROL.CLUTYPE=embedded`, and the GUI loads the resulting CLUPOT with the
original host reference. The Guided workflow exposes only the cluster tasks
supported by the backend; a geometry-only host is not enough to launch a run.

The host POTFIL is part of the physical input. When reopening a CLUPOT against
another host, the GUI checks native geometry consistency and asks for explicit
approval if a mismatch is detected. A versioned CLUPOT in calculation history
can be restored using the host reference recorded in its lightweight snapshot;
the full radial payload is read from the versioned CLUPOT file, not duplicated
in the snapshot.
