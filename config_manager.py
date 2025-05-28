import json
import os

class ConfigManager:
    def __init__(self, app_dir):
        self.app_dir = app_dir
        self.providers_config = self._load_json(os.path.join(self.app_dir, "providers.json"))
        self.api_keys = self._load_json(os.path.join(self.app_dir, "user_api_keys.json"))

        if not self.providers_config:
            # Fallback to an empty structure if providers.json is missing or invalid
            # In a real app, might raise an error or log more verbosely
            print("Error: providers.json not found or invalid. Application may not function correctly.")
            self.providers_config = {"providers": []}
        
        if not self.api_keys:
            # Fallback for api keys, user will be notified if keys are missing for a provider
            print("Warning: user_api_keys.json not found or invalid. API calls may fail if keys are required.")
            self.api_keys = {}

    def _load_json(self, file_path):
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {file_path}: {e}")
            return None
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            return None

    def get_providers(self):
        return self.providers_config.get("providers", [])

    def get_provider_details(self, provider_id):
        for provider in self.get_providers():
            if provider.get("id") == provider_id:
                return provider
        return None

    def get_model_details(self, provider_id, model_id):
        provider = self.get_provider_details(provider_id)
        if provider:
            for model in provider.get("models", []):
                if model.get("id") == model_id:
                    return model
        return None

    def get_api_key(self, api_key_env_var_name):
        if not api_key_env_var_name: # For local models like Ollama, LMStudio
            return None 
        return self.api_keys.get(api_key_env_var_name)

if __name__ == '__main__':
    # Basic test
    # Create dummy files for testing in the same directory as this script
    # This is just for quick testing of ConfigManager, real files should be with the app
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Dummy providers.json
    dummy_providers_data = {
      "providers": [
        {
          "id": "openai",
          "name": "OpenAI",
          "api_key_env_var": "OPENAI_API_KEY",
          "base_url": "https://api.openai.com/v1",
          "models": [
            { "id": "gpt-4.1", "name": "GPT-4.1", "type": "chat_completion" }
          ]
        },
        {
          "id": "ollama",
          "name": "Ollama (Local)",
          "api_key_env_var": None,
          "base_url": "http://localhost:11434/api",
          "models": [
            { "id": "llama3", "name": "Llama 3 (Ollama)", "type": "chat_completion_ollama" }
          ]
        }
      ]
    }
    with open(os.path.join(script_dir, "providers.json"), "w") as f:
        json.dump(dummy_providers_data, f, indent=2)

    # Dummy user_api_keys.json
    dummy_keys_data = {
        "OPENAI_API_KEY": "sk-dummykey123"
    }
    with open(os.path.join(script_dir, "user_api_keys.json"), "w") as f:
        json.dump(dummy_keys_data, f, indent=2)

    config_manager = ConfigManager(app_dir=script_dir)
    
    print("Providers:", [p['name'] for p in config_manager.get_providers()])
    
    openai_details = config_manager.get_provider_details("openai")
    if openai_details:
        print("\nOpenAI Details:", openai_details['name'])
        print("OpenAI API Key Env Var Name:", openai_details['api_key_env_var'])
        print("OpenAI API Key:", config_manager.get_api_key(openai_details['api_key_env_var']))
        
        gpt_model = config_manager.get_model_details("openai", "gpt-4.1")
        if gpt_model:
            print("GPT Model:", gpt_model['name'], "Type:", gpt_model['type'])

    ollama_details = config_manager.get_provider_details("ollama")
    if ollama_details:
        print("\nOllama Details:", ollama_details['name'])
        print("Ollama API Key Env Var Name:", ollama_details['api_key_env_var']) # Should be None
        print("Ollama API Key:", config_manager.get_api_key(ollama_details['api_key_env_var'])) # Should be None
