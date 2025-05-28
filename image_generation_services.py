import requests
import json
import base64
from io import BytesIO 
import traceback 
import os # For GOOGLE_CLOUD_PROJECT

# Attempt to import Vertex AI specific libraries
try:
    import vertexai
    from vertexai.preview.vision_models import ImageGenerationModel, Image 
    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False
    print("WARNING: google-cloud-aiplatform library not found. Google Imagen (Vertex AI) generation will not be available.")

class ImageGenerationService:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.session = requests.Session()
        self.vertex_ai_initialized = False
        self.gcp_project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or \
                              config_manager.api_keys.get("GOOGLE_CLOUD_PROJECT_ID") # Try env var then json

        if VERTEX_AI_AVAILABLE and self.gcp_project_id:
            try:
                # Location can be crucial. "us-central1" is common for many models.
                # Some Imagen models might have specific regional availability.
                vertexai.init(project=self.gcp_project_id, location="us-central1")
                self.vertex_ai_initialized = True
                print(f"Vertex AI initialized successfully for project '{self.gcp_project_id}' in location 'us-central1'.")
            except Exception as e:
                print(f"ERROR: Failed to initialize Vertex AI: {e}. "
                      "Ensure GOOGLE_CLOUD_PROJECT environment variable or GOOGLE_CLOUD_PROJECT_ID in user_api_keys.json is set "
                      "and Application Default Credentials (ADC) are configured (run 'gcloud auth application-default login').")
                self.vertex_ai_initialized = False
        elif VERTEX_AI_AVAILABLE and not self.gcp_project_id:
            print("WARNING: GOOGLE_CLOUD_PROJECT environment variable or GOOGLE_CLOUD_PROJECT_ID in user_api_keys.json is not set. "
                  "Vertex AI Imagen generation will not be available.")


    def generate_image_deepai(self, prompt: str, width: int = 512, height: int = 512, grid_size: str = "1x1", version: str = "hd"):
        # ... (DeepAI implementation remains the same as previous correct version)
        api_key = self.config_manager.get_api_key("DEEPAI_API_KEY")
        if not api_key:
            return {"success": False, "error": "DEEPAI_API_KEY not found."}

        endpoint = "https://api.deepai.org/api/text2img"
        headers = {"api-key": api_key}
        payload = {
            "text": prompt,
            "grid_size": grid_size, 
            "width": str(width),   
            "height": str(height), 
            "image_generator_version": version,
        }
        
        print(f"Sending to DeepAI: {endpoint} with payload (form-data): {payload}")
        try:
            response = self.session.post(endpoint, data=payload, headers=headers, timeout=180) 
            response.raise_for_status() 
            data = response.json() 
            output_url = data.get("output_url")
            if not output_url:
                error_detail = data.get("err") or data.get("status") or str(data)
                return {"success": False, "error": f"DeepAI API did not return an output_url. Response: {error_detail}"}
            image_response = self.session.get(output_url, timeout=60)
            image_response.raise_for_status()
            image_bytes = image_response.content
            content_type = image_response.headers.get('content-type', 'image/jpeg').lower()
            image_format = "JPEG" 
            if "png" in content_type: image_format = "PNG"
            elif "webp" in content_type: image_format = "WEBP" 
            return {"success": True, "image_bytes": image_bytes, "format": image_format}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "DeepAI API request timed out."}
        except requests.exceptions.HTTPError as e:
            err_msg = f"DeepAI HTTP Error: {e.response.status_code} ({e.response.reason})"
            try: 
                error_detail_json = e.response.json()
                detail = error_detail_json.get('err', error_detail_json.get('status', str(error_detail_json)))
                err_msg += f" - Detail: {detail}"
            except json.JSONDecodeError: 
                err_msg += f" - Detail (non-JSON): {e.response.text[:500]}" 
            return {"success": False, "error": err_msg}
        except Exception as e:
            return {"success": False, "error": f"DeepAI unexpected error: {str(e)}\n{traceback.format_exc()}"}


    def generate_image_google_imagen_vertexai(self, model_id: str, prompt: str, 
                                            negative_prompt: str | None = None, # <--- ADDED negative_prompt parameter
                                            aspect_ratio: str = "1:1", 
                                            num_images: int = 1):
        if not VERTEX_AI_AVAILABLE:
            return {"success": False, "error": "Vertex AI SDK (google-cloud-aiplatform) not installed."}
        if not self.vertex_ai_initialized:
            return {"success": False, "error": "Vertex AI not initialized. Check GCP Project ID and ADC setup."}

        print(f"--- Google Imagen (Vertex AI) Request ---")
        print(f"Using Vertex AI SDK with model: {model_id}")
        print(f"Project ID: {self.gcp_project_id}, Location: us-central1 (assumed)")
        print(f"Prompt: {prompt}")
        if negative_prompt: # <--- NEW DEBUG PRINT
            print(f"Negative Prompt: {negative_prompt}")
        print(f"Aspect Ratio: {aspect_ratio}, Num Images: {num_images}")
        print(f"-----------------------------------------")

        try:
            image_model = ImageGenerationModel.from_pretrained(model_id)
            
            # Prepare parameters for generate_images method
            generation_params = {
                "prompt": prompt,
                "number_of_images": num_images,
                "aspect_ratio": aspect_ratio, 
            }
            if negative_prompt: # <--- ADD negative_prompt to params if it exists
                generation_params["negative_prompt"] = negative_prompt
            
            images_response = image_model.generate_images(**generation_params) # <--- Pass all params

            if not images_response or not images_response.images:
                return {"success": False, "error": "Vertex AI Imagen SDK call did not return images."}

            generated_image_sdk_object = images_response.images[0]
            
            image_bytes = generated_image_sdk_object._image_bytes

            if not image_bytes:
                return {"success": False, "error": "Vertex AI Imagen SDK image object has no bytes."}
            image_format = "PNG" 
            
            return {"success": True, "image_bytes": image_bytes, "format": image_format}

        except Exception as e:
            err_msg = f"Google Imagen (Vertex AI) SDK Error: {str(e)}"
            print(f"Full Vertex AI Exception: {traceback.format_exc()}")
            if "ApplicationDefaultCredentials" in str(e):
                err_msg += "\n\nHint: Ensure Application Default Credentials (ADC) are configured by running 'gcloud auth application-default login'."
            elif "permission" in str(e).lower() or "denied" in str(e).lower():
                 err_msg += "\n\nHint: Check IAM permissions for the Vertex AI API / Imagen models in your GCP project."
            elif "Could not find model" in str(e) or "404" in str(e) or "NOT_FOUND" in str(e): 
                err_msg += f"\n\nHint: The model '{model_id}' might not be available in 'us-central1' or for your project. Verify model name and region."
            return {"success": False, "error": err_msg}
