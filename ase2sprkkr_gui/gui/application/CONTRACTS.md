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
