# GUI organization

This document describes the **canonical GUI architecture**. It is an
architectural contract for new code and refactors. Internal migration shims are
not part of that contract and should be removed rather than preserved as
alternate APIs.

## Packages

- `dialogs`: finished application windows and modal workflows, including
  `MainWindow`, `WorkflowWindow`, and structure-specific dialogs under
  `dialogs.structures`.
- `widgets`: reusable Qt controls. `widgets.input_parameters` contains the
  concrete value editors shared by guided and expert parameter editing;
  structure-specific controls live in `widgets.structures`.
- `controllers`: application-owned Qt workflow coordinators for reusable views.
  They may bridge GUI intents to application services and own GUI-wide window
  identity/lifecycle, but they do not become a second source of domain state.
- `input_parameters`: parameter-editing state and Qt-independent model helpers.
  It contains the editing session, field bindings, task semantics, validation,
  DATASET naming, tooltips, and declarative task specifications. It does not own
  finished application windows.
- `input_parameters.tasks`: Ase2sprkkr's closed mapping from opaque task keys
  accepted by the current ASE2SPRKKR input-parameter API to Guided editor/layout
  and workflow presentation metadata. It controls Guided UX only; it is not a
  backend task identity registry and is not a whitelist of tasks that Expert mode
  may execute. Backend task existence and execution/result semantics remain owned
  by ASE2SPRKKR. Ase2sprkkr must not anticipate the representation of a future
  backend task-definition API.
- `input_parameters.specs`: declarative guided-layout definitions. `schema`
  defines fields/groups/pages and individual task modules build their layouts.
  Specs describe layout and presentation only; selection of a layout for a
  backend task belongs to `input_parameters.tasks` as Ase2sprkkr presentation
  policy, keyed by the opaque backend lookup value accepted today.
- `workflow`: Qt-independent Guided workflow planning. It consumes application
  read contracts and Guided task metadata and produces an ordered typed
  presentation plan. Commands carry opaque backend task lookup keys rather than
  owning Ase2sprkkr task-definition objects or asserting backend identity semantics.
  The workflow layer owns Guided recommendation/grouping policy but no Qt
  rendering or execution permission. Backend-specific SCF status strings are
  translated at the workflow boundary before the planner consumes them.
- `presentation.py`: the small Qt-independent action-presentation vocabulary
  shared by planners and renderers, such as action categories and labels for
  semantic workspace actions.
- `recent_presentation.py`: Qt-independent presentation policy for recent files.
  It consumes immutable read snapshots and owns recent-launch selection, menu
  grouping, display labels, and empty-state copy; it never reads mutable
  application state directly.
- `workspace_semantics.py`: a Qt-free leaf module for immutable semantic value
  types shared across otherwise independent GUI layers. It owns no state,
  workflow policy, or user-facing presentation copy and imports no other
  `ase2sprkkr_gui.gui` module.
- `application`: application/document state, calculation execution, and
  provenance. `WorkspaceState` represents the mutable draft prepared for the
  next calculation; `ResultStore` owns calculation history independently of
  that draft; `WorkspaceController` is the mutation/signalling boundary between
  them and the GUI. `SprkkrExecution` owns the non-Qt execution contract for one
  immutable calculation request. Persistent application state such as recent
  files and settings also lives here.
- `flows`: stateless shared Qt workflows composed from application state and
  leaf dialogs. They may show modal UI and call public controller transitions,
  but they do not own application state or top-level windows.
- `plots`: GUI plotting/rendering. Pure physical/lattice queries and
  transformations belong in `ase2sprkkr_gui.physics`, not in the GUI layer.
- `misc`: small, specifically named Qt/layout/resource helpers. It must not
  become a home for application state or task-specific rules.
- `style`: the small palette-aware visual vocabulary shared by dialogs and
  renderers. Semantic state and task-specific presentation stay with the
  component that owns their meaning.

`ase2sprkkr_gui.main.GuiApplication` is the composition root. It owns one
`WorkspaceController`, one `PersistentJobSource`, one shared
`PersistentJobsController`, one `RecentFiles`, and one `ApplicationSettings`,
and injects the same shared objects into the relevant top-level windows. The
windows do not construct another application state or another top-level window.
Result selection is presentation state; the composition root wires explicit
result-selection intent separately from result history updates.

`PersistentJobSource` is authoritative for persistent run metadata, backend
operations, and persisted-run recovery. `PersistentJobsController` subscribes
to that source once and coordinates any number of `PersistentJobsWidget` views.
It also owns GUI-wide monitor-window identity and lifetime. A launch flow creates
`SprkkrRunWindow` without starting its worker, transfers it to
`PersistentJobsController.track_launch_window()`, and only then shows and starts
it. The controller therefore holds a strong pending reference before execution
can publish a persistent id. Because a runner is registered before persistent
submission, a browser request can match a newly visible persistent record to the
pending launch by `runner.id` even if the queued lifecycle signal has not yet
arrived. The pending launch is then promoted into the single
`job_id -> monitor_window` registry instead of creating a second attached
monitor. Any two distinct monitor windows claiming the same persistent id are a
programming/invariant error, not a recoverable UI policy.

Later launch lifecycle notifications refresh authoritative metadata. A launch is
announced to the composition root after a successful authoritative reload, so a
transient store error can be recovered by a later lifecycle notification without
losing project assignment. History views create an attached monitor only when no
active or matching pending launch monitor exists. Attached monitors are likewise
registered before their worker starts. Persistent job views never own backend
recovery or monitor-window lifecycle.

Calculation execution is deliberately not owned by a GUI run registry. A
`CalculationRequest` captures exact launch provenance, `SprkkrExecution` owns
runner creation/submission/cancellation/result loading, and `RunMonitorWindow`
is only the generic Qt monitor. `PersistentJobsController` owns GUI window
lifetime and identity, including pending launch windows, but not runner execution
or persistent state. Persistent execution identity and collision policy remain
in ASE2SPRKKR's runner/persistence layer.

Package `__init__.py` files should stay lightweight and should not become
alternate import APIs for dialog/widget internals. Canonical imports use the
concrete modules documented by the current package layout. Internal
compatibility wrappers are not architectural extension points and should not be
added to accommodate tests or obsolete call shapes.

## Workspace, results, and provenance

`WorkspaceState` is the draft for the **next** calculation. Results deliberately
do not live in it. Its `structure_id` identifies the user-visible structure and
`state_id` identifies the exact calculation state from which the next task will
start.

`WorkspaceState.atoms` is the sole physical authority for the active structure,
including an attached SPR-KKR potential when one exists. `potential_path` is
artifact/provenance metadata only; calculation launch must not silently use it
as a second physical source of truth.

`ResultStore` owns result history and calculation-state provenance independently
of the mutable workspace. A result may refer to an input state and, when the
backend result declares that it produces a new potential, to an output state.
Historical states retain enough provenance to reconstruct a reusable calculation
input from the recorded POTFIL version or a structure snapshot when necessary.
Activating historical state is always an explicit transition.

Potential production is a result capability defined by ASE2SPRKKR result types,
not inferred in Ase2sprkkr from a task-name string or from the input-parameter
definition. GUI-internal operation results implement the same small capability
contract explicitly. `ResultStore` derives potential provenance from the result
it records rather than accepting duplicate caller-supplied policy booleans.

Windows and flows mutate the draft through named `WorkspaceController`
operations rather than assigning workspace facets independently. The important
result-adoption semantics are:

- `adopt_external_result()` **records** an output imported by the user or another
  external source. It does not implicitly replace the current workspace draft.
  The imported result's atoms, potential, and input parameters belong to that
  result's provenance, not to the active draft. `select_result=True` expresses
  only explicit presentation intent to select that result in the UI.
- `adopt_calculation_result()` records a result produced from its mandatory
  captured `CalculationRequest`. It never reconstructs launch provenance from
  whatever happens to be active when the result finishes. Only a
  potential-producing result finishing from the exact currently active input
  state may fast-forward the workspace to its produced state. A result from an
  older branch is recorded in that branch and cannot silently overwrite a newer
  user choice.
- `use_result_state()` is the explicit operation for activating a reusable
  historical state (or an explicitly approved current version of its POTFIL).
- `use_for_new_calculation()` creates a new calculation branch from the active
  state instead of rewriting historical provenance.

The distinction between **recording a result**, **selecting a result for
presentation**, and **activating a result state for a future calculation** is
intentional. Do not collapse these operations into one implicit transition.
Presentation code reads history through `result_store`; controllers do not
expose duplicate compatibility views of the same history.

## Parameter editing

`input_parameters.session.InputParametersSession` owns an isolated working copy
of `InputParameters`, Undo/Redo history, and non-serialized editing state.
Edits go through session transactions; callers may inspect
`working_parameters` but must not mutate it directly. `result()` returns an
independently mutable copy. Transaction plugins may adjust a candidate and its
dormant state atomically before one history command is installed.

`input_parameters.bindings.InputParameterPath` is a tuple such as
`("ENERGY", "EMIN")`; it is an option address, not a filesystem path. Shared
option resolution/value comparison also lives in `input_parameters.bindings`.

Guided fields are connected to the session by
`input_parameters.field_binding`:

- `SessionFieldBinding` binds an ordinary option to its authoritative session
  value.
- `ProjectedFieldBinding` exposes a composable view into part of a structured
  parent value while reconstruction still happens through the parent binding.
- specialized draft/index helpers are presentation adapters; they must not
  become a second parameter model.

`widgets.input_parameters.parameter.ParameterEditor` is the presentation shell
for one declarative field. It owns tooltip/validation presentation and delegates
value editing to a registered `ParameterValueEditor` control. It does not
implement type-specific editing semantics itself.

All guided value editors implement the explicit
`widgets.input_parameters.value_editor.ParameterValueEditor` lifecycle:
`refresh()`, `commit()`, and `focus_for_history()`. Optional capabilities such as
`dependencies`, `full_width`, `help_text`, and tooltip application have formal
defaults; surrounding code must not discover editor contracts by probing
arbitrary attributes with `getattr`.

`widgets.input_parameters.registry.EDITORS` is the single name-to-editor
registry. `create_editor()` is the construction path. A field declaration
normally chooses its editor explicitly; `editor="auto"` alone invokes the
registered grammar-type MRO fallback in `editor_for_type()`.

Task-specific parameter semantics belong outside generic widgets. For example,
atomic BSF mode/path changes live in `input_parameters.bsf`, and the
single-site-contour transaction behavior lives in its dedicated plugin.
Generic renderers and scalar controls must not duplicate those rules.

### Guided specifications and presentation rules

Guided layouts are declarative. A `FieldPlacement` identifies the parameter
path, editor, related paths, and presentation metadata. Conditional behavior is
expressed by named rules in the task specification and receives a
Qt-independent presentation context. Rules may inspect parameter state but must
not mutate `InputParameters` or invoke Qt actions.

Fields may define dynamic visibility/enabling/labels/help and required state;
groups may define dynamic visibility, titles, notes, and layout. Programmatic
identity uses stable IDs, never translated/user-visible titles.

The renderer reapplies presentation rules after session changes, including
Undo/Redo and parameter replacement. Unrelated edits preserve a control's local
draft; replacement/history restoration or changes to that control's own
parameter/dependencies refresh it from the model.

### Expert editing

`dialogs.expert_input.InputParametersDialog` edits an isolated
`InputParametersSession` fork. Cancel therefore cannot mutate the caller's
session. The accepted result is returned as the fork/current parameter copy.

`widgets.input_parameters.expert_tree.ExpertInputTreeEditor` owns expert-tree
presentation and pending editor commits, while the dialog owns modal workflow,
validation, loading/editing input files, and acceptance. The expert tree and
guided form share the same session model; neither owns a second authoritative
parameter object. Tests and neighboring components use its narrow query API
such as `option_item(path)` rather than depending on internal row registries or
Qt role aliases.

Implicit backend defaults are presentation placeholders, not GUI-created
presets. Focusing or refreshing a control must not turn an implicit default into
an explicit stored value.

## Dependency rules

- `ase2sprkkr_gui.main.GuiApplication` is the composition root for shared application
  state and top-level windows.
- `application` does not import dialogs, widgets, controllers, flows, `workflow`,
  `presentation.py`, or `recent_presentation.py`; application state must not
  depend on Guided or recent-file presentation policy.
- `workspace_semantics.py` is a leaf: it imports no other `ase2sprkkr_gui.gui` module
  and contains no state ownership, workflow policy, or presentation text.
- `presentation.py` and `recent_presentation.py` are Qt-independent and may
  depend on leaf semantic values, but not on application state, input-parameter
  implementation, workflow, dialogs, widgets, controllers, or flows.
- `workflow` is Qt-independent and may consume application read contracts,
  `input_parameters.tasks`, pure presentation values, and physics helpers, but
  does not import dialogs, widgets, controllers, or flows. Its command model is
  independent of `input_parameters.tasks`; task commands carry only an opaque
  backend lookup key accepted by the current backend API. Planner code may
  consult Guided task metadata to construct the presentation plan.
- `controllers` coordinate reusable Qt workflows and may depend on application
  services, reusable widgets, and leaf dialogs, but reusable widgets do not
  depend back on controllers.
- Windows render controller state and invoke flows/controller transitions; they
  do not assign workspace fields directly.
- `flows` may compose application state and leaf dialogs, but must not import
  `MainWindow` or `WorkflowWindow`.
- Widgets may use parameter services and small helpers, but must not import
  concrete application dialogs. Use signals/callbacks for actions owned by a
  higher layer.
- `input_parameters` must not depend on concrete dialogs or widgets.
- `input_parameters.tasks` may depend on declarative specs but not on concrete
  dialogs/widgets; workflow metadata here is presentation policy, not backend
  task identity or execution permission.
- `input_parameters.specs` must remain independent of Qt session/widget
  implementations and of workflow/task identity policy.
- `misc` and `plots` must not become dependencies on top-level dialogs or
  parameter editors.
- Domain logic that can be expressed without Qt belongs outside the GUI package
  where practical.

The checks in `tests/test_gui_architecture.py` protect the broad layer
directions, acyclic GUI imports, lightweight import boundaries, and the leaf
contracts above. Tests should protect invariants and public contracts, not freeze
incidental implementation layout. Backend execution behavior is tested through
`SprkkrExecution`; only Qt signal/thread adaptation belongs in worker-level
tests.

## Common canonical imports

```python
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.application.result_store import ResultStore
from ase2sprkkr_gui.gui.application.sprkkr_execution import SprkkrExecution
from ase2sprkkr_gui.gui.controllers.persistent_jobs import PersistentJobsController
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath
from ase2sprkkr_gui.gui.input_parameters.dataset import filename_component
from ase2sprkkr_gui.gui.input_parameters.field_binding import SessionFieldBinding
from ase2sprkkr_gui.gui.input_parameters.tasks import guided_task_definition
from ase2sprkkr_gui.gui.presentation import ActionCategory
from ase2sprkkr_gui.gui.recent_presentation import RecentLaunch
from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner
from ase2sprkkr_gui.gui.workspace_semantics import EmptySpheresAction
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import ParameterValueEditor
```