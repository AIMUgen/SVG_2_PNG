# LLM SVG & Image Assistant

## 1. Goal of the Application

The **LLM SVG & Image Assistant** is a desktop application designed to streamline and enhance the process of creating and converting graphical assets. It leverages Large Language Models (LLMs) for generating both SVG icons and raster images from text prompts. Additionally, it provides utilities for converting between various image formats, with a special focus on generating ICO files from SVG or raster sources, and a powerful bulk image generation mode for automating the creation of multiple themed images.

This tool is aimed at developers, designers, and content creators who need to quickly produce or convert icons and simple images for their projects.

## 2. Core Functionalities

### 2.1. SVG Icon Generation (via LLM)
*   **Provider & Model Selection:** Users can select from a configurable list of LLM providers and models (defined in `providers.json`) suitable for generating SVG code.
*   **Prompt-Based Generation:** Input a text prompt describing the desired SVG icon.
*   **Preview & Save:** View the generated SVG in real-time and save it as a `.svg` file.
*   **Prompt History:** Access recently used prompts for quick re-generation.

### 2.2. Raster Image Generation (via LLM)
*   **Dedicated Image Models:** Select from pre-configured image generation models:
    *   DeepAI Text-to-Image API
    *   Google Imagen 3 (via Vertex AI SDK - various quality/speed options)
*   **Prompt-Based Generation:** Input a text prompt to generate raster images.
*   **Aspect Ratio Control:** For Imagen models, select common aspect ratios (1:1, 16:9, etc.).
*   **Negative Prompts:** Optionally provide negative prompts to guide the image generation away from undesired elements.
*   **Preview & Save:** Display the generated image (PNG, JPEG) and save it to a chosen location and format (PNG or JPEG).
*   **Auto-Save to Temp Folder:** Generated images are automatically saved to a user-configurable temporary folder during the session.
*   **Unsaved Changes Warning:** The application warns about unsaved generated images before closing or performing actions that would overwrite the preview.

### 2.3. Image Conversion
*   **SVG to PNG:**
    *   Convert the currently loaded/generated SVG to a PNG file.
    *   Specify output dimensions (width, height).
    *   Choose a background color (transparent, white, black, or custom).
*   **SVG or PNG to ICO:**
    *   Convert the currently loaded SVG or a loaded PNG image to an ICO file.
    *   Select multiple desired sizes to be included in the `.ico` file (e.g., 16x16, 32x32, 256x256).
    *   Specify a background color for the ICO layers if the source is an SVG or if a fill is desired for transparent PNGs.
*   **Loaded Raster to PNG:**
    *   Re-save an opened raster image (PNG, JPG, WEBP, etc.) as a PNG, allowing for resizing and background color changes.

### 2.4. File Operations & Session Management
*   **Open SVG/Image Files:** Load existing SVG or raster image files (PNG, JPG, WEBP, BMP, GIF) into the preview area.
*   **Session Gallery (for SVGs and Raster Images):**
    *   Thumbnails of SVGs and raster images generated or opened during the current session are displayed.
    *   Items are prefixed with their type (e.g., `[SVG]`, `[PNG]`).
    *   Double-click an item to load it back into the main preview.
*   **Settings Persistence (`app_settings.json`):**
    *   Remembers last selected LLM providers/models (for SVG and Image generation).
    *   Remembers last used aspect ratio.
    *   Remembers the path to the temporary auto-save folder.
    *   Remembers last used directories for various file dialogs (open SVG, open Image, save SVG, save generated image, save conversions).
*   **Temporary Folder Management:**
    *   Button to set a custom temporary folder for auto-saved generated images.
    *   Button to open the current temporary folder in the system's file explorer.
    *   Prompts on exit to handle unsaved auto-saved files (save manually or delete temps).

### 2.5. Bulk Image Creation Mode (Advanced Feature)
*   A dedicated dialog for generating large batches of images based on a list of combinations/entities from a text file.
*   Sophisticated layered prompting system.
*   Flexible filename and output folder structuring.
*   Retry, pause, resume, and progress tracking for long generation tasks.
*   Persistence of bulk configurations per input file.
*   (Details in Section 4)

## 3. Setup and Configuration

### 3.1. Prerequisites
*   Python 3.x
*   Required Python packages (install via pip):
    *   `PyQt6`
    *   `requests`
    *   `Pillow`
    *   `google-cloud-aiplatform` (for Google Imagen via Vertex AI)
*   **Google Cloud SDK (`gcloud` CLI):** Required for Google Imagen (Vertex AI) authentication. Must be installed and configured with Application Default Credentials (ADC).
    1.  Install `gcloud` from [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install).
    2.  Authenticate ADC by running: `gcloud auth application-default login`
        *   Log in with a Google account that has "Vertex AI User" (or broader) permissions on your GCP project.

### 3.2. Configuration Files
Place these JSON files in the same directory as `main.py`:

*   **`providers.json`:**
    *   Defines LLM providers and models for **SVG generation**.
    *   Structure:
      ```json
      {
        "providers": [
          {
            "id": "unique_provider_id",
            "name": "Display Name (e.g., OpenAI)",
            "api_key_env_var": "ENV_VAR_NAME_FOR_KEY_IN_USER_API_KEYS_JSON",
            "base_url": "https://api.provider.com/v1",
            "models": [
              { "id": "model-id", "name": "Model Display Name", "type": "chat_completion_or_other_svg_type", ... },
              ...
            ]
          },
          ...
        ]
      }
      ```
*   **`user_api_keys.json`:**
    *   Stores your API keys and other sensitive configuration. The application will create a template if this file is missing.
    *   Structure:
      ```json
      {
        "OPENAI_API_KEY": "your_openai_key",
        "ANTHROPIC_API_KEY": "your_anthropic_key",
        "GOOGLE_API_KEY": "your_gemini_api_key", // Used by some Google services, Imagen now uses ADC + Project ID
        "GOOGLE_CLOUD_PROJECT_ID": "your-gcp-project-id-string", // REQUIRED for Imagen via Vertex AI
        "DEEPAI_API_KEY": "your_deepai_key",
        "MISTRAL_API_KEY": "your_mistral_key",
        // ... other keys as needed by providers.json ...
      }
      ```
*   **`app_settings.json`:**
    *   Automatically created/updated by the application to store user preferences (last selections, paths, etc.). Do not edit manually unless you know what you're doing.

### 3.3. Running the Application
Execute `python main.py` from the application's root directory.

## 4. Bulk Image Creation Mode - In-Depth Guide

The Bulk Image Creation Mode allows you to automate the generation of multiple images, each potentially with a unique prompt constructed from several layers of text, based on an input list of "combinations" or "entities".

### 4.1. Accessing Bulk Mode
Go to the top menu: **Tools -> Bulk Image Creation...**
This will open a new dialog dedicated to bulk operations.

### 4.2. Proposed Workflow & Step-by-Step Instructions

**Step 1: Load Your Combinations File**
1.  Click the **"Load Combinations File (.txt)"** button.
2.  Select a plain text file (`.txt`) where each line represents a unique item/character/entity for which you want to generate an image(s).
    *   Example line: `Cinderspawn_Cleric_Male`
    *   Example line: `Forest_Scene_With_River`
3.  The loaded combinations will appear in the list on the left. The path to the loaded file will also be displayed.

**Step 2: (Optional) Load Existing Bulk Settings**
*   If you have previously configured and saved settings for this specific `.txt` file, they will be automatically loaded (if found). The settings file is named `your_combinations_file.txt.bulk_settings.json`.
*   You can also manually click **"Load Bulk Settings"** to attempt to load them.
*   **File Change Detection:** If the content of the loaded `.txt` file differs from when the settings were last saved (e.g., new lines added, old lines removed), the application will notify you.
    *   New lines will be marked `[NEW]` in the combinations list.
    *   Missing lines will be reported. Progress/settings for missing lines might be invalid.
    *   You'll need to manually integrate `[NEW]` lines into your Sections or ensure Commonality Layers cover them.

**Step 3: (Optional) Filter and Manage the Combination List**
*   Use the **Filter input** and **"Apply Filter" / "Clear Filter"** buttons to narrow down the displayed combinations. This helps in selecting specific groups for defining Sections.
*   Check **"Case Sensitive"** for the filter if needed.

**Step 4: Define "Section-Specific Prompts" (for contiguous blocks)**
*   **Purpose:** Apply a detailed description common to a block of related items in your list. For this to be most effective, your input `.txt` file should group related items together (e.g., all "Dwarf" characters, then all "Elf" characters).
1.  **Select Lines:** In the "Combinations" list on the left, select a contiguous block of lines that belong to a conceptual section (e.g., all lines starting with "Cinderspawn").
2.  Click **"Define Section from Selection"**.
3.  A new entry will appear in the "Section-Specific Prompts" list (e.g., "Section 1 (Lines 1-12...)").
4.  **Select this new section entry** in the list.
5.  The `QTextEdit` box below this list will become active. **Type or paste the detailed prompt specific to this section** (e.g., "Cinderspawn are a race of fire elementals, with skin like cooling magma, eyes like embers, often wreathed in faint smoke. Their armor and clothing are typically dark, heat-resistant materials...").
6.  Repeat for other logical sections in your combination list.
*   **Editing/Removing Sections:**
    *   Select a section from the list.
    *   Click **"Edit Section Prompt"** (which just ensures the prompt box is active for the selected section).
    *   Click **"Remove Section"** to delete the selected section definition.
*   **Note:** Sections are defined by the *exact text* of the lines you selected. If you reorder your `.txt` file, these sections will still apply to the same lines as long as their text hasn't changed.

**Step 5: Define "Commonality Layers" (for overlapping characteristics)**
*   **Purpose:** Apply specific prompt snippets or filename suffixes to any line that matches a certain text filter, regardless of its position or section. Layers can overlap.
1.  Click **"Add New Layer"**. A dialog will pop up.
2.  **Configure the Layer:**
    *   **Layer Name:** A descriptive name (e.g., "Male Characters", "Cleric Class", "Wearing Helmet").
    *   **Filter Text:** The text to search for within each combination line (e.g., "Male", "Cleric", "Helmet").
    *   **Case Sensitive Filter:** Check if the filter text should be case-sensitive.
    *   **Filename Suffix (Optional):** A suffix to add to filenames for images generated from matching lines (e.g., `_male`, `_cleric`).
    *   **Prompt Snippet for this Layer:** The specific text to add to the prompt for matching lines (e.g., for "Male" filter: "masculine build, strong jawline"; for "Cleric" filter: "adorned with holy symbols, carrying a mace or staff").
3.  Click "OK" in the dialog. The layer will appear in the "Commonality Layers" list.
4.  Repeat for all common characteristics you want to add details for.
*   **Managing Layers:**
    *   Select a layer from the list to see its details in the read-only summary box below.
    *   Click **"Edit Layer"** to modify the selected layer's settings via the dialog.
    *   Click **"Remove Layer"** to delete the selected layer.

**Step 6: Set the "Global Prompt"**
*   In the "Global Prompt" `QTextEdit` box, enter text that should be appended to *every* generated image's prompt.
*   This is ideal for defining overall style, art medium, camera angle, lighting, etc.
    *   Example: "pixel art style, detailed sprite, fantasy RPG character, white background, vibrant colors, --ar 1:1" (though aspect ratio is also set separately for Imagen).

**Step 7: Configure Generation and Output Settings**
1.  **Image Model:** Select the desired image generation model (DeepAI or one of the Google Imagen options).
2.  **Aspect Ratio:** If an Imagen model is selected, choose the desired aspect ratio. (This is ignored for DeepAI, which uses default or might have different width/height params not exposed in this UI).
3.  **Images per Combination:** Set how many unique images you want for each line in your combinations list (e.g., if 3, it will try to generate 3 distinct images for "Cinderspawn_Cleric_Male").
4.  **Global Filename Prefix (Optional):** Text to add at the beginning of every filename after the iteration number (e.g., `MyGame_`).
5.  **Output Folder:** Click "Browse..." to select the main folder where generated images will be saved.
6.  **Folder Structure for Output:**
    *   **Save all to selected Output Folder:** All images will be saved directly into the folder chosen above.
    *   **Save to subfolders... (experimental):** The application will try to create/use subfolders within the main Output Folder. The subfolder name will be derived from the combination line, *after* removing any keywords specified in the "Subfolder Excl. Keywords" field.
        *   **Subfolder Excl. Keywords:** Enter comma-separated words to ignore when creating subfolder names from the combination line (e.g., if line is `Cinderspawn_Cleric_Male` and exclusions are `male, female`, the subfolder might be `Cinderspawn_Cleric`).

**Step 8: (Highly Recommended) Save Bulk Settings**
*   Click **"Save Bulk Settings"**. This saves your entire configuration (loaded file path, sections, layers, prompts, output settings, and current generation progress) to a `.json` file named after your loaded `.txt` file (e.g., if you loaded `characters.txt`, settings are saved to `characters.txt.bulk_settings.json`).
*   Next time you load `characters.txt`, these settings (and progress) will be automatically reloaded.

**Step 9: Start Bulk Generation**
1.  Click **"START BULK GENERATION"**.
2.  **Resume/Restart:** If there's saved progress for the loaded file, you'll be asked if you want to resume the previous run or restart from the beginning.
3.  The process will begin. Observe the **Overall Progress Bar** and the **Status Label** for updates.
4.  Generated images will be saved according to your output settings.
5.  The list of combinations will update with status markers: `[Processing X/Y]`, `[DONE]`, `[ERROR]`.

**Step 10: Managing the Generation Process**
*   **Pause/Resume:**
    *   Click **"Pause"** to temporarily halt generation after the current image is finished. The button will change to "Resume".
    *   Click **"Resume"** to continue.
*   **Pause on Error:** If an API call for an image fails 3 times in a row, the process will automatically pause. The status will indicate the error.
    *   You can then investigate (e.g., check API key, network, prompt).
    *   Click **"Resume (after error)"** to retry that specific failed item (it will attempt its 3 retries again).
    *   Or click **"STOP"** to abandon the entire bulk run.
*   **STOP:** Click **"STOP"** to abort the entire bulk generation process. Any partially completed work for the current line might not be saved. Progress up to the stop point *is* saved when you click "Save Bulk Settings" or when the dialog is closed.

**Step 11: After Completion / Stopping**
*   A message will indicate completion or if it was stopped.
*   You can review the generated files in your output folder(s).
*   Save your bulk settings again if you made any changes or want to ensure the very latest progress is stored.
*   Click **"Close Dialog"** to return to the main application window.

### 4.3. How Prompts are Built (Example)

*   **Combination Line:** `Elf_Ranger_Female`
*   **Section ("Elves"):** `Elves are tall, slender, with pointed ears, often associated with forests and archery. Their attire is typically practical yet elegant, made of natural materials.`
*   **Commonality Layer 1 (Filter: "Ranger"):** `Skilled archer, carrying a longbow and a quiver of arrows, wearing leather armor and a cloak for camouflage.`
*   **Commonality Layer 2 (Filter: "Female"):** `Feminine facial features, agile posture.` (Suffix: `_fem`)
*   **Global Prompt:** `detailed pixel art character, 64x64 sprite, side-view, vibrant colors, white background`

**Resulting Final Prompt (simplified concatenation):**
`Elf_Ranger_Female, Elves are tall, slender..., Skilled archer..., Feminine facial features..., detailed pixel art character, 64x64 sprite...`

**Resulting Filename (example, iter 1, no global prefix):**
`1_Elf_Ranger_Female_fem.png` (if saved as PNG)

This detailed workflow should allow for highly customized and automated image generation. Remember to save your bulk settings frequently if you're doing complex configurations!

---

This `README.md` provides a good overview and detailed instructions for the bulk mode. You can copy and paste this into a `README.md` file in your project root.
