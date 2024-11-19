from typing import List, Dict
import json
import os

class ChatStorage:
    def __init__(self, storage_file: str = "chat_history.json"):
        self.storage_file = storage_file
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.storage_path = os.path.join(self.base_dir, storage_file)

    def save_chat_history(self, history_data: List[Dict]):
        """Save chat history to file"""
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving chat history: {e}")

    def load_chat_history(self) -> List[Dict]:
        """Load chat history from file"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading chat history: {e}")
        
        return []  # Return empty list if file doesn't exist or there's an error