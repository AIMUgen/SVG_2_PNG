import requests
import json

# Standard prompt prefix for SVG generation
# This system prompt is crucial for guiding the LLM to produce SVG code.
SVG_PROMPT_SYSTEM_MESSAGE = """
You are an expert SVG generation assistant. Your task is to generate VALID, self-contained SVG code based on the user's request.
Only output the SVG code itself. Do not include any explanations, markdown backticks (```svg ... ```), or any other text before or after the SVG code block.
The SVG should be well-formed XML, use standard SVG 1.1 features where possible for maximum compatibility, and be visually appealing.
Ensure paths are closed if they represent filled shapes. Use viewBox for scalability.
Minimize use of external fonts or resources unless explicitly part of the icon's design and unavoidable.
If generating icons, they should generally be square and use a viewBox like "0 0 100 100" or similar, unless the description implies otherwise.
"""

class LLMService:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.session = requests.Session() # Use a session for potential connection pooling

    def _clean_svg_response(self, svg_code):
        """Helper to remove common LLM-added markdown/text around SVG code."""
        if not isinstance(svg_code, str): # Ensure it's a string before stripping
            return "" 
        svg_code = svg_code.strip()
        
        # More robust cleaning for various markdown code block syntaxes
        prefixes_to_remove = ["```svg", "```xml", "```json", "```"] # Added ```json as some models might wrap it
        
        # Handle cases where the desired content might be within a ```block```
        # that starts with a language specifier, e.g. ```svg\n<svg>...</svg>\n```
        for prefix_candidate in prefixes_to_remove:
            if svg_code.startswith(prefix_candidate):
                # Attempt to strip the prefix and then the first newline if it exists immediately after
                temp_code = svg_code[len(prefix_candidate):]
                if temp_code.startswith('\n'):
                    temp_code = temp_code[1:]
                # Then check if the remaining code ends with ```
                if temp_code.strip().endswith("```"):
                    svg_code = temp_code.strip()[:-len("```")].strip()
                    break # Found and processed a block
                # If it doesn't end with ``` but started with a prefix, assume it's just the prefix to strip
                # This path might be risky if the content genuinely starts with the prefix text itself.
                # However, for LLM output, this is usually an indicator of a code block.
                # Let's refine this to only strip if it's clearly a code block marker
                # Fallback to simple prefix stripping if not a clear block
                # svg_code = svg_code[len(prefix_candidate):].strip() 
                # break 
        else: # If no prefix from prefixes_to_remove matched and was handled
            if svg_code.startswith("```"): # Generic backticks without language
                 # Find the first newline after the prefix
                newline_index = svg_code.find('\n', 3)
                if newline_index != -1:
                    svg_code = svg_code[newline_index+1:] 
                else: 
                    svg_code = svg_code[3:]
                svg_code = svg_code.strip()
            if svg_code.endswith("```"):
                svg_code = svg_code[:-len("```")].strip()

        return svg_code

    def generate_svg(self, provider_id, model_id, user_prompt):
        provider_details = self.config_manager.get_provider_details(provider_id)
        model_details = self.config_manager.get_model_details(provider_id, model_id)

        if not provider_details or not model_details:
            return {"success": False, "error": "Invalid provider or model ID."}

        api_key_name = provider_details.get("api_key_env_var")
        api_key = self.config_manager.get_api_key(api_key_name) if api_key_name else None
        
        if api_key_name and not api_key:
            return {"success": False, "error": f"API key '{api_key_name}' not found in user_api_keys.json."}

        base_url = provider_details.get("base_url")
        model_type = model_details.get("type")
        
        # Ensure base_url is correctly formatted (no double slashes if it already ends with one)
        base_url = base_url.rstrip('/')
        
        full_user_prompt = f"User request: {user_prompt}\nGenerate the SVG code."

        try:
            if model_type in ["chat_completion", "chat_completion_openai_compatible"]:
                endpoint = f"{base_url}/chat/completions"
                headers = {"Content-Type": "application/json"}
                if api_key: 
                    headers["Authorization"] = f"Bearer {api_key}"
                
                payload = {
                    "model": model_id, 
                    "messages": [
                        {"role": "system", "content": SVG_PROMPT_SYSTEM_MESSAGE},
                        {"role": "user", "content": full_user_prompt}
                    ],
                    "max_tokens": 10000, 
                    "temperature": 1.0 
                }
                
                response = self.session.post(endpoint, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                data = response.json()
                svg_code = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                svg_code = self._clean_svg_response(svg_code)
                return {"success": True, "svg_code": svg_code}

            elif model_type == "messages": # Anthropic
                endpoint = f"{base_url}/messages"
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01" 
                }
                payload = {
                    "model": model_id,
                    "system": SVG_PROMPT_SYSTEM_MESSAGE,
                    "messages": [
                        {"role": "user", "content": full_user_prompt}
                    ],
                    "max_tokens": 10000,
                    "temperature": 1.0
                }
                response = self.session.post(endpoint, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                data = response.json()
                svg_code = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        svg_code += block.get("text", "")
                svg_code = self._clean_svg_response(svg_code)
                return {"success": True, "svg_code": svg_code}

            elif model_type == "generative": # Google Gemini
                # Base URL for Gemini is typically "https://generativelanguage.googleapis.com/v1beta"
                # And the specific model ID is part of the path, so providers.json base_url should be
                # "https://generativelanguage.googleapis.com/v1beta/models" as you specified.
                endpoint = f"{base_url}/{model_id}:generateContent?key={api_key}"
                headers = {"Content-Type": "application/json"}
                
                combined_prompt_for_gemini = f"{SVG_PROMPT_SYSTEM_MESSAGE}\n\nUser request: {user_prompt}\nGenerate the SVG code."
                
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": combined_prompt_for_gemini}]}],
                    "generationConfig": {
                        "maxOutputTokens": 10000, 
                        "temperature": 1.0,
                    }
                }
                response = self.session.post(endpoint, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                data = response.json()
                
                # ***** CORRECTED GEMINI RESPONSE HANDLING *****
                svg_code = ""
                candidates_list = data.get("candidates")
                if candidates_list and isinstance(candidates_list, list) and len(candidates_list) > 0:
                    first_candidate = candidates_list[0] 
                    if isinstance(first_candidate, dict):
                        content_block = first_candidate.get("content")
                        if content_block and isinstance(content_block, dict):
                            parts_list = content_block.get("parts")
                            if parts_list and isinstance(parts_list, list) and len(parts_list) > 0:
                                first_part = parts_list[0] 
                                if isinstance(first_part, dict):
                                    svg_code = first_part.get("text", "")
                
                if not svg_code: 
                    print(f"Warning: Could not extract text from Gemini response, or response was empty. "
                          f"Provider: Google, Model: {model_id}. "
                          f"Full response data (first 500 chars): {str(data)[:500]}")
                # *********************************************
                
                svg_code = self._clean_svg_response(svg_code)
                return {"success": True, "svg_code": svg_code}

            elif model_type == "chat_completion_ollama": # Ollama
                endpoint = f"{base_url}/chat" 
                headers = {"Content-Type": "application/json"}
                payload = {
                    "model": model_id, 
                    "messages": [
                        {"role": "system", "content": SVG_PROMPT_SYSTEM_MESSAGE},
                        {"role": "user", "content": full_user_prompt}
                    ],
                    "stream": False, 
                    "options": { 
                        "temperature": 0.5,
                        "num_predict": 3000 
                    }
                }
                response = self.session.post(endpoint, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                data = response.json()
                svg_code = data.get("message", {}).get("content", "")
                svg_code = self._clean_svg_response(svg_code)
                return {"success": True, "svg_code": svg_code}

            else:
                return {"success": False, "error": f"Unsupported model type: {model_type}"}

        except requests.exceptions.Timeout:
            return {"success": False, "error": "API request timed out after 120 seconds."}
        except requests.exceptions.HTTPError as e:
            error_message = f"HTTP Error: {e.response.status_code} - {e.response.reason}"
            try:
                error_detail = e.response.json() # Try to parse JSON error from response body
                # Some APIs put detailed errors in specific fields
                if isinstance(error_detail, dict) and "error" in error_detail:
                    if isinstance(error_detail["error"], dict) and "message" in error_detail["error"]:
                        error_message += f" - Detail: {error_detail['error']['message']}"
                    elif isinstance(error_detail["error"], str):
                         error_message += f" - Detail: {error_detail['error']}"
                    else:
                        error_message += f" - Detail: {json.dumps(error_detail)}"
                else:
                    error_message += f" - Detail: {json.dumps(error_detail)}"

            except json.JSONDecodeError: # If response body is not JSON
                error_message += f" - Detail (non-JSON): {e.response.text[:500]}" # Show first 500 chars
            return {"success": False, "error": error_message}
        except requests.exceptions.RequestException as e: # Other request errors (DNS, connection, etc.)
            return {"success": False, "error": f"API Request Error: {str(e)}"}
        except Exception as e:
            import traceback
            traceback.print_exc() 
            return {"success": False, "error": f"An unexpected error occurred in LLM service: {str(e)}"}