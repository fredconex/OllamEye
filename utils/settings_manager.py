import os
import json
from pathlib import Path


class SettingsManager:
    DEFAULT_CONFIG_PATH = "config.json"

    @staticmethod
    def load_config():
        config_path = Path() / SettingsManager.DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return {}

        with open(config_path, "r") as file:
            config = json.load(file)

        # Ensure default values are set
        config.setdefault("openai_url", "https://api.openai.com/v1")
        config.setdefault("openai_key", "")
        config.setdefault("openai_default_model", "llama3.1:8b")

        config.setdefault("ollama_url", "http://localhost:11434")
        config.setdefault("ollama_default_model", "llama3.1:8b")

        config.setdefault("temperature", None)
        config.setdefault("context_size", None)
        config.setdefault("system_prompt", "")
        config.setdefault("vision_capable_models", [])

        return config

    @staticmethod
    def save_config(config):
        with open(SettingsManager.DEFAULT_CONFIG_PATH, "w") as file:
            json.dump(config, file, indent=4)


def get_system_prompt():
    try:
        with open("config.json", "r") as f:
            settings = json.load(f)
        return settings.get(
            "system_prompt",
            "You are a helpful AI assistant, answer in same language of question.",
        )
    except FileNotFoundError:
        return "You are a helpful AI assistant, answer in same language of question."


def get_default_model():
    try:
        with open("config.json", "r") as f:
            settings = json.load(f)
        if get_provider() == "openai":
            return settings.get("openai_default_model", "llama3.1:8b")
        else:
            return settings.get("ollama_default_model", "llama3.1:8b")
    except FileNotFoundError:
        return "llama3.1:8b"


def load_settings_from_file():
    return SettingsManager.load_config()


def save_settings_to_file(settings):
    SettingsManager.save_config(settings)


def get_provider():
    settings = load_settings_from_file()
    return settings.get("provider", "ollama")


def get_openai_key():
    settings = load_settings_from_file()
    return settings.get("openai_key")


def get_openai_url():
    try:
        with open("config.json", "r") as f:
            settings = json.load(f)
        return settings.get("openai_url", "https://api.openai.com/v1")
    except FileNotFoundError:
        return "https://api.openai.com/v1"


def get_ollama_url():
    try:
        with open("config.json", "r") as f:
            settings = json.load(f)
        return settings.get("ollama_url", "http://localhost:11434")
    except FileNotFoundError:
        return "http://localhost:11434"
