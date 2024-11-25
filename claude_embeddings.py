# claude_embeddings.py
import requests
import numpy as np
from typing import List

class ClaudeEmbeddings:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.api_url = "https://api.anthropic.com/v1/messages"
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json={
                    "model": "claude-3-sonnet-20240229",
                    "max_tokens": 1000,
                    "messages": [{
                        "role": "user", 
                        "content": f"Convert this text into a semantic vector representation:\n\n{text}"
                    }]
                }
            )
            embedding = response.json()["content"][0]["text"]
            embeddings.append(embedding)
        return embeddings