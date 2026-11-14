"""Guided chooser for obtaining a detached structure candidate."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.flows import structure_candidates
from ase2sprkkr_gui.gui.flows.structure_candidates import StructureCandidate
from ase2sprkkr_gui.gui.presentation import ActionCategory
from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.style import (
    SPACE_LG,
    SPACE_SM,
    SPACE_XL,
    SPACE_XXL,
    heading_font,
    secondary_text_stylesheet,
)
from ase2sprkkr_gui.gui.widgets.action_card import configure_action_card
from ase2sprkkr_gui.gui.widgets.recent_launcher import populate_recent_menu


class StructureSourceDialog(QDialog):
    """Offer the standard non-workspace ways to obtain an atomic structure."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        recent_files: RecentFiles,
        title: str = "Choose Structure",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(620)
        self._candidate: StructureCandidate | None = None
        self._recent_files = recent_files

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_XXL, SPACE_XL, SPACE_XXL, SPACE_XL)
        layout.setSpacing(SPACE_LG)

        heading = QLabel(title, self)
        heading.setFont(heading_font(heading.font(), "dialog"))
        layout.addWidget(heading)

        intro = QLabel(
            "Choose how to obtain the structure. The selected structure is kept "
            "detached until the enclosing workflow accepts it.",
            self,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(secondary_text_stylesheet(self.palette()))
        layout.addWidget(intro)

        create_layout = self._add_section(layout, "Create structure")
        self._add_action(
            create_layout,
            "Create a 3D Structure",
            "Build a periodic bulk crystal",
            self._create,
            category="structure",
            icon=QIcon(str(icon_path("bulk_crystal.png"))),
        )
        self._add_action(
            create_layout,
            "Create Structure from Prototype Database",
            "Start from a crystallographic structure prototype",
            self._create_from_database,
            category="structure",
            icon=QIcon(str(icon_path("database.svg"))),
        )

        self._add_action(
            create_layout,
            "Create by Python Shell",
            "Create an ASE Atoms structure using Python",
            self._create_from_shell,
            category="structure",
            icon=QStyle.StandardPixmap.SP_ComputerIcon,
        )

        load_layout = self._add_section(layout, "Load structure")
        self._add_action(
            load_layout,
            "Download Structure from Online Database",
            "Search an online crystallographic database",
            self._download,
            category="load",
            icon=QStyle.StandardPixmap.SP_ArrowDown,
        )
        self._add_action(
            load_layout,
            "Load a Structure",
            "Open a supported atomic structure file",
            self._load_file,
            category="load",
            icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        )
        self._add_recent_action(load_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_section(self, root: QVBoxLayout, title: str) -> QVBoxLayout:
        section = QWidget(self)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(SPACE_SM)
        label = QLabel(title, section)
        label.setFont(heading_font(label.font(), "section"))
        section_layout.addWidget(label)
        root.addWidget(section)
        return section_layout

    def _add_action(
        self,
        layout: QVBoxLayout,
        title: str,
        description: str,
        callback,
        *,
        category: ActionCategory,
        icon: QStyle.StandardPixmap | QIcon,
    ) -> None:
        button = QPushButton(self)
        configure_action_card(
            button,
            title,
            description,
            icon if isinstance(icon, QIcon) else self.style().standardIcon(icon),
            category=category,
        )
        button.clicked.connect(callback)
        layout.addWidget(button)

    def _add_recent_action(self, layout: QVBoxLayout) -> None:
        snapshot = self._recent_files.read_snapshot()
        recent = snapshot.paths("structure")
        if not recent:
            return

        default_path = recent[0]
        button = QToolButton(self)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setToolTip(default_path)
        configure_action_card(
            button,
            f"Recent: {Path(default_path).name}",
            "Reuse a recently loaded structure",
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward),
            category="load",
            icon_size=QSize(24, 24),
            minimum_height=56,
            menu_button=True,
        )
        button.clicked.connect(
            lambda _checked=False, path=default_path: self._load_recent_path(path)
        )

        menu = QMenu(button)
        populate_recent_menu(
            menu,
            snapshot,
            "structure",
            self._load_recent_path,
        )
        button.setMenu(menu)
        layout.addWidget(button)

    def _accept_candidate(self, candidate: StructureCandidate | None) -> None:
        if candidate is None:
            return
        self._candidate = candidate
        self.accept()

    def _create(self) -> None:
        self._accept_candidate(
            structure_candidates.create_structure_candidate(self)
        )

    def _create_from_shell(self) -> None:
        from ase2sprkkr_gui.gui.dialogs.structures.shell import select_shell_structure

        atoms = select_shell_structure(self)
        if atoms is not None:
            self._accept_candidate(StructureCandidate(atoms))

    def _create_from_database(self) -> None:
        self._accept_candidate(
            structure_candidates.create_structure_from_database_candidate(self)
        )

    def _download(self) -> None:
        self._accept_candidate(
            structure_candidates.download_structure_candidate(self)
        )

    def _load_file(self) -> None:
        candidate = structure_candidates.choose_structure_candidate(self)
        if candidate is not None and candidate.source_path is not None:
            self._recent_files.remember("structure", candidate.source_path)
        self._accept_candidate(candidate)

    def _load_recent_path(self, value: str | Path) -> None:
        path = Path(value)
        if not path.exists():
            QMessageBox.warning(
                self,
                "Missing File",
                f"File not found:\n{path}",
            )
            self._recent_files.forget("structure", path)
            return
        candidate = structure_candidates.load_structure_candidate(path, self)
        if candidate is None:
            return
        self._recent_files.remember("structure", path)
        self._accept_candidate(candidate)

    def candidate(self) -> StructureCandidate | None:
        return self._candidate


def select_structure_source(
    parent: QWidget | None = None,
    *,
    recent_files: RecentFiles,
    title: str = "Choose Structure",
) -> StructureCandidate | None:
    """Run the guided source chooser and return its detached candidate."""
    dialog = StructureSourceDialog(
        parent,
        recent_files=recent_files,
        title=title,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.candidate()
