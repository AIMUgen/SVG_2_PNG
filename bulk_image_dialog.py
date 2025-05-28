import sys
import os
import json
import time
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QPushButton, QLabel, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QProgressBar, QSpinBox, QComboBox, QRadioButton,
    QGroupBox, QCheckBox, QAbstractItemView, QDialogButtonBox, QWidget,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QColor

from main import APP_DIR


# Assuming image_generation_services.py is in the same directory or accessible path
# We'll import it dynamically or ensure it's available
# from image_generation_services import ImageGenerationService # Will be instantiated later

# Constants for settings keys
# Constants for settings keys
SETTINGS_COMBINATIONS_FILE = "source_combinations_file"
SETTINGS_SECTIONS = "sections_data"
SETTINGS_COMMONALITY_LAYERS = "commonality_layers_data"
SETTINGS_GLOBAL_PROMPT = "global_prompt"
SETTINGS_IMAGE_MODEL_ID = "image_model_id"
SETTINGS_ASPECT_RATIO = "aspect_ratio"
SETTINGS_ITERATIONS_PER_COMBO = "iterations_per_combo"
SETTINGS_API_IMAGES_PER_RUN = "api_images_per_run"
SETTINGS_GLOBAL_FILENAME_PREFIX = "global_filename_prefix"
SETTINGS_OUTPUT_FOLDER = "output_folder"
SETTINGS_SAVE_TO_SINGLE_FOLDER = "save_to_single_folder"
SETTINGS_SUBFOLDER_EXCLUSION = "subfolder_exclusion_keywords"
SETTINGS_GENERATION_PROGRESS = "generation_progress_state"
SETTINGS_PROMPT_COMPONENT_ORDER = "prompt_component_order" # New constant


class BulkGenerationSignals(QObject):
    progress_updated = pyqtSignal(int, str)  # overall_percentage, current_action_text
    image_saved = pyqtSignal(str, str, int, int)  # filepath, line_text, iteration_num, image_in_iteration_num
    error_occurred = pyqtSignal(str, int, int, str)  # line_text, iteration_num, attempt_num, error_msg
    paused_due_to_error = pyqtSignal(str, int, str) # line_text, iteration_num, error_msg
    bulk_process_finished = pyqtSignal(bool, str)  # completed_fully, summary_message
    request_resume = pyqtSignal() # To signal thread from dialog if user clicks resume after error pause

class BulkGenerationThread(QThread):
    signals = BulkGenerationSignals()

    def __init__(self, config_manager, settings_data, parent_dialog):
        super().__init__(parent_dialog)
        self.config_manager = config_manager
        self.settings = settings_data # This will contain all UI selections and loaded data
        self.parent_dialog = parent_dialog # To access methods like build_final_prompt_for_line

        self.is_running = False
        self.is_paused = False
        self.is_stopped = False
        self.current_line_index = 0
        self.current_iteration_num = 0 # For unique images per combination
        self.current_api_attempt_num = 0 # For retries of a single API call

        self.img_gen_service = None
        self.vertex_ai_available = False
        try:
            from image_generation_services import ImageGenerationService, VERTEX_AI_AVAILABLE
            self.img_gen_service = ImageGenerationService(self.config_manager)
            self.vertex_ai_available = VERTEX_AI_AVAILABLE
        except ImportError:
            print("ERROR: BulkGenerationThread could not import ImageGenerationService.")
        except Exception as e:
            print(f"ERROR: BulkGenerationThread failed to initialize ImageGenerationService: {e}")
        
    def run(self):
        if not self.img_gen_service:
            self.signals.bulk_process_finished.emit(False, "ImageGenerationService not available.")
            return

        self.is_running = True
        self.is_paused = False
        self.is_stopped = False
        
        loaded_combinations = self.settings.get("loaded_combinations", [])
        total_combinations = len(loaded_combinations)
        iterations_per_combo = self.settings.get(SETTINGS_ITERATIONS_PER_COMBO, 1)
        # api_images_per_run = self.settings.get(SETTINGS_API_IMAGES_PER_RUN, 1) # TODO: Handle API n>1 if supported

        generation_progress_state = self.settings.get(SETTINGS_GENERATION_PROGRESS, {})
        
        overall_item_count = total_combinations * iterations_per_combo
        processed_item_count = 0

        for line_idx, line_text in enumerate(loaded_combinations):
            if self.is_stopped: break
            
            line_progress = generation_progress_state.get(line_text, {
                "status": "pending", "iterations_completed": 0, "generated_files": []
            })

            if line_progress["status"] == "completed":
                processed_item_count += iterations_per_combo # Assume all iterations were done
                self.signals.progress_updated.emit(
                    int((processed_item_count / overall_item_count) * 100) if overall_item_count > 0 else 0,
                    f"Skipping completed: {line_text}"
                )
                continue

            for iter_num in range(line_progress["iterations_completed"] + 1, iterations_per_combo + 1):
                if self.is_stopped: break
                
                while self.is_paused: # Pause loop
                    self.sleep(1) # Sleep for 1 second while paused
                    if self.is_stopped: break
                if self.is_stopped: break

                self.current_line_index = line_idx
                self.current_iteration_num = iter_num
                
                current_action_msg = f"Processing: '{line_text}' (Image {iter_num}/{iterations_per_combo})"
                self.signals.progress_updated.emit(
                     int((processed_item_count / overall_item_count) * 100) if overall_item_count > 0 else 0,
                    current_action_msg
                )

                final_prompt = self.parent_dialog.build_final_prompt_for_line(line_idx)
                if not final_prompt:
                    error_msg = f"Could not build prompt for '{line_text}'."
                    self.signals.error_occurred.emit(line_text, iter_num, 0, error_msg)
                    line_progress["status"] = "error"
                    line_progress["last_error_message"] = error_msg
                    generation_progress_state[line_text] = line_progress
                    self.parent_dialog.update_generation_progress_on_main_thread(generation_progress_state) # Update UI
                    continue # Move to next iteration or line

                api_call_successful = False
                for attempt in range(1, 4): # Max 3 retries
                    if self.is_stopped: break
                    self.current_api_attempt_num = attempt
                    
                    self.signals.progress_updated.emit(
                        int((processed_item_count / overall_item_count) * 100) if overall_item_count > 0 else 0,
                        f"{current_action_msg} - API Call Attempt {attempt}/3"
                    )

                    image_model_id = self.settings.get(SETTINGS_IMAGE_MODEL_ID)
                    aspect_ratio = self.settings.get(SETTINGS_ASPECT_RATIO, "1:1")
                    negative_prompt_text = self.settings.get("negative_prompt", "") # Get from settings if stored

                    provider_type = None
                    for _, data in self.parent_dialog.image_generation_models.items():
                        if data["id"] == image_model_id:
                            provider_type = data["provider"]
                            break
                    
                    image_result_data = None
                    if provider_type == "deepai":
                        image_result_data = self.img_gen_service.generate_image_deepai(final_prompt)
                    elif provider_type == "google_vertex_ai_imagen":
                        if not self.vertex_ai_available or not self.img_gen_service.vertex_ai_initialized:
                            image_result_data = {"success": False, "error": "Vertex AI not ready."}
                        else:
                            image_result_data = self.img_gen_service.generate_image_google_imagen_vertexai(
                                model_id=image_model_id,
                                prompt=final_prompt,
                                negative_prompt=negative_prompt_text if negative_prompt_text else None,
                                aspect_ratio=aspect_ratio
                                # num_images = api_images_per_run # TODO
                            )
                    else:
                        image_result_data = {"success": False, "error": f"Unknown provider type '{provider_type}' for bulk."}

                    if image_result_data and image_result_data.get("success"):
                        img_bytes = image_result_data.get("image_bytes")
                        img_format = image_result_data.get("format", "PNG").upper()
                        if img_bytes:
                            filename = self.parent_dialog.build_filename(line_idx, line_text, iter_num, 1) # Assuming 1 image per API call for now
                            target_path = self.parent_dialog.get_target_save_path(line_idx, line_text, filename)
                            try:
                                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                                with open(target_path, "wb") as f:
                                    f.write(img_bytes)
                                self.signals.image_saved.emit(target_path, line_text, iter_num, 1)
                                if "generated_files" not in line_progress: line_progress["generated_files"] = []
                                line_progress["generated_files"].append(target_path)
                                api_call_successful = True
                                break # Success, exit retry loop
                            except Exception as e_save:
                                error_msg = f"Error saving file {target_path}: {e_save}"
                                self.signals.error_occurred.emit(line_text, iter_num, attempt, error_msg)
                                line_progress["last_error_message"] = error_msg
                                # Potentially pause here too if saving fails consistently
                        else: # Success but no image bytes
                            error_msg = "API success but no image data."
                            self.signals.error_occurred.emit(line_text, iter_num, attempt, error_msg)
                            line_progress["last_error_message"] = error_msg
                    else: # API call failed
                        error_msg = image_result_data.get("error", "Unknown API error") if image_result_data else "API call failed (no data)."
                        self.signals.error_occurred.emit(line_text, iter_num, attempt, error_msg)
                        line_progress["last_error_message"] = error_msg
                        if attempt < 3:
                            self.sleep(5) # Wait 5 seconds before retry
                        else: # All retries failed
                            self.is_paused = True # Set internal pause flag
                            self.signals.paused_due_to_error.emit(line_text, iter_num, error_msg)
                            # Thread will now loop in the self.is_paused check above until resumed or stopped
                            # Need a mechanism for the dialog to set self.is_paused = False
                
                if self.is_stopped: break

                if api_call_successful:
                    line_progress["iterations_completed"] = iter_num
                    line_progress["status"] = "in_progress" if iter_num < iterations_per_combo else "completed"
                    line_progress["last_error_message"] = None
                    processed_item_count += 1
                else: # API call failed after retries or was stopped during retries
                    line_progress["status"] = "error"
                    # Error message already set
                    generation_progress_state[line_text] = line_progress
                    self.parent_dialog.update_generation_progress_on_main_thread(generation_progress_state)
                    # If we paused due to error, the outer pause loop will handle it.
                    # If we stopped, the outer stop check will handle it.
                    # If it just failed all retries without explicit stop/pause from UI, it moves to next iter/line.
                    # This might need refinement: if retries fail and not paused by error signal, should process stop?
                    # For now, assume it logs error and continues, relying on pause_due_to_error for user intervention.
                    break # Break from iterations for this line if one API call failed badly

            generation_progress_state[line_text] = line_progress
            self.parent_dialog.update_generation_progress_on_main_thread(generation_progress_state)
            if line_progress["status"] == "error" and self.is_paused: # If an error caused a pause
                while self.is_paused: # Re-check pause state after updating progress
                    self.sleep(1)
                    if self.is_stopped: break # Allow stop during error pause
            
        self.is_running = False
        final_summary = "Bulk generation stopped by user." if self.is_stopped else "Bulk generation finished."
        if not self.is_stopped:
            all_completed = all(gp.get("status") == "completed" for gp in generation_progress_state.values())
            self.signals.bulk_process_finished.emit(all_completed, final_summary)
        else:
            self.signals.bulk_process_finished.emit(False, final_summary)


    def stop_processing(self):
        self.is_stopped = True
        self.is_paused = False # Ensure it's not stuck in pause

    def pause_processing(self):
        self.is_paused = True

    def resume_processing(self):
        self.is_paused = False
        self.signals.request_resume.emit() # Inform dialog that thread is ready to resume


class EditLayerDialog(QDialog):
    def __init__(self, layer_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Commonality Layer" if layer_data else "Add New Commonality Layer")
        
        self.layout = QVBoxLayout(self)
        
        # Layer Name
        self.layout.addWidget(QLabel("Layer Name:"))
        self.name_edit = QLineEdit(layer_data.get("name", "") if layer_data else "")
        # self.name_edit.setUndoRedoEnabled(True) # Removed incorrect call
        self.layout.addWidget(self.name_edit)

        # Filter Text
        self.layout.addWidget(QLabel("Filter Text (applied to combination lines):"))
        self.filter_edit = QLineEdit(layer_data.get("filter_text", "") if layer_data else "")
        # self.filter_edit.setUndoRedoEnabled(True) # Removed incorrect call
        self.layout.addWidget(self.filter_edit)
        self.case_sensitive_check = QCheckBox("Case Sensitive Filter")
        if layer_data and layer_data.get("case_sensitive", False):
            self.case_sensitive_check.setChecked(True)
        self.layout.addWidget(self.case_sensitive_check)

        # Filename Suffix
        self.layout.addWidget(QLabel("Filename Suffix (optional, e.g., _male):"))
        self.suffix_edit = QLineEdit(layer_data.get("suffix", "") if layer_data else "")
        # self.suffix_edit.setUndoRedoEnabled(True) # Removed incorrect call
        self.layout.addWidget(self.suffix_edit)

        # Prompt Snippet
        self.layout.addWidget(QLabel("Prompt Snippet for this Layer:"))
        self.prompt_edit = QTextEdit(layer_data.get("prompt", "") if layer_data else "")
        self.prompt_edit.setFixedHeight(80)
        self.prompt_edit.setUndoRedoEnabled(True) # Correct: This is a QTextEdit
        self.layout.addWidget(self.prompt_edit)

        # Dialog Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "filter_text": self.filter_edit.text().strip(),
            "case_sensitive": self.case_sensitive_check.isChecked(),
            "suffix": self.suffix_edit.text().strip(),
            "prompt": self.prompt_edit.toPlainText().strip()
        }


class BulkImageDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("Bulk Image Creation Mode")
        self.setMinimumSize(1000, 1000) # Consider adjusting if UI elements grow
        self.setModal(True)

        self.loaded_combinations_filepath = None
        self.loaded_combinations = [] 
        self.previous_loaded_combinations_for_settings = [] # For file change detection
        
        # Sections will store member_lines (actual text) instead of indices
        self.sections_data = [] # List of dicts: {"name", "member_lines": ["text1", "text2"], "prompt"}
        
        self.commonality_layers_data = [] 
        self.generation_progress_state = {} 
        
        self.image_generation_models = getattr(parent, 'image_generation_models', {}) # Get from main window
        self.main_window_temp_folder = getattr(parent, 'temp_image_folder', '') # Get temp folder from main

        self.generation_thread = None
        self.is_processing_paused_by_error = False

        # Last used directories for this dialog's file operations
        self.last_bulk_combinations_dir = getattr(parent, 'last_bulk_combinations_dir', str(Path.home())) if parent else str(Path.home())
        self.last_bulk_output_dir = getattr(parent, 'last_bulk_output_dir', str(Path.home())) if parent else str(Path.home())


        self.init_ui()
        self._update_section_buttons_state()
        self._update_layer_buttons_state()


    def init_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left Pane: File, List, Filters ---
        left_widget = QWidget()
        left_v_layout = QVBoxLayout(left_widget)

        self.load_combinations_file_button = QPushButton("Load Combinations File (.txt)")
        self.load_combinations_file_button.clicked.connect(self.load_combinations_file)
        left_v_layout.addWidget(self.load_combinations_file_button)
        self.loaded_file_label = QLabel("No file loaded.")
        self.loaded_file_label.setStyleSheet("font-style: italic;")
        left_v_layout.addWidget(self.loaded_file_label)

        filter_group = QGroupBox("Filter Combinations")
        filter_layout = QGridLayout(filter_group)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Enter text to filter list...")
        self.case_sensitive_filter_check = QCheckBox("Case Sensitive")
        apply_filter_button = QPushButton("Apply Filter")
        apply_filter_button.clicked.connect(self.apply_combination_filter)
        clear_filter_button = QPushButton("Clear Filter")
        clear_filter_button.clicked.connect(self.clear_combination_filter)
        filter_layout.addWidget(self.filter_input, 0, 0, 1, 2)
        filter_layout.addWidget(self.case_sensitive_filter_check, 1, 0)
        filter_layout.addWidget(apply_filter_button, 2, 0)
        filter_layout.addWidget(clear_filter_button, 2, 1)
        left_v_layout.addWidget(filter_group)
        
        self.combination_list_widget = QListWidget()
        self.combination_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.combination_list_widget.itemSelectionChanged.connect(self._update_ui_on_selection) # General UI updates
        self.combination_list_widget.setStyleSheet("QListWidget { color: white; background-color: #333333; border: 1px solid #555555; } QListWidget::item { color: white; }")
        left_v_layout.addWidget(QLabel("Combinations:"))
        left_v_layout.addWidget(self.combination_list_widget, 1) 

        self.regenerate_selected_button = QPushButton("Regenerate Selected")
        self.regenerate_selected_button.clicked.connect(self.regenerate_selected_combinations)
        self.regenerate_selected_button.setEnabled(False) 
        left_v_layout.addWidget(self.regenerate_selected_button)

        splitter.addWidget(left_widget)

        # --- Right Pane: Prompts & Settings ---
        right_widget = QWidget()
        right_v_layout = QVBoxLayout(right_widget)
        
        prompt_order_group = QGroupBox("Prompt Component Order (Drag to Reorder)")
        prompt_order_group_layout = QVBoxLayout(prompt_order_group)
        self.prompt_order_list_widget = QListWidget()
        self.prompt_order_list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.prompt_order_list_widget.setStyleSheet("QListWidget { color: white; background-color: #333333; border: 1px solid #555555; } QListWidget::item { color: white; }")
        self.prompt_order_list_widget.setFixedHeight(120) 
        self.prompt_order_list_widget.itemSelectionChanged.connect(self._update_prompt_order_button_states) # Connect specific updater
        prompt_order_group_layout.addWidget(self.prompt_order_list_widget)
        
        prompt_order_buttons_layout = QHBoxLayout()
        self.move_prompt_component_up_button = QPushButton("Move Up")
        self.move_prompt_component_up_button.clicked.connect(self.move_prompt_component_up)
        self.move_prompt_component_down_button = QPushButton("Move Down")
        self.move_prompt_component_down_button.clicked.connect(self.move_prompt_component_down)
        prompt_order_buttons_layout.addWidget(self.move_prompt_component_up_button)
        prompt_order_buttons_layout.addWidget(self.move_prompt_component_down_button)
        prompt_order_group_layout.addLayout(prompt_order_buttons_layout)
        right_v_layout.addWidget(prompt_order_group)

        sections_group = QGroupBox("Section-Specific Prompts")
        sections_layout = QHBoxLayout(sections_group)
        self.sections_list_widget = QListWidget()
        self.sections_list_widget.setMaximumHeight(100)
        self.sections_list_widget.itemClicked.connect(self.on_section_selected)
        self.sections_list_widget.setStyleSheet("QListWidget { color: white; background-color: #333333; border: 1px solid #555555; } QListWidget::item { color: white; }")
        sections_buttons_layout = QVBoxLayout()
        self.define_section_button = QPushButton("Define Section from Selection")
        self.define_section_button.clicked.connect(self.define_new_section)
        self.edit_section_prompt_button = QPushButton("Edit Section Prompt")
        self.edit_section_prompt_button.clicked.connect(self.edit_selected_section_prompt)
        self.remove_section_button = QPushButton("Remove Section")
        self.remove_section_button.clicked.connect(self.remove_selected_section)
        sections_buttons_layout.addWidget(self.define_section_button)
        sections_buttons_layout.addWidget(self.edit_section_prompt_button)
        sections_buttons_layout.addWidget(self.remove_section_button)
        sections_layout.addWidget(self.sections_list_widget, 1)
        sections_layout.addLayout(sections_buttons_layout)
        right_v_layout.addWidget(sections_group)
        self.section_prompt_edit = QTextEdit()
        self.section_prompt_edit.setPlaceholderText("Enter prompt for the selected section...")
        self.section_prompt_edit.setFixedHeight(60) 
        self.section_prompt_edit.textChanged.connect(self.on_section_prompt_changed)
        self.section_prompt_edit.setStyleSheet("QTextEdit { color: white; background-color: #404040; border: 1px solid #555555; }") 
        self.section_prompt_edit.setUndoRedoEnabled(True)
        right_v_layout.addWidget(self.section_prompt_edit)

        layers_group = QGroupBox("Commonality Layers (Overlapping)")
        layers_layout = QHBoxLayout(layers_group)
        self.commonality_layers_list_widget = QListWidget()
        self.commonality_layers_list_widget.setMaximumHeight(100)
        self.commonality_layers_list_widget.itemClicked.connect(self.on_layer_selected)
        self.commonality_layers_list_widget.setStyleSheet("QListWidget { color: white; background-color: #333333; border: 1px solid #555555; } QListWidget::item { color: white; }")
        layers_buttons_layout = QVBoxLayout()
        self.add_layer_button = QPushButton("Add New Layer")
        self.add_layer_button.clicked.connect(self.add_new_commonality_layer)
        self.edit_layer_button = QPushButton("Edit Layer")
        self.edit_layer_button.clicked.connect(self.edit_selected_commonality_layer)
        self.remove_layer_button = QPushButton("Remove Layer")
        self.remove_layer_button.clicked.connect(self.remove_selected_commonality_layer)
        layers_buttons_layout.addWidget(self.add_layer_button)
        layers_buttons_layout.addWidget(self.edit_layer_button)
        layers_buttons_layout.addWidget(self.remove_layer_button)
        layers_layout.addWidget(self.commonality_layers_list_widget, 1)
        layers_layout.addLayout(layers_buttons_layout)
        right_v_layout.addWidget(layers_group)
        
        self.selected_layer_details_label = QLabel("No layer selected. Click 'Add' or select a layer.")
        self.selected_layer_details_label.setWordWrap(True)
        self.selected_layer_details_label.setStyleSheet("font-style: italic; padding: 5px; border: 1px solid #555555; background-color: #3a3a3a; color: #e0e0e0;") 
        self.selected_layer_details_label.setMinimumHeight(40) 
        right_v_layout.addWidget(self.selected_layer_details_label)

        right_v_layout.addWidget(QLabel("Global Prompt (part of ordered prompt components):"))
        self.global_prompt_edit = QTextEdit()
        self.global_prompt_edit.setPlaceholderText("E.g., 'pixel art, fantasy character portrait, vibrant colors'...")
        self.global_prompt_edit.setFixedHeight(60) 
        self.global_prompt_edit.setStyleSheet("QTextEdit { color: white; background-color: #404040; border: 1px solid #555555; }") 
        self.global_prompt_edit.setUndoRedoEnabled(True)
        right_v_layout.addWidget(self.global_prompt_edit)

        gen_output_group = QGroupBox("Generation & Output")
        gen_output_layout = QGridLayout(gen_output_group)
        gen_output_layout.addWidget(QLabel("Image Model:"), 0, 0)
        self.image_model_bulk_combo = QComboBox()
        for name, data in self.image_generation_models.items():
            self.image_model_bulk_combo.addItem(name, data["id"])
        self.image_model_bulk_combo.currentIndexChanged.connect(self._update_aspect_ratio_bulk_visibility)
        gen_output_layout.addWidget(self.image_model_bulk_combo, 0, 1)
        
        self.aspect_ratio_bulk_label = QLabel("Aspect Ratio:")
        self.aspect_ratio_bulk_combo = QComboBox()
        self.aspect_ratio_bulk_combo.addItems(["1:1", "16:9", "9:16", "4:3", "3:4"])
        gen_output_layout.addWidget(self.aspect_ratio_bulk_label, 1, 0)
        gen_output_layout.addWidget(self.aspect_ratio_bulk_combo, 1, 1)

        self.negative_prompt_bulk_label = QLabel("Negative Prompt:")
        gen_output_layout.addWidget(self.negative_prompt_bulk_label, 2, 0)
        self.negative_prompt_input = QTextEdit() 
        self.negative_prompt_input.setPlaceholderText("Optional, e.g., blurry, text, watermark...")
        self.negative_prompt_input.setFixedHeight(40) 
        self.negative_prompt_input.setUndoRedoEnabled(True)
        gen_output_layout.addWidget(self.negative_prompt_input, 2, 1)

        gen_output_layout.addWidget(QLabel("Images per Combination:"), 3, 0) 
        self.iterations_per_combo_spinbox = QSpinBox()
        self.iterations_per_combo_spinbox.setRange(1, 100); self.iterations_per_combo_spinbox.setValue(1)
        gen_output_layout.addWidget(self.iterations_per_combo_spinbox, 3, 1) 
        
        gen_output_layout.addWidget(QLabel("Global Filename Prefix:"), 4, 0) 
        self.global_filename_prefix_edit = QLineEdit()
        self.global_filename_prefix_edit.setPlaceholderText("Optional, e.g., MyProject_")
        gen_output_layout.addWidget(self.global_filename_prefix_edit, 4, 1)
        
        gen_output_layout.addWidget(QLabel("Output Folder:"), 5, 0)
        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setReadOnly(True)
        browse_output_button = QPushButton("Browse...")
        browse_output_button.clicked.connect(self.browse_output_folder)
        output_folder_layout = QHBoxLayout()
        output_folder_layout.addWidget(self.output_folder_edit, 1)
        output_folder_layout.addWidget(browse_output_button)
        gen_output_layout.addLayout(output_folder_layout, 5, 1)
        
        self.save_to_single_folder_radio = QRadioButton("Save all to selected Output Folder")
        self.save_to_single_folder_radio.setChecked(True)
        self.save_to_matched_subfolders_radio = QRadioButton("Save to subfolders matching combinations (experimental)")
        gen_output_layout.addWidget(self.save_to_single_folder_radio, 6, 0, 1, 2)
        gen_output_layout.addWidget(self.save_to_matched_subfolders_radio, 7, 0, 1, 2)
        
        self.subfolder_exclusion_label = QLabel("Subfolder Excl. Keywords (comma-sep):")
        self.subfolder_exclusion_edit = QLineEdit()
        self.subfolder_exclusion_edit.setPlaceholderText("e.g., male, female, variant")
        self.subfolder_exclusion_label.setVisible(False)
        self.subfolder_exclusion_edit.setVisible(False)
        self.save_to_matched_subfolders_radio.toggled.connect(self.subfolder_exclusion_label.setVisible)
        self.save_to_matched_subfolders_radio.toggled.connect(self.subfolder_exclusion_edit.setVisible)
        gen_output_layout.addWidget(self.subfolder_exclusion_label, 8, 0)
        gen_output_layout.addWidget(self.subfolder_exclusion_edit, 8, 1)
        
        right_v_layout.addWidget(gen_output_group)
        right_v_layout.addStretch(1) 
        splitter.addWidget(right_widget)

        main_layout.addWidget(splitter)

        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setTextVisible(True)
        self.overall_progress_bar.setFormat("%p% - Overall")
        main_layout.addWidget(self.overall_progress_bar)
        self.current_action_status_label = QLabel("Status: Idle. Load a combinations file to begin.")
        main_layout.addWidget(self.current_action_status_label)

        action_buttons_layout = QHBoxLayout()
        self.save_settings_button = QPushButton("Save Bulk Settings")
        self.save_settings_button.clicked.connect(self.save_bulk_settings)
        self.load_settings_button = QPushButton("Load Bulk Settings")
        self.load_settings_button.clicked.connect(self.load_bulk_settings)
        action_buttons_layout.addWidget(self.save_settings_button)
        action_buttons_layout.addWidget(self.load_settings_button)
        action_buttons_layout.addStretch()
        self.start_button = QPushButton("START BULK GENERATION")
        self.start_button.setStyleSheet("background-color: lightgreen; color: black;") 
        self.start_button.clicked.connect(self.start_bulk_generation)
        self.pause_resume_button = QPushButton("Pause")
        self.pause_resume_button.clicked.connect(self.toggle_pause_resume)
        self.pause_resume_button.setEnabled(False)
        self.stop_button = QPushButton("STOP")
        self.stop_button.setStyleSheet("background-color: salmon; color: black;") 
        self.stop_button.clicked.connect(self.stop_bulk_generation)
        self.stop_button.setEnabled(False)
        
        self.close_dialog_button = QPushButton("Close Dialog") 
        self.close_dialog_button.clicked.connect(self.accept) 
        
        action_buttons_layout.addWidget(self.start_button)
        action_buttons_layout.addWidget(self.pause_resume_button)
        action_buttons_layout.addWidget(self.stop_button)
        action_buttons_layout.addStretch()
        action_buttons_layout.addWidget(self.close_dialog_button)
        main_layout.addLayout(action_buttons_layout)

        splitter.setSizes([300, 700]) 
        self._update_aspect_ratio_bulk_visibility() 
        self._apply_dark_theme_styles_to_dialog_elements()
        self._update_prompt_order_button_states() # Initial state for prompt order buttons

    def _apply_dark_theme_styles_to_dialog_elements(self):
        widget_style = "color: white; background-color: #404040; border: 1px solid #555555;"
        button_style = "color: white; background-color: #505050; border: 1px solid #666666; padding: 4px;"
        list_widget_style = "QListWidget { color: white; background-color: #333333; border: 1px solid #555555; } QListWidget::item { color: white; }"
        text_edit_style = "QTextEdit { color: white; background-color: #404040; border: 1px solid #555555; }"
        
        self.filter_input.setStyleSheet(widget_style)
        self.case_sensitive_filter_check.setStyleSheet("color: white;") 

        self.combination_list_widget.setStyleSheet(list_widget_style) # Already set, but for completeness
        self.sections_list_widget.setStyleSheet(list_widget_style)
        self.commonality_layers_list_widget.setStyleSheet(list_widget_style)
        if hasattr(self, 'prompt_order_list_widget'):
            self.prompt_order_list_widget.setStyleSheet(list_widget_style)
        
        self.section_prompt_edit.setStyleSheet(text_edit_style)
        self.global_prompt_edit.setStyleSheet(text_edit_style)
        if hasattr(self, 'negative_prompt_input'): 
            self.negative_prompt_input.setStyleSheet(text_edit_style)
        
        self.image_model_bulk_combo.setStyleSheet(widget_style)
        self.aspect_ratio_bulk_combo.setStyleSheet(widget_style)
        self.iterations_per_combo_spinbox.setStyleSheet(widget_style)
        self.global_filename_prefix_edit.setStyleSheet(widget_style)
        self.output_folder_edit.setStyleSheet(widget_style) 
        self.save_to_single_folder_radio.setStyleSheet("color: white;")
        self.save_to_matched_subfolders_radio.setStyleSheet("color: white;")
        self.subfolder_exclusion_edit.setStyleSheet(widget_style)

        buttons_to_style = [
            "define_section_button", "edit_section_prompt_button", "remove_section_button",
            "add_layer_button", "edit_layer_button", "remove_layer_button",
            "save_settings_button", "load_settings_button", 
            "pause_resume_button", "regenerate_selected_button", # Added regenerate button
            "move_prompt_component_up_button", "move_prompt_component_down_button" # Added move buttons
        ]
        for btn_name in buttons_to_style:
            if hasattr(self, btn_name):
                btn_widget = getattr(self, btn_name)
                if btn_widget: # Ensure widget exists
                    btn_widget.setStyleSheet(button_style)
        
        for group_box in self.findChildren(QGroupBox):
            for button in group_box.findChildren(QPushButton):
                if not button.styleSheet(): 
                    button.setStyleSheet(button_style)
        
        if hasattr(self, 'close_dialog_button') and self.close_dialog_button:
             self.close_dialog_button.setStyleSheet(button_style)

        for label in self.findChildren(QLabel):
            current_style = label.styleSheet()
            if "color:" not in current_style.lower(): 
                 label.setStyleSheet(current_style + "color: white;")

        for checkbox in self.findChildren(QCheckBox):
            current_style = checkbox.styleSheet()
            if "color:" not in current_style.lower():
                 checkbox.setStyleSheet(current_style + "color: white;")

    def _update_ui_on_selection(self):
        # This method is for the main combination_list_widget selection
        selected_items = self.combination_list_widget.selectedItems()
        count = len(selected_items)
        self.define_section_button.setEnabled(count > 0)
        if hasattr(self, 'regenerate_selected_button'):
            self.regenerate_selected_button.setEnabled(count > 0 and not (self.generation_thread and self.generation_thread.isRunning()))
        # Note: Prompt order button states are handled by _update_prompt_order_button_states

    def _update_section_buttons_state(self):
        has_selection = self.sections_list_widget.currentItem() is not None
        self.edit_section_prompt_button.setEnabled(has_selection)
        self.remove_section_button.setEnabled(has_selection)
        self.section_prompt_edit.setEnabled(has_selection)
        if not has_selection:
            self.section_prompt_edit.clear()

    def _update_layer_buttons_state(self):
        has_selection = self.commonality_layers_list_widget.currentItem() is not None
        self.edit_layer_button.setEnabled(has_selection)
        self.remove_layer_button.setEnabled(has_selection)
        if not has_selection:
            self.selected_layer_details_label.setText("No layer selected. Click 'Add' or select a layer.")

    def _update_aspect_ratio_bulk_visibility(self):
        selected_image_model_data_id = self.image_model_bulk_combo.currentData()
        provider = None
        for _name, data_dict in self.image_generation_models.items():
            if data_dict["id"] == selected_image_model_data_id:
                provider = data_dict["provider"]
                break
        is_imagen = (provider == "google_vertex_ai_imagen")
        self.aspect_ratio_bulk_label.setVisible(is_imagen)
        self.aspect_ratio_bulk_combo.setVisible(is_imagen)

    # --- File and List Management ---
    def load_combinations_file(self):
        if self.generation_thread and self.generation_thread.isRunning():
            QMessageBox.warning(self, "Processing Active", "Cannot load new file while generation is in progress.")
            return

        filepath, _ = QFileDialog.getOpenFileName(self, "Load Combinations File", self.last_bulk_combinations_dir, "Text Files (*.txt)")
        if filepath:
            self.last_bulk_combinations_dir = os.path.dirname(filepath)
            if self.parent(): 
                setattr(self.parent(), 'last_bulk_combinations_dir', self.last_bulk_combinations_dir)
            
            try:
                current_lines_from_file = []
                with open(filepath, 'r', encoding='utf-8') as f:
                    current_lines_from_file = [line.strip() for line in f if line.strip()]
                
                self.loaded_combinations = current_lines_from_file
                self.loaded_combinations_filepath = filepath
                self.loaded_file_label.setText(f"Loaded: {os.path.basename(filepath)} ({len(self.loaded_combinations)} lines)")
                self.current_action_status_label.setText(f"{len(self.loaded_combinations)} combinations loaded. Configure prompts and settings.")
                
                self.sections_data.clear()
                self.sections_list_widget.clear()
                self.commonality_layers_data.clear()
                self.commonality_layers_list_widget.clear()
                self.generation_progress_state.clear() 
                self.global_filename_prefix_edit.clear()
                self.global_prompt_edit.clear()
                self.negative_prompt_input.clear() # Clear negative prompt for new file
                self._update_section_buttons_state()
                self._update_layer_buttons_state()
                
                self._populate_prompt_order_list() # Reset to default order for new file initially
                self.load_bulk_settings(silent=True) # Attempt to load settings, which might override prompt order

                new_lines, missing_lines = self.compare_loaded_combinations()
                
                self.combination_list_widget.clear() 
                self.populate_combination_list_with_status(new_lines, missing_lines)

                if new_lines or missing_lines:
                    summary_message = "File content compared to saved settings:\n"
                    if new_lines:
                        summary_message += f"- {len(new_lines)} New lines found (marked [NEW]).\n"
                    if missing_lines:
                        summary_message += f"- {len(missing_lines)} Lines missing from file (progress/settings for them might be irrelevant).\n"
                    QMessageBox.information(self, "File Change Detected", summary_message)
                
                self.previous_loaded_combinations_for_settings = list(self.loaded_combinations)
                self._update_ui_on_selection() # Update button states

            except Exception as e:
                QMessageBox.critical(self, "Error Loading File", f"Could not load or parse file: {e}")
                self.loaded_file_label.setText("Error loading file.")
                traceback.print_exc()

    def apply_combination_filter(self):
        filter_text = self.filter_input.text()
        case_sensitive = self.case_sensitive_filter_check.isChecked()
        
        self.combination_list_widget.clear()
        if not filter_text:
            self.combination_list_widget.addItems(self.loaded_combinations)
            return

        for item_text in self.loaded_combinations:
            text_to_check = item_text if case_sensitive else item_text.lower()
            filter_to_check = filter_text if case_sensitive else filter_text.lower()
            if filter_to_check in text_to_check:
                self.combination_list_widget.addItem(item_text)
                
    def clear_combination_filter(self):
        self.filter_input.clear()
        self.combination_list_widget.clear()
        self.combination_list_widget.addItems(self.loaded_combinations)


    # --- Prompt Layering & Assignments Logic (Sections & Commonality Layers) ---
    def define_new_section(self):
        selected_items = self.combination_list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Select lines from the combination list to define a section.")
            return
        
        # Get the TEXT of the selected lines
        member_lines_texts = sorted(list(set(item.text().replace("[NEW] ", "").replace("[MISSING] ", "").split(" (Status:")[0].strip() for item in selected_items))) # Get original text
        
        if not member_lines_texts:
            QMessageBox.warning(self, "Error", "Could not retrieve text from selected items.")
            return

        # Check for overlap: A line should not be in more than one section.
        for line_text in member_lines_texts:
            for existing_section in self.sections_data:
                if line_text in existing_section.get("member_lines", []):
                    QMessageBox.warning(self, "Overlap Detected", 
                                        f"Line '{line_text}' is already part of section '{existing_section.get('name')}'.\n"
                                        "Lines can only belong to one section.")
                    return

        # Create a display name for the section (can be edited later by user if needed)
        first_line_display = member_lines_texts[0][:20] + "..." if len(member_lines_texts[0]) > 20 else member_lines_texts[0]
        last_line_display = member_lines_texts[-1][:20] + "..." if len(member_lines_texts[-1]) > 20 else member_lines_texts[-1]
        section_name = f"Section {len(self.sections_data) + 1} ({first_line_display} ... {last_line_display})"
        
        new_section = {"name": section_name, "member_lines": member_lines_texts, "prompt": ""}
        self.sections_data.append(new_section)
        
        # Add to UI list and select it
        list_item = QListWidgetItem(section_name)
        list_item.setData(Qt.ItemDataRole.UserRole, len(self.sections_data) - 1) # Store index to sections_data
        self.sections_list_widget.addItem(list_item)
        self.sections_list_widget.setCurrentItem(list_item) # Auto-select the new section
        self.on_section_selected(list_item) # Trigger prompt display
        self._update_section_buttons_state()

    def on_section_selected(self, current_item: QListWidgetItem):
        if not current_item: 
            self.section_prompt_edit.clear()
            self.section_prompt_edit.setEnabled(False)
            self._update_section_buttons_state()
            return

        # Retrieve section data using stored index or by matching name (index is safer)
        selected_idx = current_item.data(Qt.ItemDataRole.UserRole) # Assuming we store index
        if selected_idx is not None and 0 <= selected_idx < len(self.sections_data):
            section_data = self.sections_data[selected_idx]
            self.section_prompt_edit.setText(section_data.get("prompt", ""))
            self.section_prompt_edit.setEnabled(True)
        else: # Fallback by name if index not stored or invalid (less ideal)
            section_name_from_list = current_item.text()
            found_section = None
            for i, sec in enumerate(self.sections_data):
                if sec.get("name") == section_name_from_list:
                    found_section = sec
                    current_item.setData(Qt.ItemDataRole.UserRole, i) # Store index now
                    break
            if found_section:
                self.section_prompt_edit.setText(found_section.get("prompt", ""))
                self.section_prompt_edit.setEnabled(True)
            else: # Should not happen if list is in sync with data
                self.section_prompt_edit.clear()
                self.section_prompt_edit.setEnabled(False)
        self._update_section_buttons_state()

    def on_section_prompt_changed(self):
        current_item = self.sections_list_widget.currentItem()
        if not current_item: return
        
        selected_idx = current_item.data(Qt.ItemDataRole.UserRole)
        if selected_idx is not None and 0 <= selected_idx < len(self.sections_data):
            self.sections_data[selected_idx]["prompt"] = self.section_prompt_edit.toPlainText()
        else: # Fallback by name (less ideal)
            section_name_from_list = current_item.text()
            for i, sec_data in enumerate(self.sections_data):
                if sec_data.get("name") == section_name_from_list:
                    sec_data["prompt"] = self.section_prompt_edit.toPlainText()
                    current_item.setData(Qt.ItemDataRole.UserRole, i) # Ensure index is stored
                    break
    def edit_selected_section_prompt(self): # Could be merged with on_section_selected if UI allows direct edit
        self.on_section_selected(self.sections_list_widget.currentItem()) # Ensure prompt edit is populated

    def remove_selected_section(self):
            current_item = self.sections_list_widget.currentItem()
            if not current_item: return
            
            selected_idx = current_item.data(Qt.ItemDataRole.UserRole)
            row_to_remove = self.sections_list_widget.row(current_item)

            if selected_idx is not None and 0 <= selected_idx < len(self.sections_data):
                # Confirm removal by name from data, then by index if names could be non-unique
                # For safety, if index from item data is valid, use it.
                del self.sections_data[selected_idx]
                self.sections_list_widget.takeItem(row_to_remove)
                
                # Re-assign UserRole data (indices) for remaining items in the list widget
                for i in range(self.sections_list_widget.count()):
                    list_item = self.sections_list_widget.item(i)
                    # Find corresponding section in self.sections_data by name (assuming names are unique enough for this UI context)
                    # or re-index self.sections_data if names are not guaranteed unique
                    # For simplicity now, assume item text (name) can find its new index in the modified self.sections_data
                    item_text_name = list_item.text()
                    new_data_idx = -1
                    for data_idx, sec_item_data in enumerate(self.sections_data):
                        if sec_item_data.get("name") == item_text_name:
                            new_data_idx = data_idx
                            break
                    if new_data_idx != -1:
                        list_item.setData(Qt.ItemDataRole.UserRole, new_data_idx)
                    else: # Should not happen if names are consistent
                        print(f"Warning: Could not re-index section item: {item_text_name}")


            elif row_to_remove != -1 : # Fallback if UserRole data was missing, try by row (less safe if data out of sync)
                self.sections_list_widget.takeItem(row_to_remove)
                # Here, self.sections_data would need more complex reconciliation if only row is known.
                # This path indicates a potential issue. For now, focus on UserRole index.
                print("Warning: Removed section from UI by row, data sync might be imperfect if UserRole index was missing.")


            self.section_prompt_edit.clear()
            self.section_prompt_edit.setEnabled(False)
            self._update_section_buttons_state()

    def add_new_commonality_layer(self):
        dialog = EditLayerDialog(parent=self)
        if dialog.exec():
            layer_data = dialog.get_data()
            if not layer_data["name"]: layer_data["name"] = f"Layer {len(self.commonality_layers_data) + 1}"
            self.commonality_layers_data.append(layer_data)
            self.commonality_layers_list_widget.addItem(QListWidgetItem(layer_data["name"]))
            self._populate_prompt_order_list(current_order=self.get_current_prompt_order_from_ui()) # Refresh order list
        self._update_layer_buttons_state()
        self.on_layer_selected(self.commonality_layers_list_widget.currentItem())

    def edit_selected_commonality_layer(self):
        current_item = self.commonality_layers_list_widget.currentItem()
        if not current_item: return
        selected_index = self.commonality_layers_list_widget.row(current_item)
        if 0 <= selected_index < len(self.commonality_layers_data):
            layer_data = self.commonality_layers_data[selected_index]
            dialog = EditLayerDialog(layer_data=layer_data, parent=self)
            if dialog.exec():
                updated_data = dialog.get_data()
                if not updated_data["name"]: updated_data["name"] = layer_data["name"] 
                self.commonality_layers_data[selected_index] = updated_data
                current_item.setText(updated_data["name"])
                self._populate_prompt_order_list(current_order=self.get_current_prompt_order_from_ui()) # Refresh order list
        self.on_layer_selected(current_item)

    def remove_selected_commonality_layer(self):
        current_item = self.commonality_layers_list_widget.currentItem()
        if not current_item: return
        selected_index = self.commonality_layers_list_widget.row(current_item)
        if 0 <= selected_index < len(self.commonality_layers_data):
            del self.commonality_layers_data[selected_index]
            self.commonality_layers_list_widget.takeItem(selected_index)
            self._populate_prompt_order_list(current_order=self.get_current_prompt_order_from_ui()) # Refresh order list
        self._update_layer_buttons_state()
        self.on_layer_selected(self.commonality_layers_list_widget.currentItem())

    def on_layer_selected(self, current_item: QListWidgetItem):
        if not current_item:
            self.selected_layer_details_label.setText("No layer selected.")
            return
        selected_index = self.commonality_layers_list_widget.row(current_item)
        if 0 <= selected_index < len(self.commonality_layers_data):
            layer = self.commonality_layers_data[selected_index]
            details = (f"Name: {layer['name']}\n"
                       f"Filter: '{layer['filter_text']}' (Case Sensitive: {layer['case_sensitive']})\n"
                       f"Suffix: '{layer['suffix']}'\n"
                       f"Prompt: {layer['prompt'][:100]}{'...' if len(layer['prompt']) > 100 else ''}")
            self.selected_layer_details_label.setText(details)
        self._update_layer_buttons_state()


    # --- Settings Persistence ---
    def get_settings_filepath(self):
        if not self.loaded_combinations_filepath:
            return None
        return self.loaded_combinations_filepath + ".bulk_settings.json"

    def save_bulk_settings(self):
        settings_filepath = self.get_settings_filepath()
        if not settings_filepath:
            QMessageBox.warning(self, "Cannot Save Settings", "No combinations file loaded to associate settings with.")
            return

        current_prompt_order = self.get_current_prompt_order_from_ui()

        settings_data = {
            SETTINGS_COMBINATIONS_FILE: self.loaded_combinations_filepath,
            "previous_loaded_combinations_content_for_settings": list(self.loaded_combinations),
            SETTINGS_SECTIONS: self.sections_data, 
            SETTINGS_COMMONALITY_LAYERS: self.commonality_layers_data,
            SETTINGS_GLOBAL_PROMPT: self.global_prompt_edit.toPlainText(),
            SETTINGS_IMAGE_MODEL_ID: self.image_model_bulk_combo.currentData(),
            SETTINGS_ASPECT_RATIO: self.aspect_ratio_bulk_combo.currentText(),
            SETTINGS_ITERATIONS_PER_COMBO: self.iterations_per_combo_spinbox.value(),
            SETTINGS_API_IMAGES_PER_RUN: 1, 
            SETTINGS_GLOBAL_FILENAME_PREFIX: self.global_filename_prefix_edit.text(),
            SETTINGS_OUTPUT_FOLDER: self.output_folder_edit.text(),
            SETTINGS_SAVE_TO_SINGLE_FOLDER: self.save_to_single_folder_radio.isChecked(),
            SETTINGS_SUBFOLDER_EXCLUSION: self.subfolder_exclusion_edit.text(),
            SETTINGS_GENERATION_PROGRESS: self.generation_progress_state,
            "negative_prompt": self.negative_prompt_input.toPlainText().strip(),
            SETTINGS_PROMPT_COMPONENT_ORDER: current_prompt_order # Save prompt order
        }
        try:
            with open(settings_filepath, 'w', encoding='utf-8') as f:
                json.dump(settings_data, f, indent=2)
            self.current_action_status_label.setText(f"Bulk settings saved to {os.path.basename(settings_filepath)}")
        except Exception as e:
            QMessageBox.critical(self, "Error Saving Settings", f"Could not save bulk settings: {e}")
            traceback.print_exc()

    def load_bulk_settings(self, silent=False):
            settings_filepath = self.get_settings_filepath()
            if not settings_filepath or not os.path.exists(settings_filepath):
                if not silent:
                    QMessageBox.information(self, "No Settings", "No saved bulk settings found for this combinations file.")
                self.previous_loaded_combinations_for_settings = []
                self._populate_prompt_order_list() # Populate with default if no settings
                return

            try:
                with open(settings_filepath, 'r', encoding='utf-8') as f:
                    settings_data = json.load(f)

                self.previous_loaded_combinations_for_settings = settings_data.get("previous_loaded_combinations_content_for_settings", [])
                self.sections_data = settings_data.get(SETTINGS_SECTIONS, [])
                for sec in self.sections_data:
                    if "line_indices" in sec and "member_lines" not in sec: 
                        sec["member_lines"] = [self.previous_loaded_combinations_for_settings[i] for i in sec["line_indices"] if 0 <= i < len(self.previous_loaded_combinations_for_settings)]

                self.commonality_layers_data = settings_data.get(SETTINGS_COMMONALITY_LAYERS, [])
                self.global_prompt_edit.setPlainText(settings_data.get(SETTINGS_GLOBAL_PROMPT, ""))
                
                idx = self.image_model_bulk_combo.findData(settings_data.get(SETTINGS_IMAGE_MODEL_ID))
                if idx >= 0: self.image_model_bulk_combo.setCurrentIndex(idx)
                
                idx = self.aspect_ratio_bulk_combo.findText(settings_data.get(SETTINGS_ASPECT_RATIO, "1:1"))
                if idx >= 0: self.aspect_ratio_bulk_combo.setCurrentIndex(idx)

                self.iterations_per_combo_spinbox.setValue(settings_data.get(SETTINGS_ITERATIONS_PER_COMBO, 1))
                self.global_filename_prefix_edit.setText(settings_data.get(SETTINGS_GLOBAL_FILENAME_PREFIX, ""))
                
                loaded_output_folder = settings_data.get(SETTINGS_OUTPUT_FOLDER, "")
                self.output_folder_edit.setText(loaded_output_folder)
                if loaded_output_folder: self.last_bulk_output_dir = loaded_output_folder

                if settings_data.get(SETTINGS_SAVE_TO_SINGLE_FOLDER, True):
                    self.save_to_single_folder_radio.setChecked(True)
                else:
                    self.save_to_matched_subfolders_radio.setChecked(True)
                self.subfolder_exclusion_edit.setText(settings_data.get(SETTINGS_SUBFOLDER_EXCLUSION, ""))
                
                self.generation_progress_state = settings_data.get(SETTINGS_GENERATION_PROGRESS, {})
                self.negative_prompt_input.setPlainText(settings_data.get("negative_prompt", ""))

                # Load prompt order
                loaded_prompt_order = settings_data.get(SETTINGS_PROMPT_COMPONENT_ORDER)
                self._populate_prompt_order_list(current_order=loaded_prompt_order) # Pass loaded order

                self.sections_list_widget.clear()
                for sec_idx, sec in enumerate(self.sections_data):
                    list_item = QListWidgetItem(sec.get("name", f"Unnamed Section {sec_idx+1}"))
                    list_item.setData(Qt.ItemDataRole.UserRole, sec_idx)
                    self.sections_list_widget.addItem(list_item)

                self.commonality_layers_list_widget.clear()
                for layer in self.commonality_layers_data: self.commonality_layers_list_widget.addItem(layer.get("name", "Unnamed Layer"))
                
                self._update_section_buttons_state()
                self._update_layer_buttons_state()
                self._update_aspect_ratio_bulk_visibility()

                if not silent:
                    self.current_action_status_label.setText("Bulk settings loaded.")
            except Exception as e:
                if not silent:
                    QMessageBox.critical(self, "Error Loading Settings", f"Could not load/apply bulk settings: {e}")
                traceback.print_exc()
                self.previous_loaded_combinations_for_settings = []
                self._populate_prompt_order_list() # Populate with default on error

    # --- Prompt and Filename Construction ---
    def build_final_prompt_for_line(self, line_index_in_loaded_combinations_or_line_text):
        line_text_to_process = "" 
        if isinstance(line_index_in_loaded_combinations_or_line_text, int):
            line_idx = line_index_in_loaded_combinations_or_line_text
            if not (0 <= line_idx < len(self.loaded_combinations)): return ""
            line_text_to_process = self.loaded_combinations[line_idx]
        elif isinstance(line_index_in_loaded_combinations_or_line_text, str):
            line_text_to_process = line_index_in_loaded_combinations_or_line_text
        else: return ""

        final_prompt_parts = []
        current_prompt_order = self.get_current_prompt_order_from_ui()

        for component_info in current_prompt_order:
            comp_type = component_info.get("type")
            comp_id = component_info.get("id") 

            if comp_type == "global_prompt":
                global_prompt_text = self.global_prompt_edit.toPlainText().strip()
                if global_prompt_text: final_prompt_parts.append(global_prompt_text)
            # elif comp_type == "line_text": # THIS COMPONENT TYPE IS NO LONGER ADDED TO current_prompt_order
            #     pass # Explicitly do nothing if "line_text" somehow appears
            elif comp_type == "section_prompt":
                for section in self.sections_data:
                    if line_text_to_process in section.get("member_lines", []):
                        if section.get("prompt"): final_prompt_parts.append(section["prompt"])
                        break 
            elif comp_type == "commonality_layer":
                for layer in self.commonality_layers_data:
                    if layer.get("name") == comp_id: 
                        filter_text = layer.get("filter_text", "")
                        # line_text_to_process is still used here for filtering, but not added to prompt
                        text_to_check_for_layer = line_text_to_process 
                        if not layer.get("case_sensitive", False):
                            filter_text = filter_text.lower()
                            text_to_check_for_layer = text_to_check_for_layer.lower()
                        if filter_text and filter_text in text_to_check_for_layer:
                            if layer.get("prompt"): final_prompt_parts.append(layer["prompt"])
                        break 
            
        return ", ".join(filter(None, final_prompt_parts))
    def build_filename(self, line_index, line_text, iteration_num, image_in_iteration_num):
        # Naming: [iter]_[global_prefix]_[line_text_slug]_[suffixes_from_layers]_[img_num_in_iter (if >1)].png
        # For now, api_images_per_run is 1, so image_in_iteration_num is 1.
        
        prefix = self.global_filename_prefix_edit.text().strip()
        line_slug = "".join(c if c.isalnum() else "_" for c in line_text).strip("_")[:50] # Sanitize and shorten
        
        suffixes = []
        for layer in self.commonality_layers_data:
            filter_text = layer.get("filter_text", "")
            text_to_check = line_text
            if not layer.get("case_sensitive", False):
                filter_text = filter_text.lower()
                text_to_check = text_to_check.lower()
            if filter_text and filter_text in text_to_check:
                if layer.get("suffix"):
                    suffixes.append(layer["suffix"].strip("_"))
        
        suffix_str = ("_" + "_".join(filter(None, suffixes))) if suffixes else ""
        
        # Default format is PNG, actual format comes from API response.
        # We'll save with format from API, this is just for a base name.
        filename = f"{iteration_num}{'_' + prefix if prefix else ''}_{line_slug}{suffix_str}.png" 
        return filename.replace("__", "_") # Clean up double underscores

    def get_target_save_path(self, line_index, line_text, filename_with_extension):
        base_output_folder = self.output_folder_edit.text()
        if not base_output_folder or not os.path.isdir(base_output_folder):
            print(f"Warning: Output folder '{base_output_folder}' is not valid. Defaulting to app directory.")
            base_output_folder = Path(self.loaded_combinations_filepath).parent if self.loaded_combinations_filepath else APP_DIR

        if self.save_to_single_folder_radio.isChecked():
            return os.path.join(base_output_folder, filename_with_extension)
        else: # Matched subfolders
            exclusion_keywords_str = self.subfolder_exclusion_edit.text().strip()
            exclusions = [kw.strip().lower() for kw in exclusion_keywords_str.split(',') if kw.strip()]
            
            folder_name_parts = []
            for part in line_text.split('_'): # Assuming underscore delimiter in combination
                if part.lower() not in exclusions:
                    folder_name_parts.append(part)
            
            subfolder_name = "_".join(folder_name_parts) if folder_name_parts else "Uncategorized"
            subfolder_name = "".join(c if c.isalnum() or c in "-_" else "" for c in subfolder_name) # Sanitize
            
            target_folder = os.path.join(base_output_folder, subfolder_name)
            return os.path.join(target_folder, filename_with_extension)

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.output_folder_edit.text() or str(Path.home()))
        if folder:
            self.output_folder_edit.setText(folder)

    # --- Generation Process Control ---
    def start_bulk_generation(self):
        if not self.loaded_combinations_filepath or not self.loaded_combinations:
            QMessageBox.warning(self, "No Data", "Please load a combinations file first."); return
        if not self.output_folder_edit.text() or not os.path.isdir(self.output_folder_edit.text()):
            QMessageBox.warning(self, "No Output Folder", "Please select a valid output folder."); return
        if not self.image_model_bulk_combo.currentData():
            QMessageBox.warning(self, "No Model", "Please select an image generation model."); return

        if self.generation_progress_state and any(v.get("status") != "completed" for v in self.generation_progress_state.values()):
            reply = QMessageBox.question(self, "Resume Generation?",
                                         "Previous bulk generation for this file was not fully completed or items were reset. "
                                         "Do you want to resume (process pending/reset items) or clear all progress and restart everything?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                         QMessageBox.StandardButton.Yes) 
            if reply == QMessageBox.StandardButton.Cancel: return
            if reply == QMessageBox.StandardButton.No: 
                self.generation_progress_state.clear() 
                self.update_combination_list_statuses() 
        else: 
             self.generation_progress_state.clear()
             self.update_combination_list_statuses()

        self.start_button.setEnabled(False)
        self.load_settings_button.setEnabled(False); self.save_settings_button.setEnabled(False)
        if hasattr(self, 'load_combinations_file_button'):
            self.load_combinations_file_button.setEnabled(False) 
        if hasattr(self, 'regenerate_selected_button'):
            self.regenerate_selected_button.setEnabled(False)


        self.pause_resume_button.setEnabled(True); self.pause_resume_button.setText("Pause")
        self.stop_button.setEnabled(True)
        self.is_processing_paused_by_error = False

        current_settings = self._gather_current_settings_for_thread()
        self.generation_thread = BulkGenerationThread(self.config_manager, current_settings, self)
        self.generation_thread.signals.progress_updated.connect(self.on_thread_progress_update)
        self.generation_thread.signals.image_saved.connect(self.on_thread_image_saved)
        self.generation_thread.signals.error_occurred.connect(self.on_thread_error)
        self.generation_thread.signals.paused_due_to_error.connect(self.on_thread_paused_by_error)
        self.generation_thread.signals.bulk_process_finished.connect(self.on_thread_bulk_finished)
        self.generation_thread.signals.request_resume.connect(self.on_thread_request_resume_ack) 
        
        self.generation_thread.start()
        self.current_action_status_label.setText("Bulk generation started...")
        
    def _gather_current_settings_for_thread(self):
        # This ensures the thread gets a snapshot of settings at the time of start
        return {
            "loaded_combinations": list(self.loaded_combinations), # Send a copy
            SETTINGS_SECTIONS: list(self.sections_data), # Send a copy
            SETTINGS_COMMONALITY_LAYERS: list(self.commonality_layers_data), # Send a copy
            SETTINGS_GLOBAL_PROMPT: self.global_prompt_edit.toPlainText(),
            SETTINGS_IMAGE_MODEL_ID: self.image_model_bulk_combo.currentData(),
            SETTINGS_ASPECT_RATIO: self.aspect_ratio_bulk_combo.currentText(),
            SETTINGS_ITERATIONS_PER_COMBO: self.iterations_per_combo_spinbox.value(),
            # SETTINGS_API_IMAGES_PER_RUN: self.api_images_per_run_spinbox.value(),
            SETTINGS_GLOBAL_FILENAME_PREFIX: self.global_filename_prefix_edit.text(),
            SETTINGS_OUTPUT_FOLDER: self.output_folder_edit.text(),
            SETTINGS_SAVE_TO_SINGLE_FOLDER: self.save_to_single_folder_radio.isChecked(),
            SETTINGS_SUBFOLDER_EXCLUSION: self.subfolder_exclusion_edit.text(),
            SETTINGS_GENERATION_PROGRESS: dict(self.generation_progress_state), # Send a copy
            "negative_prompt": self.negative_prompt_input.toPlainText().strip() # Include negative prompt
        }

    def toggle_pause_resume(self):
        if not self.generation_thread or not self.generation_thread.isRunning():
            return

        if self.generation_thread.is_paused:
            self.generation_thread.resume_processing()
            # Button text will be updated by on_thread_request_resume_ack or progress update
        else:
            self.generation_thread.pause_processing()
            self.pause_resume_button.setText("Resume")
            self.current_action_status_label.setText("Processing paused by user...")

    def stop_bulk_generation(self):
        if self.generation_thread and self.generation_thread.isRunning():
            self.current_action_status_label.setText("Stopping bulk generation...")
            self.generation_thread.stop_processing()
            # UI will be fully re-enabled in on_thread_bulk_finished
            self.pause_resume_button.setEnabled(False)
            self.stop_button.setEnabled(False) # Disable stop once clicked
            # User might need to wait a moment for thread to fully stop.


    # --- Thread Signal Slots ---
    def on_thread_progress_update(self, percentage, message):
        self.overall_progress_bar.setValue(percentage)
        self.current_action_status_label.setText(message)
        self.update_combination_list_statuses() # Reflect progress in list

    def on_thread_image_saved(self, filepath, line_text, iteration_num, image_in_iteration_num):
        print(f"SUCCESS: Saved '{filepath}' for '{line_text}' (Iter {iteration_num})")
        # Update progress state is handled by the thread internally and synced via update_generation_progress_on_main_thread
        # self.update_combination_list_statuses() # Already called by progress_update

    def on_thread_error(self, line_text, iteration_num, attempt_num, error_msg):
        print(f"ERROR: Line '{line_text}', Iter {iteration_num}, Attempt {attempt_num}: {error_msg}")
        self.current_action_status_label.setText(f"Error on '{line_text}' (Iter {iteration_num}): {error_msg[:100]}...")
        # Progress state updated by thread and synced via update_generation_progress_on_main_thread

    def on_thread_paused_by_error(self, line_text, iteration_num, error_msg):
        self.is_processing_paused_by_error = True
        self.pause_resume_button.setText("Resume (after error)")
        self.pause_resume_button.setEnabled(True) # Ensure resume is possible
        self.current_action_status_label.setText(f"PAUSED due to error on '{line_text}' (Iter {iteration_num}): {error_msg}")
        QMessageBox.warning(self, "Processing Paused", 
                            f"Bulk generation paused due to an error after 3 attempts on:\n"
                            f"Line: {line_text}\n"
                            f"Iteration: {iteration_num}\n"
                            f"Error: {error_msg}\n\n"
                            "Please check the issue (e.g., API key, network, model availability) and then either 'Resume' or 'STOP'.")

    def on_thread_request_resume_ack(self): # When thread acknowledges it's no longer paused
        self.is_processing_paused_by_error = False
        self.pause_resume_button.setText("Pause")
        self.current_action_status_label.setText("Processing resumed...")


    def on_thread_bulk_finished(self, completed_fully, summary_message):
        self.overall_progress_bar.setValue(100 if completed_fully else self.overall_progress_bar.value())
        self.current_action_status_label.setText(summary_message)
        QMessageBox.information(self, "Bulk Generation Finished", summary_message)
        
        self.start_button.setEnabled(True)
        self.load_settings_button.setEnabled(True); self.save_settings_button.setEnabled(True)
        if hasattr(self, 'load_combinations_file_button'):
             self.load_combinations_file_button.setEnabled(True)
        if hasattr(self, 'regenerate_selected_button'):
            self.regenerate_selected_button.setEnabled(self.combination_list_widget.count() > 0 and len(self.combination_list_widget.selectedItems()) > 0)


        self.pause_resume_button.setEnabled(False); self.pause_resume_button.setText("Pause")
        self.stop_button.setEnabled(False)
        
        self.generation_thread = None 
        self.update_combination_list_statuses() 
        self.save_bulk_settings() 

    def update_generation_progress_on_main_thread(self, new_progress_state):
        """Called by thread (via signal if proper thread safety needed) or directly after thread finishes."""
        self.generation_progress_state = new_progress_state
        self.update_combination_list_statuses()

    def update_combination_list_statuses(self):
        # This method needs to correctly map the display items (which might be filtered)
        # back to their original line text for progress lookup.
        # For now, it assumes the text of the QListWidgetItem IS the original line text
        # (potentially with a status prefix we need to strip for lookup).

        for i in range(self.combination_list_widget.count()):
            item = self.combination_list_widget.item(i)
            displayed_text = item.text()
            
            # Extract original line text from displayed text (strip status prefixes)
            original_line_text = displayed_text
            prefixes_to_strip = ["[DONE] ", "[ERROR] ", "[NEW] ", "[MISSING] ", "[Pending] "]
            # Also strip iteration progress like "[Processing 1/3] "
            if original_line_text.startswith("[Processing ") and "]" in original_line_text:
                original_line_text = original_line_text.split("] ", 1)[-1]

            for prefix in prefixes_to_strip:
                if original_line_text.startswith(prefix):
                    original_line_text = original_line_text[len(prefix):]
            
            # Handle cases where original_line_text might still have status from a previous run if not cleared properly
            # This part is tricky if the list is filtered and items don't directly map 1:1 to self.loaded_combinations
            # A robust solution would store original_line_text or original_index as item.data() when populating the list.

            # For this iteration, let's assume original_line_text is recoverable.
            progress = self.generation_progress_state.get(original_line_text)
            item_font = item.font() # Get current font to preserve it

            if progress:
                status = progress.get("status", "pending")
                iters_done = progress.get("iterations_completed", 0)
                total_iters = self.iterations_per_combo_spinbox.value()
                
                if status == "completed":
                    item.setText(f"[DONE] {original_line_text}")
                    item.setForeground(QColor("lightgreen"))
                elif status == "error":
                    err_msg_short = progress.get("last_error_message", "Unknown error")[:30]
                    item.setText(f"[ERROR] {original_line_text} (Iter {iters_done+1}) - {err_msg_short}...")
                    item.setForeground(QColor("salmon"))
                elif status == "in_progress":
                    item.setText(f"[Processing {iters_done+1}/{total_iters}] {original_line_text}")
                    item.setForeground(QColor("lightblue"))
                else: # pending
                    item.setText(f"{original_line_text}") # No prefix for plain pending after initial load
                    item.setForeground(QColor("white")) # Default for dark theme
            else: # No progress info yet (e.g., after loading a new file)
                # Check if it's a "new" or "missing" line based on initial comparison
                new_lines, missing_lines = self.compare_loaded_combinations(perform_comparison=False) # Get pre-calculated
                if original_line_text in new_lines:
                    item.setText(f"[NEW] {original_line_text}")
                    item.setForeground(QColor("yellow"))
                elif original_line_text in missing_lines: # Should not happen if list shows current file
                    item.setText(f"[MISSING?] {original_line_text}") # This state is odd here
                    item.setForeground(QColor("gray"))
                else:
                    item.setText(f"{original_line_text}") # Default display for pending
                    item.setForeground(QColor("white"))
            item.setFont(item_font) # Reapply font

    def closeEvent(self, event):
        if self.generation_thread and self.generation_thread.isRunning():
            reply = QMessageBox.question(self, "Confirm Close",
                                         "Bulk generation is in progress. Are you sure you want to stop it and close?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_bulk_generation()
                # Wait for thread to finish? Or just accept and let it terminate?
                # For now, let's assume stop_bulk_generation signals it, and it will finish soon.
                QTimer.singleShot(500, self.accept) # Give thread a moment to react
                event.ignore() # Ignore immediate close, wait for timer
                return
            else:
                event.ignore()
                return
        
        # Save settings before closing if not processing
        self.save_bulk_settings() # Save current UI state and progress
        super().closeEvent(event)

    def compare_loaded_combinations(self, perform_comparison=True):
        """
        Compares self.loaded_combinations with self.previous_loaded_combinations_for_settings.
        Returns (new_lines_set, missing_lines_set).
        If perform_comparison is False, it returns previously stored comparison results if any.
        This needs a more robust way to store comparison results if used like that.
        For now, it always re-calculates if perform_comparison is True.
        """
        if not perform_comparison: # This part is conceptual if we want to cache comparison
            # return self._cached_new_lines or set(), self._cached_missing_lines or set()
            # For now, always re-compare if called explicitly or ensure previous_loaded is set.
            pass

        current_set = set(self.loaded_combinations)
        previous_set = set(self.previous_loaded_combinations_for_settings)

        new_lines = current_set - previous_set
        missing_lines = previous_set - current_set
        return new_lines, missing_lines

    def populate_combination_list_with_status(self, new_lines_set=None, missing_lines_set=None):
        """Populates the combination list widget, adding status prefixes and ensuring text is white."""
        self.combination_list_widget.clear()
        
        if new_lines_set is None: new_lines_set = set()
        if missing_lines_set is None: missing_lines_set = set()
        # If called without explicit sets, it means we just want to refresh display based on current state
        # The compare_loaded_combinations() would ideally be called once after settings load.

        # Ensure all items added to combination_list_widget have white text by default
        # The list widget itself also has a stylesheet for general item color.
        # self.combination_list_widget.setStyleSheet("QListWidget::item { color: white; }") # Set once if needed

        for line_text in self.loaded_combinations:
            item = QListWidgetItem()
            item.setForeground(QColor("white")) # Explicitly set default text color for each item
            
            progress = self.generation_progress_state.get(line_text)
            display_text = line_text

            if progress:
                status = progress.get("status", "pending")
                iters_done = progress.get("iterations_completed", 0)
                total_iters = self.iterations_per_combo_spinbox.value()
                if status == "completed": 
                    display_text = f"[DONE] {line_text}"
                    item.setForeground(QColor("lightgreen"))
                elif status == "error": 
                    display_text = f"[ERROR] {line_text}"
                    item.setForeground(QColor("salmon"))
                elif status == "in_progress": 
                    display_text = f"[Processing {iters_done+1}/{total_iters}] {line_text}"
                    item.setForeground(QColor("lightblue"))
                # else use default white for pending
            elif line_text in new_lines_set: # Check against the passed new_lines_set
                display_text = f"[NEW] {line_text}"
                item.setForeground(QColor("yellow"))
            
            item.setText(display_text)
            item.setData(Qt.ItemDataRole.UserRole, line_text) 
            self.combination_list_widget.addItem(item)

    def _populate_prompt_order_list(self, current_order=None):
        if not hasattr(self, 'prompt_order_list_widget'):
            return

        self.prompt_order_list_widget.clear()
        
        # Remove "line_text" from default definitions
        default_order_definitions = [
            {"type": "global_prompt", "display_name": "Global Prompt", "id": "global_prompt"},
            # {"type": "line_text", "display_name": "Line Text (Combination)", "id": "line_text"}, # REMOVED
            {"type": "section_prompt", "display_name": "Section Prompt", "id": "section_prompt"}
        ]
        
        layer_definitions = []
        for layer in self.commonality_layers_data:
            layer_name = layer.get("name", "Unnamed Layer")
            layer_definitions.append({
                "type": "commonality_layer", 
                "display_name": f"Layer: {layer_name}", 
                "id": layer_name 
            })

        final_component_list = []
        all_available_components = default_order_definitions + layer_definitions

        if current_order:
            for ordered_item_info in current_order:
                # Skip "line_text" if found in old saved order
                if ordered_item_info.get("type") == "line_text":
                    continue

                found_component = next((comp for comp in all_available_components 
                                        if comp["type"] == ordered_item_info.get("type") and 
                                           comp["id"] == ordered_item_info.get("id")), None)
                if found_component and found_component not in final_component_list:
                    final_component_list.append(found_component)
            
            for available_comp in all_available_components:
                # Ensure "line_text" is not added even if somehow missed above
                if available_comp["type"] == "line_text":
                    continue
                is_present = any(fc["type"] == available_comp["type"] and fc["id"] == available_comp["id"] for fc in final_component_list)
                if not is_present:
                    final_component_list.append(available_comp)
        else:
            # Default order without "line_text"
            final_component_list = all_available_components # Already excludes line_text from default_order_definitions

        for comp_info in final_component_list:
            # Defensive check to ensure "line_text" is not added to UI
            if comp_info["type"] == "line_text":
                continue
            item = QListWidgetItem(comp_info["display_name"])
            item.setData(Qt.ItemDataRole.UserRole, {"type": comp_info["type"], "id": comp_info["id"]})
            self.prompt_order_list_widget.addItem(item)
        
        self.prompt_component_order = self.get_current_prompt_order_from_ui() 
    def get_current_prompt_order_from_ui(self):
        if not hasattr(self, 'prompt_order_list_widget'):
            return [] # Should match default if UI not ready

        order = []
        for i in range(self.prompt_order_list_widget.count()):
            item = self.prompt_order_list_widget.item(i)
            data = item.data(Qt.ItemDataRole.UserRole) # {"type": ..., "id": ...}
            if data: # Should always have data if populated correctly
                order.append(data)
        return order
    
    def move_prompt_component_up(self):
        if not hasattr(self, 'prompt_order_list_widget'): return
        current_item = self.prompt_order_list_widget.currentItem()
        if current_item:
            row = self.prompt_order_list_widget.row(current_item)
            if row > 0:
                # Take item and insert it one position up
                item_to_move = self.prompt_order_list_widget.takeItem(row)
                self.prompt_order_list_widget.insertItem(row - 1, item_to_move)
                self.prompt_order_list_widget.setCurrentItem(item_to_move) # Re-select the moved item
        self._update_prompt_order_button_states() 

    def move_prompt_component_down(self):
        if not hasattr(self, 'prompt_order_list_widget'): return
        current_item = self.prompt_order_list_widget.currentItem()
        if current_item:
            row = self.prompt_order_list_widget.row(current_item)
            if row < self.prompt_order_list_widget.count() - 1:
                # Take item and insert it one position down
                item_to_move = self.prompt_order_list_widget.takeItem(row)
                self.prompt_order_list_widget.insertItem(row + 1, item_to_move)
                self.prompt_order_list_widget.setCurrentItem(item_to_move) # Re-select the moved item
        self._update_prompt_order_button_states()

    def regenerate_selected_combinations(self):
        selected_list_widget_items = self.combination_list_widget.selectedItems()
        if not selected_list_widget_items:
            QMessageBox.information(self, "No Selection", "Please select combinations from the list to regenerate.")
            return

        if self.generation_thread and self.generation_thread.isRunning():
            QMessageBox.warning(self, "Processing Active", "Cannot regenerate items while bulk generation is in progress.")
            return

        selected_line_texts = [item.data(Qt.ItemDataRole.UserRole) for item in selected_list_widget_items if item.data(Qt.ItemDataRole.UserRole)]
        if not selected_line_texts:
             QMessageBox.warning(self, "Error", "Could not retrieve original text for selected items.")
             return

        reply_keep_files = QMessageBox.question(self, "Keep Previous Images?",
                                                "For the selected combinations, do you want to keep any previously generated images?\n\n"
                                                "'Yes' - Keep old files; new files will be added (potentially with different names if settings changed).\n"
                                                "'No' - Attempt to remove previously generated images for these combinations before regenerating.",
                                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                                QMessageBox.StandardButton.Yes)

        if reply_keep_files == QMessageBox.StandardButton.Cancel:
            return

        files_to_delete_display = []
        files_actually_deleted_count = 0

        if reply_keep_files == QMessageBox.StandardButton.No:
            # Prepare to list files for deletion
            for line_text in selected_line_texts:
                progress_entry = self.generation_progress_state.get(line_text, {})
                existing_files = progress_entry.get("generated_files", [])
                
                if existing_files:
                    files_to_delete_display.extend(existing_files)
                else: # If no record, try to infer from output structure (more complex)
                    # This part is tricky if save_to_single_folder_radio was true.
                    # For now, only delete files explicitly tracked in generation_progress_state.
                    # A more robust solution would involve scanning the output folder based on naming patterns.
                    pass 
            
            if files_to_delete_display:
                confirm_delete_msg = "The following files associated with the selected combinations will be deleted:\n\n"
                confirm_delete_msg += "\n".join(files_to_delete_display[:20]) # Show up to 20 files
                if len(files_to_delete_display) > 20:
                    confirm_delete_msg += f"\n...and {len(files_to_delete_display) - 20} more files."
                confirm_delete_msg += "\n\nAre you sure you want to permanently delete these files?"

                reply_confirm_delete = QMessageBox.warning(self, "Confirm Deletion", confirm_delete_msg,
                                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                                           QMessageBox.StandardButton.Cancel)
                if reply_confirm_delete == QMessageBox.StandardButton.Yes:
                    for f_path in files_to_delete_display:
                        try:
                            if os.path.exists(f_path):
                                os.remove(f_path)
                                files_actually_deleted_count += 1
                                print(f"Deleted for regeneration: {f_path}")
                        except Exception as e_del:
                            print(f"Error deleting file {f_path} for regeneration: {e_del}")
                            QMessageBox.warning(self, "Deletion Error", f"Could not delete file: {f_path}\n{e_del}")
                else: # User cancelled deletion
                    return 
            else:
                QMessageBox.information(self, "No Files to Delete", "No previously generated files were found in the progress records for the selected items to delete.")


        # Reset progress for selected items
        for line_text in selected_line_texts:
            self.generation_progress_state[line_text] = {
                "status": "pending", 
                "iterations_completed": 0, 
                "generated_files": [] # Clear list of generated files for this item
            }
        
        self.update_combination_list_statuses()
        QMessageBox.information(self, "Ready to Regenerate",
                                f"Selected combinations have been reset for regeneration. "
                                f"{files_actually_deleted_count} previous image file(s) were deleted (if chosen).\n\n"
                                "Click 'START BULK GENERATION' to proceed with generating these items.")
        
    def _update_prompt_order_button_states(self):
        if not hasattr(self, 'prompt_order_list_widget'):
            return

        selected_item = self.prompt_order_list_widget.currentItem()
        count = self.prompt_order_list_widget.count()
        
        can_move_up = False
        can_move_down = False

        if selected_item and count > 0:
            current_row = self.prompt_order_list_widget.row(selected_item)
            if current_row > 0:
                can_move_up = True
            if current_row < count - 1:
                can_move_down = True
        
        if hasattr(self, 'move_prompt_component_up_button'):
            self.move_prompt_component_up_button.setEnabled(can_move_up)
        if hasattr(self, 'move_prompt_component_down_button'):
            self.move_prompt_component_down_button.setEnabled(can_move_down)