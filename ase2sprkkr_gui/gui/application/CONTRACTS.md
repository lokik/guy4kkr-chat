# Application-layer contracts

## Threading

`WorkspaceController` is confined to its `QObject` owning thread, normally the
GUI thread. Worker threads must return through queued Qt signals or equivalent
queued callbacks before reading or mutating workspace state.

`Generation` and `OptimisticLocked` provide optimistic stale-operation checks.
They are not thread-synchronization primitives and do not make the workspace
controller thread-safe.

## Structure editing

`WorkspaceController.apply_structure_edit()` owns the workspace transaction and
stale-state checks, not the physical interpretation of the edited structure.
The structure returned by the editor is authoritative, including its attached
SPR-KKR potential (or the absence of one). The controller must not copy, move,
rebind, create, or remove an attached potential in an attempt to repair the
editor result.

The controller may still update workspace provenance that necessarily changes
when a new structure is accepted, such as structure/state lineage,
`potential_path`, and restart intent.

Mutating editors receive a shallow editing copy: geometry and site/type
containers are independent, while radial arrays and attached-potential option
values are shared. Such editors may replace values, but must use an independent
copy before writing into shared arrays. Read-only dialogs use
`copy_source=False`, retain the original structure for display, and return an
independent result only when changed. Returning the source leaves the workspace
unchanged.


## Calculation input ownership

Guided task editors produce a one-off `CalculationRequest`: their input
parameters belong to the run and its result history, not to the editable
workspace input document. Recomputing a Guided historical result follows the
same rule. Expert input editing and explicit input-file loading continue to
operate on the workspace document.

For a normal Expert run, the exact workspace input generation captured when
the request is constructed becomes saved only after the execution backend
successfully returns from `submit()`, at which point the input files have
been written. The acknowledgement crosses to the GUI thread through a Qt
signal. It does not wait for SCF convergence, DOS completion, or result
parsing. A rejected submission never saves the draft; a later workspace edit
must remain unsaved. Preparation-only runs mark input saved after successful
file writing. Explicit one-off requests do not change the workspace's
input-document saved state.
