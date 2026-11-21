# Changelog

## Unreleased

- The execution profile editor now selects `backend: kkrunner` for supervised
  execution; the `process` backend name is no longer supported.
- Renamed the supervision control to **KKRunner supervisor**, separating
  backend reattachment capabilities from saving persistent project records.
- Requires ASE2SPRKKR 4.0.0 beta7 and KKRunner 0.2.0 beta5.
- Custom input files can be calculated without loading their structure into the
  workspace. The initial host/cluster potentials are parsed once and their
  content identities are verified against the staged files before launch.
- Embedded calculation history retains both host and cluster input versions.

### Features

- Added a dedicated Ase2sprkkr configuration tab in GUI settings, clearly
  distinguishing library-wide settings from GUI preferences. It edits
  empty-sphere defaults, output filtering, and NOMAD authentication. The
  output editor offers independent checkboxes for printing all output,
  printing summary information and printing lines matching a regex. The
  regex input stays visible, but is enabled only when regex filtering is
  selected. The all-output option supersedes the other two. Stored
  ``"info"`` and legacy stringified info values select the summary checkbox,
  never the regex field. Multiple regex filters use the shared
  ``"ERROR"|"WARNING"`` format provided by ase2sprkkr. Unmodified output
  filters are preserved when saving other settings. The default-profile selection lives in the execution-profile
  editor, with a highlighted default and Make default / Use automatic
  actions. Changes use ase2sprkkr's shared configuration API.


### Fixes

- Fixed application shutdown after exit confirmation: the workflow window now
  closes correctly, while cancelling exit keeps the workflow and project
  browser open.
- Fixed package-discovery and CI regressions following the GUI package rename.
- Updated regression tests for the project browser, persistent results,
  SSH file availability and visualization fallbacks.
- Avoided duplicate result parsing during project-history refreshes.

## 0.2.0b1 — 14 November 2026

This is the first beta release of **ASE2SPRKKR GUI**, a PyQt6 desktop
application for preparing atomic structures, configuring and running
SPR-KKR calculations, and exploring their results. It builds on
ASE2SPRKKR 4.0 and the standalone KKRunner execution framework.

### Application and interface

- Renamed the application to **Ase2sprkkr**, distributed as
  `ase2sprkkr-gui` with the Python package `ase2sprkkr_gui`.
- Added a vector application icon and action icons.
- Provided guided workflow and expert interfaces that share the same
  structure, calculation settings and results.
- Improved workflow navigation, expert-window layout and organization
  of application settings.
- Added an interactive ASE Python console and structure visualization.

### Structure preparation

- Added graphical tools for creating and editing bulk crystals,
  surfaces, interfaces and other atomic structures.
- Integrated structure visualization, editing and calculation preparation
  using ASE-compatible atomic models.

### Calculation setup and execution

- Added graphical editors for SPR-KKR task input parameters and
  calculation setup.
- Integrated local and SSH execution, optional scheduler support
  (including Slurm through PSI/J), and execution monitoring through
  ASE2SPRKKR and KKRunner.
- Added saved execution profiles and project-specific working directories.
- Added persistent run history, reconnection to supported running jobs,
  cancellation and result restoration.
- Improved handling of calculation conflicts, unsaved work and failed runs.

### Projects and results

- Added a project browser for organizing calculation records and
  inspecting previously computed results.
- Added project creation, editing, directory management and active-project
  selection, along with reassignment of existing results.
- Added import of existing SPR-KKR output files into projects without
  inventing execution records.
- Added access to result-file actions and ASE2SPRKKR plotting
  functionality, including supported scientific output formats.
- Added optional deletion of files referenced by historical records, with
  file-selection controls, modification dates and shared-file information.
- Added guarded cleanup of local and remote execution files and directories.
- Improved handling of missing historical files and unavailable remote results.

### Performance and reliability

- Added asynchronous project browser initialization with a loading
  placeholder and caching of historical results.
- Improved isolation of calculation execution and structure visualization.
- Expanded tests for application workflows, project persistence and
  integration with ASE2SPRKKR and KKRunner.

### Installation

Install the package from PyPI:

```console
pip install ase2sprkkr-gui
```

For explicit installation of beta/pre-release dependencies, use:

```console
pip install --pre ase2sprkkr-gui
```

Alternatively, install the latest development version:

```console
git clone git@github.com:ase2sprkkr/ase2sprkkr-gui.git
cd ase2sprkkr-gui
pip install --editable .
```

Run the application with:

```console
ase2sprkkr-gui
```

### Compatibility

- Requires Python 3.9 or newer.
- Requires ASE2SPRKKR 4.0.0 beta3 or newer within major version 4,
  and KKRunner 0.2.0 beta2 or newer within the 0.2 series.
- Running actual SPR-KKR calculations also requires an external
  SPR-KKR installation.
- The previous GUI package namespace is not retained as a compatibility
  alias.

This is a beta release; feedback and bug reports are welcome.
