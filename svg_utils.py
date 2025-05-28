from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtCore import QSize, Qt, QRectF, QByteArray, QBuffer, QIODevice # Added QByteArray, QBuffer, QIODevice

class SvgUtils:
    @staticmethod
    def convert_svg_to_png_bytes(svg_data_bytes, width, height, background_color_str="transparent"):
        try:
            renderer = QSvgRenderer()
            q_byte_array_svg = QByteArray(svg_data_bytes) # Wrap input bytes

            if not renderer.load(q_byte_array_svg):
                print("Failed to load SVG data into renderer.")
                try: # Attempt decode/re-encode as a fallback for potential encoding quirks
                    svg_data_str = svg_data_bytes.decode('utf-8')
                    q_byte_array_svg_decoded = QByteArray(svg_data_str.encode('utf-8'))
                    if not renderer.load(q_byte_array_svg_decoded):
                        print("Failed to load SVG data even after explicit decode/re-encode.")
                        return None
                except Exception as e_decode:
                    print(f"Error during decode/re-encode for SVG renderer: {e_decode}")
                    return None

            if not renderer.isValid():
                print("SVG data is not valid according to QSvgRenderer.")
                return None

            # Ensure width and height are integers for QImage constructor
            img_width = int(width)
            img_height = int(height)
            if img_width <= 0: img_width = renderer.defaultSize().width() if renderer.defaultSize().width() > 0 else 100
            if img_height <= 0: img_height = renderer.defaultSize().height() if renderer.defaultSize().height() > 0 else 100


            image = QImage(QSize(img_width, img_height), QImage.Format.Format_ARGB32)
            
            if background_color_str.lower() == "transparent":
                image.fill(Qt.GlobalColor.transparent)
            else:
                try:
                    q_color = QColor(background_color_str)
                    if not q_color.isValid():
                        print(f"Warning: Invalid background color '{background_color_str}'. Using transparent.")
                        image.fill(Qt.GlobalColor.transparent)
                    else:
                        image.fill(q_color)
                except Exception as e_color: 
                    print(f"Error processing background color '{background_color_str}': {e_color}. Using transparent.")
                    image.fill(Qt.GlobalColor.transparent)

            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            svg_size = renderer.defaultSize()
            target_rect = image.rect()

            if svg_size.isValid() and svg_size.width() > 0 and svg_size.height() > 0:
                scaled_size = svg_size.scaled(target_rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
                x = (target_rect.width() - scaled_size.width()) / 2.0
                y = (target_rect.height() - scaled_size.height()) / 2.0
                render_qrectf = QRectF(x, y, scaled_size.width(), scaled_size.height())
                renderer.render(painter, render_qrectf)
            else:
                print("Warning: SVG default size is invalid or zero. Rendering directly into target dimensions.")
                renderer.render(painter, QRectF(target_rect))

            painter.end()

            # ***** CORRECTED PNG BYTE CONVERSION *****
            # Use QBuffer (which is a QIODevice) to save the image to memory
            byte_array_png_q = QByteArray() # QByteArray to hold the PNG data
            buffer = QBuffer(byte_array_png_q)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly) # Open buffer in write mode
            
            # Save the image to the buffer in PNG format
            success = image.save(buffer, "PNG") 
            buffer.close()

            if not success:
                print("QImage.save() to buffer failed.")
                return None
            
            # Convert QByteArray to Python bytes
            png_bytes = bytes(byte_array_png_q) 
            # ****************************************
            
            return png_bytes

        except Exception as e:
            print(f"Error converting SVG to PNG: {e}")
            import traceback
            traceback.print_exc()
            return None

if __name__ == '__main__':
    # This test needs a QApplication instance to use QImage, QPainter etc.
    from PyQt6.QtWidgets import QApplication
    import sys
    if QApplication.instance() is None:
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()

    print("SvgUtils tests running within a QApplication context.")
    
    dummy_svg_bytes = b'<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40" stroke="black" stroke-width="3" fill="red" /></svg>'
    
    print("\nTesting with transparent background (256x256):")
    png_bytes_transparent = SvgUtils.convert_svg_to_png_bytes(dummy_svg_bytes, 256, 256, "transparent")
    if png_bytes_transparent:
        with open("test_transparent.png", "wb") as f:
            f.write(png_bytes_transparent)
        print("Saved test_transparent.png")
    else:
        print("Failed to convert with transparent background.")

    print("\nTesting with white background (128x128):")
    png_bytes_white = SvgUtils.convert_svg_to_png_bytes(dummy_svg_bytes, 128, 128, "white")
    if png_bytes_white:
        with open("test_white.png", "wb") as f:
            f.write(png_bytes_white)
        print("Saved test_white.png")
    else:
        print("Failed to convert with white background.")
    
    print("\nTesting with invalid SVG:")
    invalid_svg_bytes = b'<svg><circle cx="50" r="40" </svg>' # Malformed
    png_bytes_invalid = SvgUtils.convert_svg_to_png_bytes(invalid_svg_bytes, 100, 100)
    if png_bytes_invalid is None:
        print("Correctly failed to convert invalid SVG.")
    else:
        print("Incorrectly converted invalid SVG (or saved partial).")
        with open("test_invalid_attempt.png", "wb") as f:
            f.write(png_bytes_invalid)
        print("Saved test_invalid_attempt.png (output from invalid SVG)")
    
    # sys.exit(app.exec()) # Only if this script was meant to be a standalone app