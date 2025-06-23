import sys
import os
import json
import html
import subprocess
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTextBrowser, QLabel, QLineEdit,
    QScrollArea, QGridLayout, QFrame, QMenu, QSplitter
)
from PySide6.QtGui import QPixmap, QImageReader, QPainter, QColor, QImage
from PySide6.QtCore import Qt, QSize, QThread, Signal
from PIL import Image
from image_parser import comfyui_get_data

def open_file_location(filepath):
    """Opens the file explorer to the location of the given file."""
    filepath = os.path.normpath(filepath)
    if sys.platform == "win32":
        subprocess.run(['explorer', '/select,', filepath])
    elif sys.platform == "darwin": # macOS
        subprocess.run(['open', '-R', filepath])
    else: # Linux and other OSes
        dirpath = os.path.dirname(filepath)
        try:
            subprocess.run(['xdg-open', dirpath])
        except FileNotFoundError:
            print(f"Could not open file location. Please open manually: {dirpath}")

def open_image_in_system_viewer(filepath):
    """Opens an image file in the system's default viewer."""
    filepath = os.path.normpath(filepath)
    try:
        if sys.platform == "win32":
            os.startfile(filepath)
        elif sys.platform == "darwin": # macOS
            subprocess.run(['open', filepath])
        else: # Linux and other OSes
            subprocess.run(['xdg-open', filepath])
    except Exception as e:
        print(f"Could not open image in system viewer: {e}")

class ClickableLabel(QLabel):
    """A QLabel that emits clicked and double-clicked signals with its path."""
    clicked = Signal(str)
    doubleClicked = Signal(str)

    def __init__(self, path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path = path

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.path)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.path)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_action = menu.addAction("Open File Location")
        action = menu.exec(self.mapToGlobal(event.pos()))
        if action == open_action:
            open_file_location(self.path)

class ImageLoader(QThread):
    image_loaded = Signal(dict)
    finished = Signal()

    def __init__(self, directory, thumbnail_size):
        super().__init__()
        self.directory = directory
        self.running = True
        self.thumbnail_size = thumbnail_size

    def run(self):
        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp'}
        
        for root, _, files in os.walk(self.directory):
            if not self.running:
                break
            for filename in files:
                if not self.running:
                    break
                
                ext = os.path.splitext(filename)[1].lower()
                if ext in valid_extensions:
                    filepath = os.path.join(root, filename)
                    
                    source_image = QImage(filepath)
                    if source_image.isNull():
                        print(f"Could not load image {os.path.basename(filepath)}")
                        continue

                    scaled_image = source_image.scaled(self.thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    
                    try:
                        info_dict = {}
                        width, height = 0, 0
                        with Image.open(filepath) as pil_img:
                            info_dict = pil_img.info
                            width, height = pil_img.size

                        metadata = {}
                        if info_dict:
                            try:
                                metadata = comfyui_get_data(info_dict)
                            except Exception as e:
                                print(f"Could not parse metadata for {os.path.basename(filepath)}: {e}")

                        self.image_loaded.emit({
                            'path': filepath,
                            'metadata': metadata,
                            'resolution': f"{width}x{height}",
                            'thumbnail_image': scaled_image
                        })
                    except Exception as e:
                        print(f"Could not read image for metadata {os.path.basename(filepath)}: {e}")

        self.finished.emit()

    def stop(self):
        self.running = False

class ImageBrowser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Comfy Image Browser")
        self.setGeometry(100, 100, 1600, 900)
        self.selected_widget = None

        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        self.select_dir_button = QPushButton("Select Directory")
        self.select_dir_button.clicked.connect(self.select_directory)
        left_layout.addWidget(self.select_dir_button)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search all metadata...")
        self.search_bar.textChanged.connect(self.filter_images)
        left_layout.addWidget(self.search_bar)

        self.metadata_display = QTextBrowser()
        self.metadata_display.setOpenExternalLinks(True)
        left_layout.addWidget(QLabel("Metadata:"))
        left_layout.addWidget(self.metadata_display)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.scroll_area = QScrollArea()
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.image_grid_layout = QGridLayout(self.scroll_widget)
        self.image_grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.scroll_widget)
        right_layout.addWidget(self.scroll_area)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 1250])

        self.images_data = []
        self.image_widgets = []
        self.image_loader_thread = None
        self.thumbnail_size = QSize(256, 256)
        self._loading_columns = 0

    def closeEvent(self, event):
        if self.image_loader_thread and self.image_loader_thread.isRunning():
            self.image_loader_thread.stop()
            self.image_loader_thread.wait()
        super().closeEvent(event)

    def open_image_viewer(self, image_path):
        open_image_in_system_viewer(image_path)

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Image Directory")
        if directory:
            self.load_images(directory)

    def load_images(self, directory):
        for i in reversed(range(self.image_grid_layout.count())): 
            self.image_grid_layout.itemAt(i).widget().setParent(None)
        self.images_data.clear()
        self.image_widgets.clear()
        self.metadata_display.clear()
        self.selected_widget = None

        if self.image_loader_thread and self.image_loader_thread.isRunning():
            self.image_loader_thread.stop()
            self.image_loader_thread.wait()

        self._loading_columns = self.calculate_columns()
        self.image_loader_thread = ImageLoader(directory, self.thumbnail_size)
        self.image_loader_thread.image_loaded.connect(self.add_image_to_grid)
        self.image_loader_thread.finished.connect(self.on_loading_finished)
        self.image_loader_thread.start()

    def on_loading_finished(self):
        self._loading_columns = 0
        self.reorganize_grid()

    def add_image_to_grid(self, image_data):
        self.images_data.append(image_data)
        path = image_data['path']
        widget = ClickableLabel(path)
        widget.setFixedSize(self.thumbnail_size)
        widget.setFrameShape(QFrame.StyledPanel)
        widget.setAlignment(Qt.AlignCenter)

        widget.clicked.connect(self.display_image_metadata)
        widget.doubleClicked.connect(self.open_image_viewer)
        
        scaled_image = image_data.get('thumbnail_image')
        if scaled_image and not scaled_image.isNull():
            final_pixmap = QPixmap(self.thumbnail_size)
            final_pixmap.fill(QColor('black'))
            
            scaled_pixmap = QPixmap.fromImage(scaled_image)

            painter = QPainter(final_pixmap)
            x = (final_pixmap.width() - scaled_pixmap.width()) / 2
            y = (final_pixmap.height() - scaled_pixmap.height()) / 2
            painter.drawPixmap(int(x), int(y), scaled_pixmap)
            painter.end()
            widget.setPixmap(final_pixmap)
        else:
            widget.setText(os.path.basename(path))
        
        columns = self._loading_columns
        if columns == 0: columns = 1
        row = len(self.image_widgets) // columns
        col = len(self.image_widgets) % columns
        self.image_grid_layout.addWidget(widget, row, col)
        self.image_widgets.append(widget)
        widget.setProperty("image_path", path)

    def display_image_metadata(self, image_path):
        clicked_widget = None
        for widget in self.image_widgets:
            if widget.path == image_path:
                clicked_widget = widget
                break

        if clicked_widget:
            if self.selected_widget and self.selected_widget != clicked_widget:
                self.selected_widget.setStyleSheet("")
            
            hacker_green = "#39FF14"
            clicked_widget.setStyleSheet(f"border: 2px solid {hacker_green};")
            self.selected_widget = clicked_widget

        self.metadata_display.clear()
        image_info = next((item for item in self.images_data if item['path'] == image_path), None)
        
        if image_info:
            if image_info.get('resolution'):
                image_info['metadata']['Resolution'] = image_info['resolution']

            html_output = ""
            if image_info['metadata']:
                prompt_color = "#90EE90"
                neg_prompt_color = "#F08080"
                order_map = {
                    "Prompt": 0, "Negative Prompt": 1, "Model": 2, "LoRA": 3,
                    "Seed": 4, "Steps": 5, "CFG Scale": 6, "Sampler": 7,
                    "Scheduler": 8, "Denoise": 9, "Resolution": 10
                }
                
                sorted_keys = sorted(
                    image_info['metadata'].keys(), 
                    key=lambda k: (order_map.get(k, 99), k)
                )

                for key in sorted_keys:
                    value = image_info['metadata'][key]
                    color = "white"
                    if key == "Prompt":
                        color = prompt_color
                    elif key == "Negative Prompt":
                        color = neg_prompt_color
                    
                    escaped_value = html.escape(str(value)).replace('\n', '<br>')
                    html_output += f"<p style='margin-bottom: 10px; color:{color};'><b>{key}:</b><br>{escaped_value}</p>"

                self.metadata_display.setHtml(f"<html><body style='color:white; font-family: sans-serif; font-size: 14px;'>{html_output}</body></html>")
            else:
                self.metadata_display.setText("No ComfyUI metadata found.")

    def filter_images(self):
        search_text = self.search_bar.text().lower()
        
        for widget in self.image_widgets:
            image_path = widget.property("image_path")
            if not image_path:
                continue
                
            image_info = next((item for item in self.images_data if item['path'] == image_path), None)
            
            if image_info:
                metadata_str = json.dumps(image_info['metadata']).lower()
                
                if search_text in metadata_str or search_text in os.path.basename(image_path).lower():
                    widget.show()
                else:
                    widget.hide()

    def calculate_columns(self):
        return max(1, self.scroll_area.width() // (self.thumbnail_size.width() + 10))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reorganize_grid()

    def reorganize_grid(self):
        columns = self.calculate_columns()
        for i, widget in enumerate(self.image_widgets):
            row = i // columns
            col = i % columns
            self.image_grid_layout.addWidget(widget, row, col)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    app.setStyleSheet("""
        QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
            border: 1px solid #4f4f4f;
        }
        QMainWindow {
            border: none;
        }
        QPushButton {
            background-color: #4a4a4a;
            border: 1px solid #4f4f4f;
            padding: 5px;
            border-radius: 4px;
        }
        QPushButton:hover {
            background-color: #5a5a5a;
        }
        QPushButton:pressed {
            background-color: #6a6a6a;
        }
        QLineEdit, QTextBrowser, QScrollArea {
            background-color: #3c3c3c;
            border-radius: 4px;
            padding: 5px;
        }
        QMenu {
            background-color: #3c3c3c;
            border: 1px solid #4f4f4f;
        }
        QMenu::item:selected {
            background-color: #5a5a5a;
        }
        QLabel {
            border: none;
        }
        QScrollBar:vertical {
            border: none;
            background: #2b2b2b;
            width: 10px;
            margin: 0px 0px 0px 0px;
        }
        QScrollBar::handle:vertical {
            background: #8c8c8c;
            min-height: 20px;
            border-radius: 5px;
        }
        QScrollBar:horizontal {
            border: none;
            background: #2b2b2b;
            height: 10px;
            margin: 0px 0px 0px 0px;
        }
        QScrollBar::handle:horizontal {
            background: #8c8c8c;
            min-width: 20px;
            border-radius: 5px;
        }
    """)

    window = ImageBrowser()
    window.show()
    sys.exit(app.exec())