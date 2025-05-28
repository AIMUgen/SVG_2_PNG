import sys
import os
import json
from io import BytesIO 
import traceback 
import time 
import shutil
import subprocess
from pathlib import Path 

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QComboBox, QFileDialog,
    QGraphicsView, QGraphicsScene, QSpinBox, QButtonGroup,
    QColorDialog, QSizePolicy, QFrame, QSplitter, QListWidget, QListWidgetItem,
    QMessageBox, QProgressDialog, QGridLayout, QCheckBox, QRadioButton
)
from PyQt6.QtSvgWidgets import QGraphicsSvgItem
from PyQt6.QtCore import Qt, QByteArray, QSize, QBuffer, QIODevice, QRectF, QStandardPaths
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QIcon, QAction
from PyQt6.QtSvg import QSvgRenderer


# Project Modules
from config_manager import ConfigManager
from llm_services import LLMService
from svg_utils import SvgUtils
# image_utils and image_generation_services will be imported dynamically where needed

# Try to set a more modern style if available
try:
    from PyQt6.QtWidgets import QStyleFactory
    QApplication.setStyle(QStyleFactory.create('Fusion'))
except ImportError:
    pass 

# Application specific path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROVIDERS_FILE = os.path.join(APP_DIR, "providers.json") 
USER_API_KEYS_FILE = os.path.join(APP_DIR, "user_api_keys.json")
APP_SETTINGS_FILE = os.path.join(APP_DIR, "app_settings.json") 


DUMMY_API_KEYS_DATA_TEMPLATE = {
    "OPENAI_API_KEY": "YOUR_OPENAI_API_KEY_HERE (e.g., sk-xxxxxxxx)",
    "ANTHROPIC_API_KEY": "YOUR_ANTHROPIC_API_KEY_HERE (e.g., sk-ant-xxxxxxxx)",
    "GOOGLE_API_KEY": "YOUR_GEMINI_API_KEY_HERE (e.g., AIzaSyxxxxxxxx)",
    "GOOGLE_CLOUD_PROJECT_ID": "your-gcp-project-id-here <--- REQUIRED for Vertex AI Imagen",
    "MISTRAL_API_KEY": "YOUR_MISTRAL_API_KEY_HERE (e.g., xxxxxxxx)",
    "DEEPSEEK_API_KEY": "YOUR_DEEPSEEK_API_KEY_HERE (e.g., sk-xxxxxxxx)",
    "OPENROUTER_API_KEY": "YOUR_OPENROUTER_API_KEY_HERE (e.g., sk-or-xxxxxxxx)",
    "DEEPAI_API_KEY": "YOUR_DEEPAI_API_KEY_HERE" 
}

if not os.path.exists(USER_API_KEYS_FILE):
    print(f"'{os.path.basename(USER_API_KEYS_FILE)}' not found. "
          f"Creating a template at '{USER_API_KEYS_FILE}'. "
          "Please edit it with your actual API keys for the relevant providers.")
    try:
        with open(USER_API_KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(DUMMY_API_KEYS_DATA_TEMPLATE, f, indent=2)
    except Exception as e:
        print(f"Could not create template '{os.path.basename(USER_API_KEYS_FILE)}': {e}")

class SvgIconGeneratorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LLM SVG & Image Assistant") 
        self.setGeometry(100, 100, 1250, 850) 

        self.config_manager = ConfigManager(APP_DIR) 
        self.llm_service = LLMService(self.config_manager)
        
        self.current_svg_content = None 
        self.current_svg_filepath = None
        self.current_raster_image_qpixmap = None 
        self.current_raster_image_bytes = None  
        self.current_raster_image_format = None 
        self.current_raster_filepath = None 
        self.current_generated_image_temp_path = None 

        self.current_source_is_svg = True 
        self.current_svg_graphics_item = None 
        
        # Last selected settings
        self.last_selected_provider_id = None
        self.last_selected_model_id = None
        self.last_selected_generation_type = "svg" 
        self.last_selected_image_model_id = None
        self.last_selected_aspect_ratio = "1:1"
        
        # Paths for settings
        self.temp_image_folder = "" 
        self.last_svg_open_dir = ""
        self.last_image_open_dir = ""
        self.last_svg_save_dir = ""
        self.last_raster_save_dir = "" # For "Save Generated Image As"
        self.last_conversion_save_dir = "" # For PNG/ICO conversion outputs

        self._load_app_settings() # Loads all the above paths and selections

        self.image_generation_models = {
            "DeepAI Text-to-Image": {"id": "deepai_text2img", "provider": "deepai"},
            "Google Imagen 3 (Quality via Vertex AI)": {"id": "imagen-3.0-generate-002", "provider": "google_vertex_ai_imagen"}, 
            "Google Imagen 3 (Fast via Vertex AI)": {"id": "imagen-3.0-fast-generate-001", "provider": "google_vertex_ai_imagen"},
            "Google Imagen 3 (Preview via Vertex AI)": {"id": "imagen-3.0-generate-preview-0601", "provider": "google_vertex_ai_imagen"}
        }
        self.generated_image_is_dirty = False 
        self.session_autosaved_files = [] 

        self.init_ui() # Initializes UI, including menu
        self.populate_providers() # Populates SVG provider/model combos based on loaded settings
        
        # Final UI state update after everything is loaded and UI created
        if self.gen_type_svg_radio.isChecked() and self.provider_combo.count() == 0:
            QMessageBox.critical(self, "Configuration Error",
                                f"No LLM providers for SVG generation were loaded. Please ensure '{os.path.basename(PROVIDERS_FILE)}' "
                                "is correctly formatted. SVG generation will be unavailable.")
            self.statusBar.showMessage(f"CRITICAL: Could not load SVG providers from '{os.path.basename(PROVIDERS_FILE)}'.")

        if not self.temp_image_folder: 
            self.set_default_temp_folder() # Sets and creates if not existing
        self.temp_folder_label.setText(f"Temp Folder: {self.temp_image_folder}")

    def _load_app_settings(self):
        if os.path.exists(APP_SETTINGS_FILE):
            try:
                with open(APP_SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    self.last_selected_provider_id = settings.get("last_provider_id")
                    self.last_selected_model_id = settings.get("last_model_id")
                    self.last_selected_generation_type = settings.get("last_generation_type", "svg") 
                    self.last_selected_image_model_id = settings.get("last_image_model_id")
                    self.last_selected_aspect_ratio = settings.get("last_aspect_ratio", "1:1")
                    self.temp_image_folder = settings.get("temp_image_folder", "") 
                    
                    # Load last used directories
                    self.last_svg_open_dir = settings.get("last_svg_open_dir", "")
                    self.last_image_open_dir = settings.get("last_image_open_dir", "")
                    self.last_svg_save_dir = settings.get("last_svg_save_dir", "")
                    self.last_raster_save_dir = settings.get("last_raster_save_dir", "")
                    self.last_conversion_save_dir = settings.get("last_conversion_save_dir", "")

                    print(f"Loaded settings: GenType '{self.last_selected_generation_type}', "
                          f"SVGProv '{self.last_selected_provider_id}', SVGModel '{self.last_selected_model_id}', "
                          f"ImageModel '{self.last_selected_image_model_id}', AspectRatio '{self.last_selected_aspect_ratio}', "
                          f"TempFolder '{self.temp_image_folder}', LastRasterSaveDir '{self.last_raster_save_dir}'")
            except Exception as e:
                print(f"Error loading app settings from {APP_SETTINGS_FILE}: {e}")

    def _save_app_settings(self):
        svg_provider_id_to_save = self.provider_combo.currentData() if self.gen_type_svg_radio.isChecked() and self.provider_combo.count() > 0 else self.last_selected_provider_id
        svg_model_id_to_save = self.model_combo.currentData() if self.gen_type_svg_radio.isChecked() and self.model_combo.count() > 0 else self.last_selected_model_id
        generation_type_to_save = "image" if self.gen_type_image_radio.isChecked() else "svg"
        image_model_id_to_save = self.image_model_combo.currentData() if self.gen_type_image_radio.isChecked() and self.image_model_combo.count() > 0 else self.last_selected_image_model_id
        aspect_ratio_to_save = self.aspect_ratio_combo.currentText() if self.gen_type_image_radio.isChecked() and self.aspect_ratio_combo.isVisible() else self.last_selected_aspect_ratio

        settings = {
            "last_provider_id": svg_provider_id_to_save,
            "last_model_id": svg_model_id_to_save,
            "last_generation_type": generation_type_to_save,
            "last_image_model_id": image_model_id_to_save,
            "last_aspect_ratio": aspect_ratio_to_save,
            "temp_image_folder": self.temp_image_folder,
            # Save last used directories
            "last_svg_open_dir": self.last_svg_open_dir,
            "last_image_open_dir": self.last_image_open_dir,
            "last_svg_save_dir": self.last_svg_save_dir,
            "last_raster_save_dir": self.last_raster_save_dir,
            "last_conversion_save_dir": self.last_conversion_save_dir
        }
        try:
            with open(APP_SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=2)
            print(f"Saved settings: GenType '{settings['last_generation_type']}', "
                  f"SVGProv '{settings['last_provider_id']}', SVGModel '{settings['last_model_id']}', "
                  f"ImageModel '{settings['last_image_model_id']}', AspectRatio '{settings['last_aspect_ratio']}', "
                  f"TempFolder '{settings['temp_image_folder']}', LastRasterSaveDir '{settings['last_raster_save_dir']}'")
        except Exception as e:
            print(f"Error saving app settings to {APP_SETTINGS_FILE}: {e}")

    def set_default_temp_folder(self):
        pictures_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        if not pictures_path: 
            pictures_path = os.path.join(str(Path.home()), "Pictures") 
        self.temp_image_folder = os.path.join(pictures_path, "LLM_Image_Assistant_Temp")
        try:
            os.makedirs(self.temp_image_folder, exist_ok=True)
        except Exception as e:
            print(f"Could not create default temp folder at {self.temp_image_folder}: {e}")
            self.temp_image_folder = os.path.join(APP_DIR, "TempImages")
            try:
                os.makedirs(self.temp_image_folder, exist_ok=True)
            except Exception as e2:
                print(f"Could not create fallback temp folder in app dir: {e2}")
                self.temp_image_folder = APP_DIR 
        print(f"Default temp folder set to: {self.temp_image_folder}")

    def choose_temp_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Temporary Folder for Auto-Saved Images", self.temp_image_folder or str(Path.home()))
        if folder:
            self.temp_image_folder = folder
            self.temp_folder_label.setText(f"Temp Folder: {self.temp_image_folder}")
            self._save_app_settings() 
            QMessageBox.information(self, "Temporary Folder Set", f"Generated images will be auto-saved to:\n{self.temp_image_folder}")

    def init_ui(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('&File')
        exit_action = QAction(QIcon.fromTheme("application-exit"), '&Exit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.setStatusTip('Exit application')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        tools_menu = menubar.addMenu('&Tools')
        bulk_action = QAction('&Bulk Image Creation...', self)
        bulk_action.setStatusTip('Open dialog for bulk image generation')
        bulk_action.triggered.connect(self.launch_bulk_image_dialog)
        tools_menu.addAction(bulk_action)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        # The main_layout should be set on the main_widget, which is correct.
        main_layout = QHBoxLayout(main_widget) 

        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_pane_width = 350 
        # Making fixedWidth might be problematic for DPI scaling, consider setMaximumWidth or preferred size.
        # For now, let's keep it to address the primary error.
        left_pane.setFixedWidth(left_pane_width) 

        gen_type_group = QFrame()
        gen_type_group.setFrameShape(QFrame.Shape.StyledPanel)
        gen_type_layout = QVBoxLayout(gen_type_group)
        gen_type_layout.addWidget(QLabel("Generation Type:"))
        self.gen_type_button_group = QButtonGroup(self) 
        self.gen_type_svg_radio = QRadioButton("Generate SVG Icon")
        self.gen_type_image_radio = QRadioButton("Generate Image")
        self.gen_type_button_group.addButton(self.gen_type_svg_radio)
        self.gen_type_button_group.addButton(self.gen_type_image_radio)
        gen_type_radio_layout = QHBoxLayout()
        gen_type_radio_layout.addWidget(self.gen_type_svg_radio)
        gen_type_radio_layout.addWidget(self.gen_type_image_radio)
        gen_type_layout.addLayout(gen_type_radio_layout)
        self.gen_type_svg_radio.toggled.connect(self.on_generation_type_changed)
        left_layout.addWidget(gen_type_group)

        self.svg_provider_model_group = QFrame()
        self.svg_provider_model_group.setFrameShape(QFrame.Shape.StyledPanel)
        svg_provider_model_layout = QVBoxLayout(self.svg_provider_model_group)
        self.provider_combo = QComboBox() 
        self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)
        svg_provider_model_layout.addWidget(QLabel("Select SVG Provider:"))
        svg_provider_model_layout.addWidget(self.provider_combo)
        self.model_combo = QComboBox() 
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)
        svg_provider_model_layout.addWidget(QLabel("Select SVG Model:"))
        svg_provider_model_layout.addWidget(self.model_combo)
        left_layout.addWidget(self.svg_provider_model_group)

        self.image_model_selection_group = QFrame()
        self.image_model_selection_group.setFrameShape(QFrame.Shape.StyledPanel)
        image_model_selection_layout = QVBoxLayout(self.image_model_selection_group)
        self.image_model_combo = QComboBox()
        image_model_selection_layout.addWidget(QLabel("Select Image Model:"))
        for name, data in self.image_generation_models.items():
            self.image_model_combo.addItem(name, data["id"]) 
        self.image_model_combo.currentIndexChanged.connect(self.on_image_model_changed)
        image_model_selection_layout.addWidget(self.image_model_combo)
        self.aspect_ratio_label = QLabel("Aspect Ratio (for Imagen):")
        self.aspect_ratio_combo = QComboBox()
        self.aspect_ratio_combo.addItems(["1:1", "16:9", "9:16", "4:3", "3:4"])
        self.aspect_ratio_combo.currentIndexChanged.connect(self._save_app_settings) 
        image_model_selection_layout.addWidget(self.aspect_ratio_label)
        image_model_selection_layout.addWidget(self.aspect_ratio_combo)
        self.negative_prompt_label = QLabel("Negative Prompt (optional):")
        self.negative_prompt_input = QTextEdit()
        self.negative_prompt_input.setPlaceholderText("E.g., 'blurry, ugly, text, watermark'...")
        self.negative_prompt_input.setFixedHeight(60) 
        self.negative_prompt_input.setUndoRedoEnabled(True)
        image_model_selection_layout.addWidget(self.negative_prompt_label)
        image_model_selection_layout.addWidget(self.negative_prompt_input)
        left_layout.addWidget(self.image_model_selection_group)

        self.prompt_label = QLabel("Prompt:") 
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("Describe your desired output...")
        self.prompt_input.setFixedHeight(100)
        self.prompt_input.setUndoRedoEnabled(True)
        left_layout.addWidget(self.prompt_label)
        left_layout.addWidget(self.prompt_input)

        self.generate_button = QPushButton("Generate") 
        self.generate_button.clicked.connect(self.on_generate_button_clicked)
        left_layout.addWidget(self.generate_button)

        self.prompt_history_combo = QComboBox()
        self.prompt_history_combo.setEditable(False) 
        self.prompt_history_combo.addItem("Recent Prompts...")
        self.prompt_history_combo.activated.connect(self.load_prompt_from_history)
        left_layout.addWidget(QLabel("Prompt History:"))
        left_layout.addWidget(self.prompt_history_combo)

        gallery_group = QFrame()
        gallery_group.setFrameShape(QFrame.Shape.StyledPanel)
        gallery_layout = QVBoxLayout(gallery_group)
        gallery_layout.addWidget(QLabel("Session Gallery:")) 
        self.session_gallery_list = QListWidget()
        self.session_gallery_list.setIconSize(QSize(64, 64)) 
        self.session_gallery_list.setViewMode(QListWidget.ViewMode.IconMode) 
        self.session_gallery_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.session_gallery_list.itemDoubleClicked.connect(self.load_gallery_item_to_preview)
        gallery_layout.addWidget(self.session_gallery_list)
        clear_gallery_button = QPushButton("Clear Gallery")
        clear_gallery_button.clicked.connect(self.clear_session_gallery)
        gallery_layout.addWidget(clear_gallery_button)
        left_layout.addWidget(gallery_group, 1)

        temp_folder_layout = QHBoxLayout()
        self.temp_folder_label = QLabel(f"Temp Folder: {self.temp_image_folder or 'Not Set'}")
        self.temp_folder_label.setWordWrap(True)
        self.choose_temp_folder_button = QPushButton("Set Temp Folder...")
        self.choose_temp_folder_button.clicked.connect(self.choose_temp_folder)
        self.open_temp_folder_button = QPushButton("Open Temp Folder")
        self.open_temp_folder_button.clicked.connect(self.open_temp_folder_in_explorer)
        temp_folder_layout.addWidget(self.temp_folder_label, 1) 
        temp_folder_layout.addWidget(self.choose_temp_folder_button)
        temp_folder_layout.addWidget(self.open_temp_folder_button)
        left_layout.addLayout(temp_folder_layout)

        center_pane = QWidget()
        center_layout = QVBoxLayout(center_pane)
        self.preview_view = QGraphicsView() 
        self.preview_scene = QGraphicsScene(self) 
        self.preview_view.setScene(self.preview_scene)
        self.preview_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.preview_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_layout.addWidget(QLabel("Preview:")) 
        center_layout.addWidget(self.preview_view)

        preview_actions_layout = QHBoxLayout()
        self.open_svg_button = QPushButton("Open SVG File...")
        self.open_svg_button.clicked.connect(self.open_svg_file)
        self.open_image_button = QPushButton("Open Image File...") 
        self.open_image_button.clicked.connect(self.open_image_file)
        self.save_svg_button = QPushButton("Save Current SVG...")
        self.save_svg_button.clicked.connect(self.save_current_svg)
        self.save_svg_button.setEnabled(False) 
        self.save_generated_image_button = QPushButton("Save Generated Image As...")
        self.save_generated_image_button.clicked.connect(self.save_generated_image_as)
        self.save_generated_image_button.setEnabled(False)
        preview_actions_layout.addWidget(self.open_svg_button)
        preview_actions_layout.addWidget(self.open_image_button)
        preview_actions_layout.addWidget(self.save_svg_button)
        preview_actions_layout.addWidget(self.save_generated_image_button) 
        center_layout.addLayout(preview_actions_layout)

        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_pane_width = 300
        right_pane.setFixedWidth(right_pane_width) 

        convert_png_group = QFrame()
        convert_png_group.setFrameShape(QFrame.Shape.StyledPanel)
        convert_png_layout = QVBoxLayout(convert_png_group)
        convert_png_layout.addWidget(QLabel("Convert to PNG"))
        dim_layout_png = QHBoxLayout() 
        convert_png_layout.addWidget(QLabel("Dimensions (px):"))
        self.png_width_spin = QSpinBox()
        self.png_width_spin.setRange(16, 8192); self.png_width_spin.setValue(256)
        self.png_height_spin = QSpinBox()
        self.png_height_spin.setRange(16, 8192); self.png_height_spin.setValue(256)
        dim_layout_png.addWidget(QLabel("W:")); dim_layout_png.addWidget(self.png_width_spin)
        dim_layout_png.addWidget(QLabel("H:")); dim_layout_png.addWidget(self.png_height_spin)
        convert_png_layout.addLayout(dim_layout_png)
        convert_png_layout.addWidget(QLabel("Background Color (for PNG):"))
        self.png_bg_color_combo = QComboBox(); self.png_bg_color_combo.addItems(["Transparent", "White", "Black", "Custom..."])
        self.png_bg_color_combo.currentIndexChanged.connect(self.handle_png_bg_color_change)
        self.custom_png_bg_color = QColor(Qt.GlobalColor.transparent) 
        convert_png_layout.addWidget(self.png_bg_color_combo)
        self.convert_png_button = QPushButton("Convert & Save PNG..."); self.convert_png_button.clicked.connect(self.convert_and_save_png)
        self.convert_png_button.setEnabled(False) 
        convert_png_layout.addWidget(self.convert_png_button)
        right_layout.addWidget(convert_png_group) 

        convert_ico_group = QFrame()
        convert_ico_group.setFrameShape(QFrame.Shape.StyledPanel)
        convert_ico_layout = QVBoxLayout(convert_ico_group)
        convert_ico_layout.addWidget(QLabel("Convert to ICO"))
        source_label = QLabel("(Source: Current SVG or Loaded Image)"); source_label.setStyleSheet("font-style: italic; color: gray;")
        convert_ico_layout.addWidget(source_label)
        convert_ico_layout.addWidget(QLabel("ICO Sizes (select multiple):"))
        self.ico_sizes_checkboxes = {}; self.standard_ico_sizes = [16, 24, 32, 48, 64, 128, 256] 
        default_selected_ico_sizes = [16, 32, 48, 256]
        ico_sizes_grid_layout = QGridLayout(); checkboxes_per_row = 2; row, col = 0, 0
        for size_val in self.standard_ico_sizes: 
            size_str = f"{size_val}x{size_val}"; checkbox = QCheckBox(size_str)
            if size_val in default_selected_ico_sizes: checkbox.setChecked(True)
            self.ico_sizes_checkboxes[size_str] = checkbox
            ico_sizes_grid_layout.addWidget(checkbox, row, col); col += 1
            if col >= checkboxes_per_row: col = 0; row += 1
        convert_ico_layout.addLayout(ico_sizes_grid_layout)
        ico_select_buttons_layout = QHBoxLayout()
        select_all_ico_button = QPushButton("Select All Sizes"); select_all_ico_button.clicked.connect(self.select_all_ico_sizes)
        deselect_all_ico_button = QPushButton("Deselect All Sizes"); deselect_all_ico_button.clicked.connect(self.deselect_all_ico_sizes)
        ico_select_buttons_layout.addWidget(select_all_ico_button); ico_select_buttons_layout.addWidget(deselect_all_ico_button)
        convert_ico_layout.addLayout(ico_select_buttons_layout)
        convert_ico_layout.addWidget(QLabel("Background Color (for ICO layers):"))
        self.ico_bg_color_combo = QComboBox(); self.ico_bg_color_combo.addItems(["Transparent", "White", "Black", "Custom..."])
        self.ico_bg_color_combo.currentIndexChanged.connect(self.handle_ico_bg_color_change)
        self.custom_ico_bg_color = QColor(Qt.GlobalColor.transparent)
        convert_ico_layout.addWidget(self.ico_bg_color_combo)
        self.convert_ico_button = QPushButton("Convert & Save ICO..."); self.convert_ico_button.clicked.connect(self.convert_and_save_ico)
        self.convert_ico_button.setEnabled(False) 
        convert_ico_layout.addWidget(self.convert_ico_button)
        right_layout.addWidget(convert_ico_group) 
        right_layout.addStretch() 

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_pane); splitter.addWidget(center_pane); splitter.addWidget(right_pane)
        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1); splitter.setStretchFactor(2, 0) 
        initial_center_width = self.geometry().width() - left_pane_width - right_pane_width
        if initial_center_width < 200: initial_center_width = 200 
        splitter.setSizes([left_pane_width, initial_center_width, right_pane_width])
        main_layout.addWidget(splitter)

        self.statusBar = self.statusBar(); self.statusBar.showMessage("Ready.")
        if self.last_selected_generation_type == "image": self.gen_type_image_radio.setChecked(True)
        else: self.gen_type_svg_radio.setChecked(True)
        self.on_generation_type_changed() 
        if self.last_selected_image_model_id:
            index = self.image_model_combo.findData(self.last_selected_image_model_id)
            if index >= 0: self.image_model_combo.setCurrentIndex(index)
        if self.last_selected_aspect_ratio:
            index = self.aspect_ratio_combo.findText(self.last_selected_aspect_ratio)
            if index >=0: self.aspect_ratio_combo.setCurrentIndex(index)
        self.update_aspect_ratio_visibility()
        
    def on_generation_type_changed(self):
        is_svg_selected = self.gen_type_svg_radio.isChecked()
        is_image_selected = not is_svg_selected
        self.svg_provider_model_group.setVisible(is_svg_selected)
        self.image_model_selection_group.setVisible(is_image_selected)
        if hasattr(self, 'negative_prompt_label'): 
            self.negative_prompt_label.setVisible(is_image_selected)
            self.negative_prompt_input.setVisible(is_image_selected)
        if is_svg_selected:
            self.prompt_label.setText("Icon Prompt (SVG):"); self.generate_button.setText("Generate SVG Icon")
        else:
            self.prompt_label.setText("Image Prompt:"); self.generate_button.setText("Generate Image")
        self.update_aspect_ratio_visibility()

    def on_image_model_changed(self, index):
        self.update_aspect_ratio_visibility(); self._save_app_settings()

    def update_aspect_ratio_visibility(self):
        if hasattr(self, 'gen_type_image_radio') and self.gen_type_image_radio.isChecked(): 
            selected_image_model_data_id = self.image_model_combo.currentData()
            provider = None
            for _name, data_dict in self.image_generation_models.items():
                if data_dict["id"] == selected_image_model_data_id: provider = data_dict["provider"]; break
            is_vertex_ai_imagen = (provider == "google_vertex_ai_imagen")
            self.aspect_ratio_label.setVisible(is_vertex_ai_imagen)
            self.aspect_ratio_combo.setVisible(is_vertex_ai_imagen)
        elif hasattr(self, 'aspect_ratio_label'): 
            self.aspect_ratio_label.setVisible(False); self.aspect_ratio_combo.setVisible(False)

    def on_provider_changed(self, index):
        self.update_model_dropdown(); self._save_app_settings() 

    def on_model_changed(self, index):
        self._save_app_settings() 

    def populate_providers(self):
        self.provider_combo.blockSignals(True); self.model_combo.blockSignals(True)
        self.provider_combo.clear()
        providers = self.config_manager.get_providers()
        if not providers:
            self.statusBar.showMessage(f"Error: No providers for SVG generation in '{os.path.basename(PROVIDERS_FILE)}'.")
            self.provider_combo.blockSignals(False); self.model_combo.blockSignals(False); return
        provider_found = False
        for i, provider in enumerate(providers):
            self.provider_combo.addItem(provider.get("name", "Unknown Provider"), provider.get("id"))
            if self.last_selected_provider_id and provider.get("id") == self.last_selected_provider_id:
                self.provider_combo.setCurrentIndex(i); provider_found = True
        if not provider_found and self.provider_combo.count() > 0: self.provider_combo.setCurrentIndex(0) 
        self.provider_combo.blockSignals(False)
        if self.provider_combo.count() > 0: self.update_model_dropdown(restore_saved_model=True) 
        self.model_combo.blockSignals(False)

    def update_model_dropdown(self, restore_saved_model=False):
        self.model_combo.blockSignals(True); self.model_combo.clear()
        current_provider_id = self.provider_combo.currentData()
        if not current_provider_id:
            if self.provider_combo.count() > 0 : self.statusBar.showMessage("No SVG provider selected.")
            self.model_combo.blockSignals(False); return
        provider_details = self.config_manager.get_provider_details(current_provider_id)
        model_found_for_provider = False
        if provider_details and "models" in provider_details:
            for i, model in enumerate(provider_details["models"]):
                model_display_name = model.get("name", "Unknown Model")
                self.model_combo.addItem(model_display_name, model.get("id"))
                if restore_saved_model and self.last_selected_model_id and model.get("id") == self.last_selected_model_id:
                    self.model_combo.setCurrentIndex(i); model_found_for_provider = True
        if not model_found_for_provider and self.model_combo.count() > 0: self.model_combo.setCurrentIndex(0) 
        self.model_combo.blockSignals(False)
        if self.gen_type_svg_radio.isChecked(): 
            if self.model_combo.count() == 0 and provider_details: 
                self.statusBar.showMessage(f"No SVG models for provider: {provider_details.get('name', 'Unknown')}")
            elif self.model_combo.count() > 0:
                self.statusBar.showMessage(f"SVG Provider '{self.provider_combo.currentText()}' Model: '{self.model_combo.currentText()}'.")
        if restore_saved_model and self.last_selected_model_id and not model_found_for_provider: pass 

    def add_to_prompt_history(self, prompt_text):
        if not prompt_text: return
        items = [self.prompt_history_combo.itemText(i) for i in range(1, self.prompt_history_combo.count())] 
        if prompt_text in items: self.prompt_history_combo.removeItem(self.prompt_history_combo.findText(prompt_text))
        self.prompt_history_combo.insertItem(1, prompt_text) 
        if self.prompt_history_combo.count() > 11: self.prompt_history_combo.removeItem(11)
        self.prompt_history_combo.setCurrentIndex(0) 

    def load_prompt_from_history(self, index):
        if index > 0: 
            prompt_text = self.prompt_history_combo.itemText(index)
            self.prompt_input.setText(prompt_text); self.prompt_history_combo.setCurrentIndex(0)

    def on_generate_button_clicked(self):
        if self.generated_image_is_dirty: 
            if not self.confirm_discard_generated_image(): return
        if self.gen_type_svg_radio.isChecked(): self.generate_icon() 
        elif self.gen_type_image_radio.isChecked(): self.generate_image() 
            
    def confirm_discard_generated_image(self):
        if self.generated_image_is_dirty:
            reply = QMessageBox.question(self, "Unsaved Generated Image",
                                         "You have an unsaved generated image that was auto-saved. "
                                         "If you proceed, this preview will be cleared. Discard and proceed?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: return False 
        self.generated_image_is_dirty = False 
        self.current_generated_image_temp_path = None 
        return True 

    def generate_icon(self): 
        provider_id = self.provider_combo.currentData(); model_id = self.model_combo.currentData()
        prompt = self.prompt_input.toPlainText().strip()
        if not provider_id or not model_id: QMessageBox.warning(self, "Selection Missing", "Select SVG provider and model."); return
        if not prompt: QMessageBox.warning(self, "Input Missing", "Enter prompt for SVG icon."); return
        provider_details = self.config_manager.get_provider_details(provider_id)
        if provider_details:
            api_key_name = provider_details.get("api_key_env_var")
            if api_key_name and not self.config_manager.get_api_key(api_key_name):
                QMessageBox.critical(self, "API Key Missing", f"API Key '{api_key_name}' not in '{os.path.basename(USER_API_KEYS_FILE)}'."); return
        else: QMessageBox.critical(self, "Error", "Selected SVG provider details not found."); return
        self.statusBar.showMessage(f"Generating SVG: {model_id} via {provider_id}..."); self.generate_button.setEnabled(False)
        self.clear_all_previews_and_content_for_new_generation(); QApplication.processEvents() 
        progress = QProgressDialog("Generating SVG...", "Cancel", 0, 0, self) 
        progress.setWindowModality(Qt.WindowModality.WindowModal); progress.setMinimumDuration(0); progress.setValue(0); progress.show(); QApplication.processEvents()
        result = self.llm_service.generate_svg(provider_id, model_id, prompt)
        progress.close(); self.generate_button.setEnabled(True)
        if result.get("success"):
            svg_code = result.get("svg_code", "")
            if not svg_code or not svg_code.strip().lower().startswith("<svg"): 
                self.statusBar.showMessage("SVG Gen: Output not valid SVG."); 
                QMessageBox.warning(self, "SVG Gen Warning", f"LLM output not valid SVG.\nOutput:\n{svg_code[:500]}...") 
                self.display_svg_code_as_text(svg_code); return
            self.render_svg(svg_code.encode('utf-8')) 
            if self.current_svg_content: 
                self.statusBar.showMessage("SVG generated successfully."); self.add_to_prompt_history(prompt)
                gallery_item_name = prompt[:30].strip() + "..." if len(prompt) > 30 else prompt.strip() or "Generated SVG"
                self.add_to_session_gallery(gallery_item_name, "svg", self.current_svg_content) # Pass type
        else:
            error_msg = result.get("error", "Unknown SVG gen error.")
            self.statusBar.showMessage(f"Error: {error_msg}"); QMessageBox.critical(self, "SVG Gen Failed", f"SVG Error:\n{error_msg}")

    def generate_image(self): 
        image_model_id = self.image_model_combo.currentData(); prompt = self.prompt_input.toPlainText().strip()
        negative_prompt = self.negative_prompt_input.toPlainText().strip() 
        aspect_ratio = self.aspect_ratio_combo.currentText() if self.aspect_ratio_combo.isVisible() else "1:1"
        if not image_model_id: QMessageBox.warning(self, "Image Model Missing", "Select image model."); return
        if not prompt: QMessageBox.warning(self, "Input Missing", "Enter prompt for image."); return
        provider_type_from_ui = None 
        for _n, data_in_dict in self.image_generation_models.items(): 
            if data_in_dict["id"] == image_model_id: provider_type_from_ui = data_in_dict["provider"]; break
        print(f"DEBUG: generate_image(): ID: '{image_model_id}', Provider: '{provider_type_from_ui}', Negative: '{negative_prompt}'")
        if provider_type_from_ui is None: QMessageBox.critical(self, "Internal Error", f"No provider for model ID: '{image_model_id}'."); return
        if provider_type_from_ui == "deepai" and not self.config_manager.get_api_key("DEEPAI_API_KEY"):
            QMessageBox.critical(self, "API Key Missing", "DEEPAI_API_KEY missing."); return
        elif provider_type_from_ui == "google_vertex_ai_imagen" and not (os.getenv("GOOGLE_CLOUD_PROJECT") or self.config_manager.api_keys.get("GOOGLE_CLOUD_PROJECT_ID")):
            QMessageBox.critical(self, "GCP Project ID Missing", "GOOGLE_CLOUD_PROJECT_ID missing for Vertex AI."); return
        self.statusBar.showMessage(f"Generating image: {self.image_model_combo.currentText()}..."); self.generate_button.setEnabled(False)
        self.clear_all_previews_and_content_for_new_generation(); QApplication.processEvents()
        progress = QProgressDialog("Generating Image...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal); progress.setMinimumDuration(0); progress.setValue(0); progress.show(); QApplication.processEvents()
        image_result_data = None
        try:
            from image_generation_services import ImageGenerationService, VERTEX_AI_AVAILABLE
            img_gen_service = ImageGenerationService(self.config_manager)
            if provider_type_from_ui == "deepai":
                image_result_data = img_gen_service.generate_image_deepai(prompt)
            elif provider_type_from_ui == "google_vertex_ai_imagen":
                if not VERTEX_AI_AVAILABLE: image_result_data = {"success": False, "error": "Vertex AI SDK not installed."}
                elif not img_gen_service.vertex_ai_initialized: image_result_data = {"success": False, "error": "Vertex AI not initialized."}
                else:
                    image_result_data = img_gen_service.generate_image_google_imagen_vertexai(
                        model_id=image_model_id, prompt=prompt, 
                        negative_prompt=negative_prompt if negative_prompt else None, aspect_ratio=aspect_ratio
                    )
            else: image_result_data = {"success": False, "error": f"Unknown provider: '{provider_type_from_ui}'"}
        except ImportError: image_result_data = {"success": False, "error": "ImageGenerationService missing."}
        except Exception as e: image_result_data = {"success": False, "error": f"ImageGenService error: {e}"}
        progress.close(); self.generate_button.setEnabled(True)
        if image_result_data and image_result_data.get("success"):
            img_bytes = image_result_data.get("image_bytes"); img_format = image_result_data.get("format", "PNG").upper() 
            if img_bytes:
                self.generated_image_is_dirty = True 
                self.current_raster_image_bytes = img_bytes; self.current_raster_image_format = img_format # Store before display
                temp_path = self.auto_save_generated_image(img_bytes, img_format) 
                if temp_path: self.current_generated_image_temp_path = temp_path # Link current preview to its temp file
                self.display_raster_image(img_bytes, img_format) 
                self.statusBar.showMessage("Image generated and auto-saved."); self.add_to_prompt_history(prompt) 
                # Add to gallery
                gallery_item_name = prompt[:30].strip() + "..." if len(prompt) > 30 else prompt.strip() or f"Generated {img_format}"
                self.add_to_session_gallery(gallery_item_name, img_format.lower(), img_bytes)
            else: self.statusBar.showMessage("Image gen OK, but no image data."); QMessageBox.warning(self, "Image Gen", "API OK, no image data.")
        else:
            error_msg = image_result_data.get("error", "Unknown error.") if image_result_data else "Image gen failed."
            self.statusBar.showMessage(f"Image Gen Error: {error_msg}"); QMessageBox.critical(self, "Image Gen Failed", f"{error_msg}")
            self.save_generated_image_button.setEnabled(False); self.generated_image_is_dirty = False

    def open_svg_file(self):
        if not self.confirm_discard_generated_image(): return
        
        start_dir = self.last_svg_open_dir or self.current_svg_filepath or str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(self, "Open SVG File", start_dir, "SVG Files (*.svg);;All Files (*)")
        
        if file_path:
            self.last_svg_open_dir = os.path.dirname(file_path) # Remember this directory
            self._save_app_settings()
            try:
                with open(file_path, 'rb') as f: svg_data = f.read()
                self.clear_all_previews_and_content_for_new_generation() 
                self.current_svg_filepath = file_path
                self.current_raster_filepath = None 
                self.render_svg(svg_data) 
                if self.current_svg_content: 
                    self.statusBar.showMessage(f"Loaded SVG: {os.path.basename(file_path)}")
                    self.add_to_session_gallery(os.path.basename(file_path), "svg", svg_data) 
            except Exception as e: QMessageBox.critical(self, "Error Opening SVG", f"{e}"); self.statusBar.showMessage(f"Error loading SVG: {e}")

    def auto_save_generated_image(self, image_bytes, image_format_str):
        if not self.temp_image_folder or not os.path.isdir(self.temp_image_folder):
            self.statusBar.showMessage("Error: Temp folder not set/invalid."); print(f"Error: Temp folder '{self.temp_image_folder}' invalid.")
            self.set_default_temp_folder(); 
            if not os.path.isdir(self.temp_image_folder): QMessageBox.warning(self, "Auto-Save Fail", f"No temp folder: {self.temp_image_folder}"); return None
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S"); prompt_part_for_fn = "image"
            current_prompt = self.prompt_input.toPlainText().strip()
            if current_prompt: prompt_part_for_fn = "".join(c if c.isalnum() else "_" for c in current_prompt)[:20].strip("_") or "image"
            filename = f"autosave_{timestamp}_{prompt_part_for_fn}.{image_format_str.lower()}"
            filepath = os.path.join(self.temp_image_folder, filename)
            with open(filepath, "wb") as f: f.write(image_bytes)
            if filepath not in self.session_autosaved_files: self.session_autosaved_files.append(filepath) 
            print(f"Image auto-saved: {filepath}"); return filepath
        except Exception as e: self.statusBar.showMessage(f"Auto-save error: {e}"); print(f"Auto-save error: {e}"); QMessageBox.warning(self, "Auto-Save Fail", f"{e}"); return None

    def save_generated_image_as(self):
        if not self.generated_image_is_dirty or not self.current_raster_image_bytes or not self.current_raster_image_format:
            QMessageBox.warning(self, "No Image", "No unsaved generated image to save."); return
        
        default_filename_base = "generated_image"; 
        prompt_text = self.prompt_input.toPlainText().strip()
        if self.gen_type_image_radio.isChecked() and prompt_text: 
            prompt_part = "".join(c if c.isalnum() or c in " _-" else "" for c in prompt_text)[:30].strip()
            if prompt_part: default_filename_base = prompt_part
        
        save_filters = "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg)"
        default_save_format = self.current_raster_image_format if self.current_raster_image_format in ["PNG", "JPEG", "JPG"] else "PNG"
        default_filename = f"{default_filename_base}.{default_save_format.lower()}"
        
        initial_dir = self.last_raster_save_dir or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation) or str(Path.home())

        file_path, selected_filter = QFileDialog.getSaveFileName(self, "Save Generated Image As", 
                                                               os.path.join(initial_dir, default_filename), 
                                                               save_filters)
        if file_path:
            self.last_raster_save_dir = os.path.dirname(file_path) 
            self._save_app_settings() 

            save_format = "PNG"; 
            if "JPEG" in selected_filter.upper() or file_path.lower().endswith((".jpg", ".jpeg")): save_format = "JPEG"
            
            try:
                from PIL import Image 
                pil_image_to_save = Image.open(BytesIO(self.current_raster_image_bytes))
                if save_format == "JPEG" and pil_image_to_save.mode in ['RGBA', 'LA', 'P']: 
                    if pil_image_to_save.mode != 'RGBA': pil_image_to_save = pil_image_to_save.convert('RGBA')
                    background = Image.new("RGB", pil_image_to_save.size, (255, 255, 255)); background.paste(pil_image_to_save, mask=pil_image_to_save.split()[3]); pil_image_to_save = background
                elif save_format == "JPEG" and pil_image_to_save.mode != 'RGB':
                     pil_image_to_save = pil_image_to_save.convert("RGB")
                if save_format == "JPEG":
                    pil_image_to_save.save(file_path, format="JPEG", quality=90, optimize=True) 
                else: 
                    pil_image_to_save.save(file_path, format="PNG", optimize=True)
                self.statusBar.showMessage(f"Generated image saved: {file_path}")
                if self.current_generated_image_temp_path and self.current_generated_image_temp_path in self.session_autosaved_files:
                    try:
                        os.remove(self.current_generated_image_temp_path); print(f"Removed temp: {self.current_generated_image_temp_path}")
                        self.session_autosaved_files.remove(self.current_generated_image_temp_path)
                    except Exception as e_del: print(f"Error deleting temp {self.current_generated_image_temp_path}: {e_del}")
                self.generated_image_is_dirty = False; self.current_generated_image_temp_path = None 
                self.current_raster_filepath = file_path; self.save_generated_image_button.setEnabled(False) 
            except ImportError: QMessageBox.critical(self, "Pillow Missing", "Pillow library required to save images.")
            except Exception as e: QMessageBox.critical(self, "Error Saving Image", f"{e}"); traceback.print_exc()

    def clear_all_previews_and_content_for_new_generation(self):
        self.preview_scene.clear()
        self.current_svg_graphics_item = None; self.current_svg_content = None; self.current_svg_filepath = None
        self.current_raster_image_qpixmap = None; self.current_raster_image_bytes = None
        self.current_raster_image_format = None; self.current_raster_filepath = None
        self.current_generated_image_temp_path = None; self.generated_image_is_dirty = False 
        self.save_svg_button.setEnabled(False); self.save_generated_image_button.setEnabled(False)
        self.convert_png_button.setEnabled(False); self.convert_ico_button.setEnabled(False)
        self.statusBar.showMessage("Ready for new generation...")

    def clear_all_previews_and_content(self): 
        if self.generated_image_is_dirty: 
            if not self.confirm_discard_generated_image(): return False 
        self.clear_all_previews_and_content_for_new_generation() 
        return True 

    def render_svg(self, svg_bytes_content):
        self.current_source_is_svg = True
        if not svg_bytes_content:
            self.statusBar.showMessage("No SVG content."); self.save_svg_button.setEnabled(False)
            self.convert_png_button.setEnabled(False); self.convert_ico_button.setEnabled(False)
            self.save_generated_image_button.setEnabled(False); return
        q_byte_array = QByteArray(svg_bytes_content)
        new_svg_item = QGraphicsSvgItem(); new_svg_item.renderer().load(q_byte_array)
        if not new_svg_item.renderer().isValid():
            self.statusBar.showMessage("Invalid SVG. Displaying as text.")
            self.display_svg_code_as_text(svg_bytes_content.decode('utf-8', errors='replace')); return
        if self.current_svg_graphics_item and self.current_svg_graphics_item.scene() == self.preview_scene:
            self.preview_scene.removeItem(self.current_svg_graphics_item)
        elif self.preview_scene.items(): self.preview_scene.clear()
        self.preview_scene.addItem(new_svg_item); self.current_svg_graphics_item = new_svg_item 
        self.preview_view.setSceneRect(QRectF(self.current_svg_graphics_item.boundingRect())) 
        QApplication.processEvents(); self.preview_view.fitInView(self.current_svg_graphics_item, Qt.AspectRatioMode.KeepAspectRatio)
        self.current_svg_content = svg_bytes_content; self.current_raster_image_bytes = None 
        self.current_raster_image_format = None; self.current_raster_filepath = None
        self.current_generated_image_temp_path = None
        self.save_svg_button.setEnabled(True); self.convert_png_button.setEnabled(True) 
        self.convert_ico_button.setEnabled(True); self.save_generated_image_button.setEnabled(False) 
        self.generated_image_is_dirty = False; self.statusBar.showMessage("SVG rendered.")

    def display_raster_image(self, image_bytes, image_format_str):
        self.current_source_is_svg = False
        pixmap = QPixmap(); format_upper = image_format_str.upper() if image_format_str else None
        loaded = pixmap.loadFromData(image_bytes, format_upper) if format_upper else pixmap.loadFromData(image_bytes)
        if not loaded or pixmap.isNull():
            QMessageBox.critical(self, "Image Load Error", f"Could not load image data (format: {format_upper}).")
            self.statusBar.showMessage(f"Error loading {format_upper or 'image'}.")
            self.save_svg_button.setEnabled(False); self.convert_png_button.setEnabled(False)
            self.convert_ico_button.setEnabled(False); self.save_generated_image_button.setEnabled(False); return
        if self.current_svg_graphics_item and self.current_svg_graphics_item.scene() == self.preview_scene:
            self.preview_scene.removeItem(self.current_svg_graphics_item)
        elif self.preview_scene.items(): self.preview_scene.clear()
        self.current_svg_graphics_item = None
        self.preview_scene.addPixmap(pixmap)
        self.current_raster_image_qpixmap = pixmap
        # self.current_raster_image_bytes and self.current_raster_image_format are already set by caller
        self.current_svg_content = None; self.current_svg_filepath = None
        self.preview_view.setSceneRect(QRectF(pixmap.rect())) 
        QApplication.processEvents(); self.preview_view.fitInView(QRectF(pixmap.rect()), Qt.AspectRatioMode.KeepAspectRatio)
        self.save_svg_button.setEnabled(False); self.convert_png_button.setEnabled(True) 
        self.convert_ico_button.setEnabled(True); 
        self.save_generated_image_button.setEnabled(self.generated_image_is_dirty) 
        self.statusBar.showMessage(f"{self.current_raster_image_format or 'Image'} displayed.")

    def display_svg_code_as_text(self, text_content):
        self.current_source_is_svg = False 
        text_item = self.preview_scene.addText(text_content if text_content else "No content or invalid SVG.")
        self.preview_view.setSceneRect(QRectF(text_item.boundingRect()))
        self.preview_view.fitInView(text_item, Qt.AspectRatioMode.KeepAspectRatio)

    def open_image_file(self):
        if not self.confirm_discard_generated_image(): return

        start_dir = self.last_image_open_dir or self.current_raster_filepath or str(Path.home())
        supported_formats = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Image File", start_dir, supported_formats)
        
        if file_path:
            self.last_image_open_dir = os.path.dirname(file_path) # Remember this directory
            self._save_app_settings()
            try:
                file_ext = os.path.splitext(file_path)[1].lower(); image_format_hint = None
                if file_ext == ".png": image_format_hint = "PNG"
                elif file_ext in [".jpg", ".jpeg"]: image_format_hint = "JPEG"
                elif file_ext == ".webp": image_format_hint = "WEBP"
                elif file_ext == ".bmp": image_format_hint = "BMP"
                elif file_ext == ".gif": image_format_hint = "GIF"
                with open(file_path, 'rb') as f: image_data = f.read()
                self.clear_all_previews_and_content_for_new_generation() 
                temp_pixmap = QPixmap(); loaded_by_qt = False; actual_format_detected = image_format_hint
                if image_format_hint: loaded_by_qt = temp_pixmap.loadFromData(image_data, image_format_hint)
                if not loaded_by_qt: loaded_by_qt = temp_pixmap.loadFromData(image_data)
                if not loaded_by_qt or temp_pixmap.isNull():
                    try:
                        from PIL import Image, UnidentifiedImageError
                        pil_img_temp = Image.open(BytesIO(image_data)); actual_format_detected = pil_img_temp.format; pil_img_temp.close() 
                        if actual_format_detected and not temp_pixmap.loadFromData(image_data, actual_format_detected.upper()): # Ensure format is upper for Qt
                            QMessageBox.critical(self, "Image Load Error", f"Pillow identified as {actual_format_detected}, but Qt could not load it."); return
                        elif not actual_format_detected: QMessageBox.critical(self, "Image Load Error", "Format unknown/unsupported by Pillow & Qt."); return
                    except ImportError: QMessageBox.critical(self, "Image Load Error", "Pillow library not found."); return
                    except UnidentifiedImageError: QMessageBox.critical(self, "Image Load Error", "Format unknown or unsupported by Pillow."); return
                    except Exception as e_pil: QMessageBox.critical(self, "Image Load Error", f"Pillow loading error: {e_pil}"); return
                
                self.current_raster_filepath = file_path; self.current_svg_filepath = None 
                self.current_raster_image_bytes = image_data 
                self.current_raster_image_format = actual_format_detected.upper() if actual_format_detected else "RASTER"
                self.display_raster_image(image_data, self.current_raster_image_format) 
                self.generated_image_is_dirty = False 
                self.add_to_session_gallery(os.path.basename(file_path), self.current_raster_image_format.lower(), image_data)
            except Exception as e: QMessageBox.critical(self, "Error Opening Image File", f"{e}\n{traceback.format_exc()}"); self.statusBar.showMessage(f"Error loading image: {e}")
    
    def open_image_file(self):
        if not self.confirm_discard_generated_image(): return
        supported_formats = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Image", self.current_raster_filepath or str(Path.home()), supported_formats)
        if file_path:
            try:
                file_ext = os.path.splitext(file_path)[1].lower(); image_format_hint = None
                if file_ext == ".png": image_format_hint = "PNG"
                elif file_ext in [".jpg", ".jpeg"]: image_format_hint = "JPEG"
                elif file_ext == ".webp": image_format_hint = "WEBP" # QPixmap might not support WEBP directly on all systems
                elif file_ext == ".bmp": image_format_hint = "BMP"
                elif file_ext == ".gif": image_format_hint = "GIF"
                with open(file_path, 'rb') as f: image_data = f.read()
                self.clear_all_previews_and_content_for_new_generation() 
                temp_pixmap = QPixmap(); loaded_by_qt = False; actual_format_detected = image_format_hint
                if image_format_hint: loaded_by_qt = temp_pixmap.loadFromData(image_data, image_format_hint)
                if not loaded_by_qt: loaded_by_qt = temp_pixmap.loadFromData(image_data)
                if not loaded_by_qt or temp_pixmap.isNull():
                    try: # Fallback to Pillow
                        from PIL import Image, UnidentifiedImageError
                        pil_img = Image.open(BytesIO(image_data)); actual_format_detected = pil_img.format; pil_img.close()
                        if actual_format_detected and temp_pixmap.loadFromData(image_data, actual_format_detected.upper()):
                            pass # Loaded successfully with Pillow's detected format
                        else: QMessageBox.critical(self, "Load Error", f"Format '{actual_format_detected or 'unknown'}' not loadable by Qt."); return
                    except Exception as e_pil: QMessageBox.critical(self, "Load Error", f"Pillow/Qt load failed: {e_pil}"); return
                self.current_raster_filepath = file_path; self.current_svg_filepath = None 
                self.current_raster_image_bytes = image_data # Store original bytes
                self.current_raster_image_format = actual_format_detected or "RASTER"
                self.display_raster_image(image_data, actual_format_detected or "RASTER") 
                self.generated_image_is_dirty = False 
                self.add_to_session_gallery(os.path.basename(file_path), self.current_raster_image_format.lower(), image_data)
            except Exception as e: QMessageBox.critical(self, "Error Opening Image", f"{e}\n{traceback.format_exc()}"); self.statusBar.showMessage(f"Error loading image: {e}")

    def save_current_svg(self):
        if not self.current_source_is_svg or not self.current_svg_content:
            QMessageBox.warning(self, "No SVG", "No valid SVG to save."); return
        
        default_filename = "icon.svg"
        initial_dir = self.last_svg_save_dir or \
                      (os.path.dirname(self.current_svg_filepath) if self.current_svg_filepath else str(Path.home()))

        if not self.current_svg_filepath and self.prompt_input.toPlainText() and self.gen_type_svg_radio.isChecked(): 
             prompt_part = "".join(c if c.isalnum() or c in " _-" else "" for c in self.prompt_input.toPlainText().strip())[:30].strip()
             if prompt_part: default_filename = f"{prompt_part}.svg"
        elif self.current_svg_filepath:
            default_filename = os.path.basename(self.current_svg_filepath)
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Save SVG File", os.path.join(initial_dir, default_filename), "SVG Files (*.svg)")
        if file_path:
            self.last_svg_save_dir = os.path.dirname(file_path) # Remember this directory
            self._save_app_settings()
            try:
                with open(file_path, 'wb') as f: f.write(self.current_svg_content)
                self.statusBar.showMessage(f"SVG saved: {file_path}"); self.current_svg_filepath = file_path 
            except Exception as e: QMessageBox.critical(self, "Save Error", f"{e}"); self.statusBar.showMessage(f"SVG save error: {e}")
    
    def handle_png_bg_color_change(self, index): # ... (same as before)
        selected_option = self.png_bg_color_combo.itemText(index)
        if selected_option == "Custom...":
            initial_color = self.custom_png_bg_color if self.custom_png_bg_color.isValid() and self.custom_png_bg_color.alpha() != 0 else Qt.GlobalColor.white
            color = QColorDialog.getColor(initial_color, self)
            if color.isValid(): self.custom_png_bg_color = color
            else: 
                if self.custom_png_bg_color.alpha() == 0: self.png_bg_color_combo.setCurrentText("Transparent")
                elif self.custom_png_bg_color == QColor("white"): self.png_bg_color_combo.setCurrentText("White")
                elif self.custom_png_bg_color == QColor("black"): self.png_bg_color_combo.setCurrentText("Black")
    def get_selected_png_background_color_str(self): # ... (same as before)
        bg_option = self.png_bg_color_combo.currentText()
        if bg_option == "Transparent": return "transparent"
        elif bg_option == "White": return "white"
        elif bg_option == "Black": return "black"
        elif bg_option == "Custom...":
            return self.custom_png_bg_color.name(QColor.NameFormat.HexArgb) if self.custom_png_bg_color.isValid() else "transparent"
        return "transparent"
    
    def convert_and_save_png(self): 
        width = self.png_width_spin.value(); height = self.png_height_spin.value()
        bg_color_str = self.get_selected_png_background_color_str()
        source_data = None; source_type_for_conversion = None 
        if self.current_source_is_svg and self.current_svg_content:
            source_data = self.current_svg_content; source_type_for_conversion = "svg"
        elif not self.current_source_is_svg and self.current_raster_image_bytes:
            source_data = self.current_raster_image_bytes
            source_type_for_conversion = self.current_raster_image_format.lower() if self.current_raster_image_format else "png"
        else: QMessageBox.warning(self, "No Source", "No content to convert to PNG."); return
        self.statusBar.showMessage(f"Converting {source_type_for_conversion.upper()} to PNG..."); QApplication.processEvents()
        png_bytes = None
        if source_type_for_conversion == "svg":
            png_bytes = SvgUtils.convert_svg_to_png_bytes(source_data, width, height, bg_color_str)
        elif source_type_for_conversion in ["png", "jpeg", "jpg", "webp", "bmp", "gif", "raster"]: 
            try:
                from image_utils import ImageConverter 
                png_bytes = ImageConverter.convert_raster_to_png_bytes(
                    source_data_bytes=source_data, source_format=source_type_for_conversion,
                    target_width=width, target_height=height, background_color_str=bg_color_str
                )
            except ImportError: QMessageBox.critical(self, "Missing Utility", "ImageConverter missing."); self.statusBar.showMessage("Error: ImageConverter missing."); return
            except Exception as e_conv: QMessageBox.critical(self, "Conversion Error", f"Error converting raster to PNG: {e_conv}"); self.statusBar.showMessage("Raster to PNG error."); traceback.print_exc(); return
        else: QMessageBox.warning(self, "Unsupported Source", f"Cannot convert '{source_type_for_conversion}' to PNG."); return
        if not png_bytes: QMessageBox.critical(self, "PNG Conversion Failed", "Could not convert to PNG."); self.statusBar.showMessage("PNG conversion failed."); return
        
        default_filename = "image.png"
        initial_dir = self.last_conversion_save_dir or \
                      (os.path.dirname(self.current_raster_filepath) if self.current_raster_filepath else \
                      (os.path.dirname(self.current_svg_filepath) if self.current_svg_filepath else str(Path.home())))

        if self.current_source_is_svg:
            if self.current_svg_filepath: base, _ = os.path.splitext(self.current_svg_filepath); default_filename = base + ".png"
            elif self.prompt_input.toPlainText() and self.gen_type_svg_radio.isChecked():
                 prompt_part = "".join(c if c.isalnum() or c in " _-" else "" for c in self.prompt_input.toPlainText().strip())[:30].strip()
                 if prompt_part: default_filename = f"{prompt_part}.png"
        elif self.current_raster_filepath: base, _ = os.path.splitext(self.current_raster_filepath); default_filename = base + "_converted.png"
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Save PNG File", os.path.join(initial_dir, default_filename), "PNG Files (*.png)")
        if file_path:
            self.last_conversion_save_dir = os.path.dirname(file_path) # Remember this directory
            self._save_app_settings()
            try:
                with open(file_path, 'wb') as f: f.write(png_bytes)
                self.statusBar.showMessage(f"PNG saved to: {file_path}")
            except Exception as e: QMessageBox.critical(self, "Error Saving PNG", f"Could not save PNG file: {e}"); self.statusBar.showMessage(f"Error saving PNG: {e}")
        else: self.statusBar.showMessage("PNG save cancelled.")

    def convert_and_save_ico(self): 
        selected_sizes = self.get_selected_ico_sizes()
        if not selected_sizes: QMessageBox.warning(self, "No Sizes Selected", "Select ICO sizes."); return
        source_data = None; source_type_for_conversion = None 
        if self.current_source_is_svg and self.current_svg_content:
            source_data = self.current_svg_content; source_type_for_conversion = "svg"
        elif not self.current_source_is_svg and self.current_raster_image_bytes:
            source_data = self.current_raster_image_bytes
            source_type_for_conversion = self.current_raster_image_format.lower() if self.current_raster_image_format else "png"
        else: QMessageBox.warning(self, "No Source Image", "No content to convert to ICO."); return
        bg_color_str_ico = self.get_selected_ico_background_color_str()
        self.statusBar.showMessage(f"Converting {source_type_for_conversion.upper()} to ICO..."); QApplication.processEvents()
        try:
            from image_utils import ImageConverter 
            ico_bytes = ImageConverter.convert_to_ico_bytes(
                source_data_bytes=source_data, source_type=source_type_for_conversion, 
                sizes=selected_sizes, background_color_str=bg_color_str_ico
            )
        except ImportError: QMessageBox.critical(self, "Missing Utility", "ImageConverter missing."); self.statusBar.showMessage("Error: ImageConverter missing."); return
        except Exception as e: QMessageBox.critical(self, "ICO Error", f"{e}"); self.statusBar.showMessage(f"ICO error: {e}"); traceback.print_exc(); return
        if not ico_bytes: QMessageBox.critical(self, "ICO Conversion Failed", "Could not convert to ICO."); self.statusBar.showMessage("ICO conversion failed."); return
        
        default_filename = "icon.ico"
        initial_dir = self.last_conversion_save_dir or \
                      (os.path.dirname(self.current_raster_filepath) if self.current_raster_filepath else \
                      (os.path.dirname(self.current_svg_filepath) if self.current_svg_filepath else str(Path.home())))

        if self.current_source_is_svg:
            if self.current_svg_filepath: base, _ = os.path.splitext(self.current_svg_filepath); default_filename = base + ".ico"
            elif self.prompt_input.toPlainText() and self.gen_type_svg_radio.isChecked():
                 prompt_part = "".join(c if c.isalnum() or c in " _-" else "" for c in self.prompt_input.toPlainText().strip())[:30].strip()
                 if prompt_part: default_filename = f"{prompt_part}.ico"
        elif self.current_raster_filepath: base, _ = os.path.splitext(self.current_raster_filepath); default_filename = base + ".ico"
        elif self.generated_image_is_dirty and self.gen_type_image_radio.isChecked() and self.prompt_input.toPlainText(): 
            prompt_part = "".join(c if c.isalnum() or c in " _-" else "" for c in self.prompt_input.toPlainText().strip())[:30].strip()
            if prompt_part: default_filename = f"{prompt_part}.ico"

        file_path, _ = QFileDialog.getSaveFileName(self, "Save ICO File", os.path.join(initial_dir, default_filename), "ICO Files (*.ico)")
        if file_path:
            self.last_conversion_save_dir = os.path.dirname(file_path) # Remember this directory
            self._save_app_settings()
            try:
                with open(file_path, 'wb') as f: f.write(ico_bytes)
                self.statusBar.showMessage(f"ICO saved to: {file_path}")
            except Exception as e: QMessageBox.critical(self, "Error Saving ICO", f"{e}"); self.statusBar.showMessage(f"Error saving ICO: {e}")
        else: self.statusBar.showMessage("ICO save cancelled.")

    def add_to_session_gallery(self, name: str, item_type: str, item_bytes: bytes):
        pixmap = QPixmap(QSize(64, 64))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        display_name = f"[{item_type.upper()}] {name}"

        try:
            if item_type.lower() == "svg":
                thumb_renderer = QSvgRenderer()
                thumb_renderer.load(QByteArray(item_bytes))
                if not thumb_renderer.isValid():
                    painter.fillRect(pixmap.rect(), Qt.GlobalColor.lightGray)
                    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Bad\nSVG")
                else:
                    svg_qsize = thumb_renderer.defaultSize()
                    if svg_qsize.isValid() and svg_qsize.width() > 0 and svg_qsize.height() > 0:
                        target_rect = pixmap.rect()
                        scaled_size = svg_qsize.scaled(target_rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
                        x = (target_rect.width() - scaled_size.width()) / 2.0
                        y = (target_rect.height() - scaled_size.height()) / 2.0
                        render_qrectf = QRectF(x, y, scaled_size.width(), scaled_size.height())
                        thumb_renderer.render(painter, render_qrectf)
                    else:
                        thumb_renderer.render(painter, QRectF(pixmap.rect()))
            elif item_type.lower() in ["png", "jpeg", "jpg", "webp", "bmp", "gif", "raster"]:
                raster_thumb = QPixmap()
                if raster_thumb.loadFromData(item_bytes, item_type.upper()):
                    scaled_raster_thumb = raster_thumb.scaled(QSize(64,64), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    # Center the scaled pixmap onto the painter's pixmap
                    x = (pixmap.width() - scaled_raster_thumb.width()) / 2.0
                    y = (pixmap.height() - scaled_raster_thumb.height()) / 2.0
                    painter.drawPixmap(int(x), int(y), scaled_raster_thumb)
                else:
                    painter.fillRect(pixmap.rect(), Qt.GlobalColor.darkGray)
                    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, f"Bad\n{item_type.upper()}")
            else:
                painter.fillRect(pixmap.rect(), Qt.GlobalColor.magenta) # Unknown type
                painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "???")
        except Exception as e_thumb:
            print(f"Error creating thumbnail for '{name}' (type {item_type}): {e_thumb}")
            painter.fillRect(pixmap.rect(), QColor("salmon"))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Thumb\nError")
        finally:
            painter.end()

        item_data_dict = {"type": item_type.lower(), "bytes": item_bytes, "name": name}
        list_item = QListWidgetItem(QIcon(pixmap), display_name)
        list_item.setData(Qt.ItemDataRole.UserRole, item_data_dict)
        self.session_gallery_list.addItem(list_item)


    def load_gallery_item_to_preview(self, item: QListWidgetItem):
        item_data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(item_data, dict): return # Should be a dict

        item_type = item_data.get("type")
        item_bytes = item_data.get("bytes")
        item_name = item_data.get("name", "Loaded from Gallery")

        if not item_bytes or not item_type: return
        if not self.confirm_discard_generated_image(): return
        self.clear_all_previews_and_content_for_new_generation() 

        # Update prompt with item name (useful for generated items)
        # For file-loaded items, item_name is the filename.
        # For generated, it's based on the prompt.
        # self.prompt_input.setText(item_name) # Or a portion of it.

        if item_type == "svg":
            self.current_svg_filepath = None # From gallery, not a specific file path unless we store it
            self.current_raster_filepath = None 
            self.render_svg(item_bytes) 
            if self.current_svg_content: self.statusBar.showMessage(f"Loaded SVG '{item_name}' from gallery.")
        elif item_type in ["png", "jpeg", "jpg", "webp", "bmp", "gif", "raster"]:
            self.current_raster_filepath = None
            self.current_svg_filepath = None
            self.current_raster_image_bytes = item_bytes # Store before display for consistency
            self.current_raster_image_format = item_type.upper()
            self.display_raster_image(item_bytes, item_type)
            self.generated_image_is_dirty = False # Item from gallery is not "newly generated dirty"
            if self.current_raster_image_qpixmap: self.statusBar.showMessage(f"Loaded {item_type.upper()} '{item_name}' from gallery.")
        else:
            QMessageBox.warning(self, "Unknown Type", f"Cannot load unknown item type '{item_type}' from gallery.")


    def clear_session_gallery(self):
        self.session_gallery_list.clear(); self.statusBar.showMessage("Session gallery cleared.")

    def closeEvent(self, event):
        unsaved_temp_files_to_process = [f for f in self.session_autosaved_files if os.path.exists(f)]
        current_preview_is_dirty_generated = self.generated_image_is_dirty and \
                                            self.current_generated_image_temp_path and \
                                            os.path.exists(self.current_generated_image_temp_path)
        if current_preview_is_dirty_generated and self.current_generated_image_temp_path not in unsaved_temp_files_to_process:
            unsaved_temp_files_to_process.append(self.current_generated_image_temp_path)
        if unsaved_temp_files_to_process:
            msg = f"You have {len(unsaved_temp_files_to_process)} auto-saved image(s) from this session that were not manually saved to a final location. "
            reply_save_manually = QMessageBox.question(self, "Unsaved Auto-Saved Images",
                                         msg + "Do you want to save them now?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply_save_manually == QMessageBox.StandardButton.Yes:
                temp_files_to_remove_after_save = []
                for temp_file_path in unsaved_temp_files_to_process: 
                    if not os.path.exists(temp_file_path): continue
                    try:
                        with open(temp_file_path, 'rb') as f_temp: img_bytes = f_temp.read()
                        from PIL import Image 
                        pil_img_for_format = Image.open(BytesIO(img_bytes))
                        img_format_for_save = pil_img_for_format.format or "PNG"; pil_img_for_format.close()
                        default_save_name = os.path.basename(temp_file_path).replace("autosave_", "")
                        initial_save_dir = self.last_raster_save_dir or os.path.dirname(temp_file_path) or str(Path.home())
                        save_path, _ = QFileDialog.getSaveFileName(self, f"Save '{default_save_name}' As...", 
                                                                   os.path.join(initial_save_dir, default_save_name), 
                                                                   f"{img_format_for_save.upper()} Files (*.{img_format_for_save.lower()});;All Files (*)")
                        if save_path:
                            self.last_raster_save_dir = os.path.dirname(save_path) 
                            shutil.copyfile(temp_file_path, save_path) 
                            temp_files_to_remove_after_save.append(temp_file_path)
                            print(f"Manually saved: {temp_file_path} to {save_path}")
                        else: print(f"User cancelled saving for: {temp_file_path}")
                    except Exception as e_save_exit: print(f"Error during exit-save for {temp_file_path}: {e_save_exit}")
                
                for temp_file_path in temp_files_to_remove_after_save:
                    try:
                        os.remove(temp_file_path)
                        if temp_file_path in self.session_autosaved_files: self.session_autosaved_files.remove(temp_file_path)
                        print(f"Removed temp file after manual save: {temp_file_path}")
                    except Exception as e_del: print(f"Error removing temp file {temp_file_path}: {e_del}")
                unsaved_temp_files_to_process = [f for f in self.session_autosaved_files if os.path.exists(f)] # Recheck remaining
            if unsaved_temp_files_to_process: 
                reply_delete_temps = QMessageBox.question(self, "Delete Temporary Files?",
                                             f"The remaining {len(unsaved_temp_files_to_process)} auto-saved image(s) are in:\n{self.temp_image_folder}\n\n"
                                             "Do you want to delete these temporary files from this session?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) 
                if reply_delete_temps == QMessageBox.StandardButton.Yes:
                    for temp_file_path in unsaved_temp_files_to_process:
                        try:
                            if os.path.exists(temp_file_path): os.remove(temp_file_path); print(f"Deleted temp file on exit: {temp_file_path}")
                        except Exception as e_del_exit: print(f"Error deleting temp file {temp_file_path} on exit: {e_del_exit}")
        self._save_app_settings() 
        print("Closing LLM SVG & Image Assistant...")
        event.accept()

    def select_all_ico_sizes(self):
        for checkbox in self.ico_sizes_checkboxes.values(): checkbox.setChecked(True)
    def deselect_all_ico_sizes(self):
        for checkbox in self.ico_sizes_checkboxes.values(): checkbox.setChecked(False)
    def get_selected_ico_sizes(self):
        selected_sizes = []; 
        for size_str, checkbox in self.ico_sizes_checkboxes.items():
            if checkbox.isChecked(): selected_sizes.append(int(size_str.split('x')[0]))
        return sorted(list(set(selected_sizes))) 
    def handle_ico_bg_color_change(self, index): # ... (same as before)
        selected_option = self.ico_bg_color_combo.itemText(index)
        if selected_option == "Custom...":
            initial_color = self.custom_ico_bg_color if self.custom_ico_bg_color.isValid() and self.custom_ico_bg_color.alpha() != 0 else Qt.GlobalColor.white
            color = QColorDialog.getColor(initial_color, self)
            if color.isValid(): self.custom_ico_bg_color = color
            else: 
                if self.custom_ico_bg_color.alpha() == 0: self.ico_bg_color_combo.setCurrentText("Transparent")
                elif self.custom_ico_bg_color == QColor("white"): self.ico_bg_color_combo.setCurrentText("White")
                elif self.custom_ico_bg_color == QColor("black"): self.ico_bg_color_combo.setCurrentText("Black")
    def get_selected_ico_background_color_str(self): # ... (same as before)
        bg_option = self.ico_bg_color_combo.currentText()
        if bg_option == "Transparent": return "transparent"
        elif bg_option == "White": return "white"
        elif bg_option == "Black": return "black"
        elif bg_option == "Custom...":
            return self.custom_ico_bg_color.name(QColor.NameFormat.HexArgb) if self.custom_ico_bg_color.isValid() else "transparent"
        return "transparent"
    
    def launch_bulk_image_dialog(self):
        # Check for unsaved generated image in the main window first
        if self.generated_image_is_dirty:
            if not self.confirm_discard_generated_image():
                return # User chose not to discard, so don't open bulk dialog

        # Dynamically import here to avoid circular dependencies if bulk_image_dialog
        # might ever need to import something from main (though unlikely for this structure)
        # and to keep initial startup faster if bulk mode is not used.
        try:
            from bulk_image_dialog import BulkImageDialog
            # Pass the config_manager to the dialog so it can create its own services
            # or access API keys/settings as needed.
            # Also pass the main window as parent for modality and proper dialog behavior.
            dialog = BulkImageDialog(self.config_manager, self) 
            dialog.exec() # Show as a modal dialog
        except ImportError:
            QMessageBox.critical(self, "Error", "Bulk Image Dialog module (bulk_image_dialog.py) not found.")
            traceback.print_exc()
        except Exception as e:
            QMessageBox.critical(self, "Error Launching Bulk Dialog", f"An unexpected error occurred: {e}")
            traceback.print_exc()
    
    def open_temp_folder_in_explorer(self):
        if not self.temp_image_folder or not os.path.isdir(self.temp_image_folder):
            QMessageBox.warning(self, "Temp Folder Not Set", 
                                "The temporary image folder is not set or does not exist. Please set it first.")
            # Optionally, try to set/create default if not set
            if not self.temp_image_folder:
                self.set_default_temp_folder()
                self.temp_folder_label.setText(f"Temp Folder: {self.temp_image_folder}")
                if not os.path.isdir(self.temp_image_folder): # Still not valid
                    return
            elif not os.path.isdir(self.temp_image_folder): # Set but not a dir
                 QMessageBox.warning(self, "Invalid Temp Folder", 
                                f"The configured temp folder path is invalid:\n{self.temp_image_folder}")
                 return

        try:
            if sys.platform == "win32":
                os.startfile(self.temp_image_folder)
            elif sys.platform == "darwin": # macOS
                subprocess.run(["open", self.temp_image_folder], check=True)
            else: # Linux and other UNIX-like
                subprocess.run(["xdg-open", self.temp_image_folder], check=True)
            self.statusBar.showMessage(f"Opened temp folder: {self.temp_image_folder}")
        except FileNotFoundError: # If xdg-open or open is not found
             QMessageBox.critical(self, "Error Opening Folder",
                                 f"Could not find a file explorer utility to open the folder.\n"
                                 f"Path: {self.temp_image_folder}")
        except Exception as e:
            QMessageBox.critical(self, "Error Opening Folder",
                                 f"Could not open the temporary folder: {e}\nPath: {self.temp_image_folder}")
            traceback.print_exc()

if __name__ == '__main__':
    # Enable High DPI Scaling - Alternative method
    try:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
    except AttributeError:
        print("Warning: Standard Qt.ApplicationAttribute for HighDPI not found, trying QCoreApplication.")
        try:
            from PyQt6.QtCore import QCoreApplication
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
        except Exception as e_dpi:
            print(f"Warning: Could not set HighDPI attributes: {e_dpi}")


    app = QApplication(sys.argv)
    app.setApplicationName("LLMSvgIconGenerator"); app.setOrganizationName("IconAppDev") 
    if not os.path.exists(PROVIDERS_FILE):
        QMessageBox.critical(None, "Missing Configuration File", f"CRITICAL ERROR: '{os.path.basename(PROVIDERS_FILE)}' not found in {APP_DIR}."); sys.exit(1) 
    else: 
        try:
            with open(PROVIDERS_FILE, 'r', encoding='utf-8') as f_check:
                json.load(f_check) # Just try to parse
        except Exception as e: QMessageBox.warning(None, "Configuration Warning", f"Could not parse '{os.path.basename(PROVIDERS_FILE)}': {e}.");
    main_win = SvgIconGeneratorApp(); main_win.show(); sys.exit(app.exec())