from PIL import Image, ImageOps, UnidentifiedImageError
from io import BytesIO
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor # For QImage to PIL Image if needed
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt

# Assuming SvgUtils is in the same directory or accessible via PYTHONPATH
from svg_utils import SvgUtils 

class ImageConverter:

    @staticmethod
    def qimage_to_pil_image(qimage: QImage) -> Image.Image:
        """Converts a QImage to a PIL Image."""
        qimage = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        qimage.save(buffer, "PNG") 
        buffer.seek(0)
        pil_image = Image.open(BytesIO(buffer.readAll().data()))
        return pil_image.convert("RGBA")

    @staticmethod
    def apply_background_to_pil(pil_image: Image.Image, background_color_str: str) -> Image.Image:
        """Applies a background color to a PIL image if it's not transparent."""
        if background_color_str.lower() == "transparent" or pil_image.mode != 'RGBA':
            return pil_image

        try:
            bg_qcolor = QColor(background_color_str)
            if not bg_qcolor.isValid() or bg_qcolor.alpha() == 0: # Also skip if chosen BG is transparent
                return pil_image
            
            bg_pil = Image.new("RGBA", pil_image.size, 
                               (bg_qcolor.red(), bg_qcolor.green(), bg_qcolor.blue(), 255)) # Solid background
            # Alpha composite the original image (with its alpha) onto the new solid background
            final_image = Image.alpha_composite(bg_pil, pil_image)
            return final_image
        except Exception as e_bg:
            print(f"ICO/PNG Conversion: Error applying background color {background_color_str}: {e_bg}")
            return pil_image # Return original on error


    @staticmethod
    def convert_raster_to_png_bytes(source_data_bytes: bytes, 
                                    source_format: str, # "png", "jpeg", "webp", etc.
                                    target_width: int, 
                                    target_height: int,
                                    background_color_str: str = "transparent") -> bytes | None:
        """
        Converts various raster image bytes to PNG bytes, with resizing and background option.
        """
        try:
            pil_image = Image.open(BytesIO(source_data_bytes))
            
            # Ensure image is RGBA for consistent background handling, especially if original is P, LA, etc.
            pil_image = pil_image.convert("RGBA")

            # Apply background if specified (and not transparent)
            pil_image = ImageConverter.apply_background_to_pil(pil_image, background_color_str)

            # Resize
            if pil_image.width != target_width or pil_image.height != target_height:
                pil_image = pil_image.resize((target_width, target_height), Image.Resampling.LANCZOS)

            output_bytes_io = BytesIO()
            pil_image.save(output_bytes_io, format="PNG")
            return output_bytes_io.getvalue()

        except UnidentifiedImageError:
            print(f"Raster to PNG: Pillow could not identify image format for source type '{source_format}'.")
            return None
        except Exception as e:
            print(f"Raster to PNG: Error processing image: {e}")
            import traceback
            traceback.print_exc()
            return None

    @staticmethod
    def convert_to_ico_bytes(source_data_bytes: bytes, 
                             source_type: str, # "svg", "png", "jpeg", "webp", etc.
                             sizes: list, 
                             background_color_str: str = "transparent") -> bytes | None:
        if not source_data_bytes or not sizes:
            print("ICO Conversion: No source data or no sizes specified.")
            return None

        pil_images_for_ico = []

        for size in sorted(list(set(sizes)), reverse=True): 
            if size <= 0 or size > 256: 
                print(f"ICO Conversion: Invalid size {size}x{size} skipped.")
                continue
            
            pil_image_resized = None

            if source_type.lower() == "svg":
                png_render_bytes = SvgUtils.convert_svg_to_png_bytes(
                    svg_data_bytes=source_data_bytes,
                    width=size,
                    height=size,
                    background_color_str=background_color_str 
                )
                if png_render_bytes:
                    try:
                        pil_image_resized = Image.open(BytesIO(png_render_bytes)).convert("RGBA")
                    except Exception as e: continue
                else: continue
            
            elif source_type.lower() in ["png", "jpeg", "jpg", "webp", "bmp", "gif"]: # Handle various raster types
                try:
                    base_pil_image = Image.open(BytesIO(source_data_bytes))
                    base_pil_image = base_pil_image.convert("RGBA") # Ensure RGBA for consistent handling

                    # Apply background before resizing if needed
                    base_pil_image = ImageConverter.apply_background_to_pil(base_pil_image, background_color_str)
                    
                    pil_image_resized = base_pil_image.resize((size, size), Image.Resampling.LANCZOS)
                except UnidentifiedImageError:
                    print(f"ICO Conversion: Pillow could not identify source image format '{source_type}' for size {size}x{size}.")
                    continue
                except Exception as e:
                    print(f"ICO Conversion: Failed to load/resize source raster type '{source_type}' for size {size}x{size}: {e}")
                    continue
            
            else:
                print(f"ICO Conversion: Unsupported source type '{source_type}'.")
                return None # Or skip this source type if part of a batch

            if pil_image_resized:
                pil_images_for_ico.append(pil_image_resized)
        
        if not pil_images_for_ico:
            print("ICO Conversion: No valid images generated for ICO.")
            return None

        ico_output_bytes_io = BytesIO()
        try:
            pil_images_for_ico[0].save(ico_output_bytes_io, format="ICO", sizes=[(img.width, img.height) for img in pil_images_for_ico])
        except Exception as e:
            print(f"ICO Conversion: Failed to save images to ICO format: {e}")
            import traceback
            traceback.print_exc()
            return None
            
        return ico_output_bytes_io.getvalue()


if __name__ == '__main__':
    # Basic test for ICO conversion (requires an SVG and a PNG file for testing)
    print("Testing ImageConverter ICO generation...")

    # 1. Test SVG to ICO
    dummy_svg_bytes = b'<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="45" fill="blue" /><text x="50" y="60" font-size="30" fill="white" text-anchor="middle">SVG</text></svg>'
    ico_sizes_to_test = [16, 32, 48, 256]
    
    # Need a QApplication for SvgUtils which uses Qt for rendering
    from PyQt6.QtWidgets import QApplication
    import sys
    if QApplication.instance() is None:
        app = QApplication(sys.argv)

    print(f"\nConverting SVG to ICO with sizes {ico_sizes_to_test} and transparent background...")
    ico_bytes_from_svg = ImageConverter.convert_to_ico_bytes(
        source_data_bytes=dummy_svg_bytes,
        source_type="svg",
        sizes=ico_sizes_to_test,
        background_color_str="transparent"
    )
    if ico_bytes_from_svg:
        with open("test_from_svg.ico", "wb") as f:
            f.write(ico_bytes_from_svg)
        print("Saved test_from_svg.ico")
    else:
        print("Failed to convert SVG to ICO.")

    print(f"\nConverting SVG to ICO with sizes {ico_sizes_to_test} and white background...")
    ico_bytes_from_svg_white = ImageConverter.convert_to_ico_bytes(
        source_data_bytes=dummy_svg_bytes,
        source_type="svg",
        sizes=ico_sizes_to_test,
        background_color_str="white" # Test with a background
    )
    if ico_bytes_from_svg_white:
        with open("test_from_svg_white_bg.ico", "wb") as f:
            f.write(ico_bytes_from_svg_white)
        print("Saved test_from_svg_white_bg.ico")
    else:
        print("Failed to convert SVG to ICO with white background.")


    # 2. Test PNG to ICO (Create a dummy PNG first for testing)
    try:
        # Create a simple PNG using Pillow for testing
        dummy_png_pil = Image.new("RGBA", (100,100), (255, 0, 0, 128)) # Semi-transparent red
        # Add some drawing if needed for visual check
        from PIL import ImageDraw
        draw = ImageDraw.Draw(dummy_png_pil)
        draw.text((10,10), "PNG", fill="blue")
        
        png_bytes_io = BytesIO()
        dummy_png_pil.save(png_bytes_io, format="PNG")
        dummy_png_bytes_for_test = png_bytes_io.getvalue()
        
        print(f"\nConverting dummy PNG to ICO with sizes {ico_sizes_to_test}...")
        ico_bytes_from_png = ImageConverter.convert_to_ico_bytes(
            source_data_bytes=dummy_png_bytes_for_test,
            source_type="png",
            sizes=ico_sizes_to_test,
            background_color_str="transparent" # PNG source transparency should be preserved
        )
        if ico_bytes_from_png:
            with open("test_from_png.ico", "wb") as f:
                f.write(ico_bytes_from_png)
            print("Saved test_from_png.ico")
        else:
            print("Failed to convert PNG to ICO.")

    except ImportError:
        print("Pillow library is not installed. Cannot run PNG to ICO test.")
    except Exception as e:
        print(f"Error during PNG to ICO test setup or execution: {e}")