from PySide6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QMessageBox, QTreeView, QFileSystemModel, QMenu, QGroupBox, QLineEdit, QGridLayout, QSizePolicy
from PySide6.QtCore import QDir, Qt, QTimer, QThread, Signal, QRegularExpression
from PySide6.QtGui import QAction, QRegularExpressionValidator
import os
import shutil
import platform
from pathlib import Path
import yaml
from choose_documents_and_vector_model import select_embedding_model_directory, choose_documents_directory
import database_interactions
from utilities import check_preconditions_for_db_creation, open_file, delete_file, backup_database
import pickle

class CreateDatabaseThread(QThread):
    creationComplete = Signal()
    
    def __init__(self, database_name, parent=None):
        super().__init__(parent)
        self.database_name = database_name

    def run(self):
        create_vector_db = database_interactions.CreateVectorDB(database_name=self.database_name)
        create_vector_db.run()
        self.save_database_symlinks()
        self.update_config_with_database_name()
        backup_database()
        
        self.creationComplete.emit()

    def save_database_symlinks(self):
        source_folder = Path(__file__).resolve().parent / "Docs_for_DB"
        target_folder = source_folder / self.database_name
        target_folder.mkdir(parents=True, exist_ok=True)

        for item in source_folder.iterdir():
            if item.is_dir():
                continue
            target_item = target_folder / item.name
            if item.is_symlink():
                symlink_target = os.readlink(item)
                target_item.symlink_to(symlink_target)
            elif item.is_file():
                shutil.copy2(item, target_item)
            try:
                item.unlink()
            except PermissionError as e:
                print(f"PermissionError: Unable to delete {item}: {e}")

    def update_config_with_database_name(self):
        config_path = Path(__file__).resolve().parent / "config.yaml"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file) or {}

            model = config.get('EMBEDDING_MODEL_NAME', 'default_model')
            chunk_size = config.get('database', {}).get('chunk_size')
            chunk_overlap = config.get('database', {}).get('chunk_overlap')

            if 'created_databases' not in config or not isinstance(config['created_databases'], dict):
                config['created_databases'] = {}

            config['created_databases'][self.database_name] = {
                'model': model,
                'chunk_size': chunk_size,
                'chunk_overlap': chunk_overlap
            }

            with open(config_path, 'w', encoding='utf-8') as file:
                yaml.safe_dump(config, file, allow_unicode=True)

class CustomFileSystemModel(QFileSystemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilter(QDir.Files)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.column() == 0:
            file_path = super().filePath(index)
            if file_path.endswith('.pkl'):
                try:
                    with open(file_path, 'rb') as file:
                        document = pickle.load(file)
                    return document.metadata.get('file_name', 'Unknown')
                except Exception as e:
                    print(f"Error unpickling file {file_path}: {e}")
                    return "Error"
        return super().data(index, role)

class DatabasesTab(QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QVBoxLayout(self)
        self.documents_group_box = self.create_group_box("Files To Add to Database", "Docs_for_DB")
        self.groups = {self.documents_group_box: 1}

        grid_layout_top_buttons = QGridLayout()

        self.choose_docs_button = QPushButton("Choose Files")
        self.choose_docs_button.clicked.connect(choose_documents_directory)

        self.choose_model_dir_button = QPushButton("Choose Model")
        self.choose_model_dir_button.clicked.connect(select_embedding_model_directory)

        self.create_db_button = QPushButton("Create Vector Database")
        self.create_db_button.clicked.connect(self.on_create_db_clicked)
        self.create_db_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        grid_layout_top_buttons.addWidget(self.choose_docs_button, 0, 0)
        grid_layout_top_buttons.addWidget(self.choose_model_dir_button, 0, 1)
        grid_layout_top_buttons.addWidget(self.create_db_button, 0, 2)

        number_of_columns = 3
        for column_index in range(number_of_columns):
            grid_layout_top_buttons.setColumnStretch(column_index, 1)

        hbox2 = QHBoxLayout()
        self.database_name_input = QLineEdit()
        self.database_name_input.setPlaceholderText("Enter database name")
        self.database_name_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        regex = QRegularExpression("^[a-z0-9_-]*$")
        validator = QRegularExpressionValidator(regex, self.database_name_input)
        self.database_name_input.setValidator(validator)
        hbox2.addWidget(self.database_name_input)

        self.layout.addLayout(grid_layout_top_buttons)
        self.layout.addLayout(hbox2)

    def create_group_box(self, title, directory_name):
        group_box = QGroupBox(title)
        group_box.setCheckable(True)
        group_box.setChecked(True)
        layout = QVBoxLayout()
        tree_view = self.setup_directory_view(directory_name)
        layout.addWidget(tree_view)
        group_box.setLayout(layout)
        self.layout.addWidget(group_box)
        
        group_box.toggled.connect(lambda checked, gb=group_box: self.toggle_group_box(gb, checked))
        return group_box

    def setup_directory_view(self, directory_name):
        tree_view = QTreeView()
        model = CustomFileSystemModel()
        tree_view.setModel(model)
        tree_view.setSelectionMode(QTreeView.ExtendedSelection)

        script_dir = Path(__file__).resolve().parent
        directory_path = script_dir / directory_name
        model.setRootPath(str(directory_path))
        tree_view.setRootIndex(model.index(str(directory_path)))

        tree_view.hideColumn(1)
        tree_view.hideColumn(2)
        tree_view.hideColumn(3)

        tree_view.doubleClicked.connect(self.on_double_click)
        tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        tree_view.customContextMenuRequested.connect(self.on_context_menu)

        return tree_view

    def on_double_click(self, index):
        tree_view = self.sender()
        model = tree_view.model()
        file_path = model.filePath(index)
        
        if file_path.endswith('.pkl'):
            try:
                with open(file_path, 'rb') as file:
                    document = pickle.load(file)
                internal_file_path = document.metadata.get('file_path')
                if internal_file_path and Path(internal_file_path).exists():
                    open_file(internal_file_path)
                else:
                    QMessageBox.warning(self, "File Not Found", f"The file {internal_file_path} does not exist.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not open the pickle file: {e}")
        else:
            open_file(file_path)

    def on_context_menu(self, point):
        tree_view = self.sender()
        context_menu = QMenu(self)
        delete_action = QAction("Delete File", self)
        context_menu.addAction(delete_action)

        delete_action.triggered.connect(lambda: self.on_delete_file(tree_view))
        context_menu.exec_(tree_view.viewport().mapToGlobal(point))

    def on_delete_file(self, tree_view):
        selected_indexes = tree_view.selectedIndexes()
        model = tree_view.model()
        for index in selected_indexes:
            if index.column() == 0:
                file_path = model.filePath(index)
                delete_file(file_path)

    def on_create_db_clicked(self):
        # disable widgets
        self.create_db_button.setDisabled(True)
        self.choose_docs_button.setDisabled(True)
        self.choose_model_dir_button.setDisabled(True)
        self.database_name_input.setDisabled(True)
        
        database_name = self.database_name_input.text().strip()
        script_dir = Path(__file__).resolve().parent
        
        # check conditions
        checks_passed, message = check_preconditions_for_db_creation(script_dir, database_name)
        
        # re-enable widgets if any condition fails
        if not checks_passed:
            self.create_db_button.setDisabled(False)
            self.choose_docs_button.setDisabled(False)
            self.choose_model_dir_button.setDisabled(False)
            self.database_name_input.setDisabled(False)
            return

        print(f"Database will be named: '{database_name}'")
        
        # start create database thread
        self.create_database_thread = CreateDatabaseThread(database_name=database_name, parent=self)
        self.create_database_thread.creationComplete.connect(self.reenable_create_db_button)
        self.create_database_thread.start()

    def reenable_create_db_button(self):
        self.create_db_button.setDisabled(False)
        self.choose_docs_button.setDisabled(False)
        self.choose_model_dir_button.setDisabled(False)
        self.database_name_input.setDisabled(False)

    def toggle_group_box(self, group_box, checked):
        self.groups[group_box] = 1 if checked else 0
        self.adjust_stretch()

    def adjust_stretch(self):
        total_stretch = sum(stretch for group, stretch in self.groups.items() if group.isChecked())
        for group, stretch in self.groups.items():
            self.layout.setStretchFactor(group, stretch if group.isChecked() else 0)
