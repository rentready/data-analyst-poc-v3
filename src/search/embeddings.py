"""Embeddings generation using OpenAI/Azure OpenAI."""

import logging
from typing import List, Optional
from openai import AsyncAzureOpenAI, AsyncOpenAI
import tiktoken

logger = logging.getLogger(__name__)


class EmbeddingsGenerator:
    """Generate embeddings for text chunks using OpenAI."""
    
    def __init__(
        self, 
        model: str = 'text-embedding-3-large',
        dimensions: int = 1536,
        batch_size: int = 16,
        use_azure: bool = True,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_version: str = '2024-02-01'
    ):
        """
        Initialize embeddings generator.
        
        Args:
            model: Embedding model name
            dimensions: Embedding vector dimensions
            batch_size: Number of texts to embed in one batch
            use_azure: Use Azure OpenAI (True) or OpenAI API (False)
            api_key: API key for OpenAI
            base_url: Base URL for Azure OpenAI
            api_version: API version for Azure OpenAI
        """
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.use_azure = use_azure
        
        # Initialize OpenAI client
        if use_azure:
            self.client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version=api_version
            )
        else:
            self.client = AsyncOpenAI(api_key=api_key)
        
        # Token counter for cost estimation
        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            # Fallback to cl100k_base for unknown models
            self.encoding = tiktoken.get_encoding('cl100k_base')
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))
    
    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector
        """
        try:
            response = await self.client.embeddings.create(
                input=text,
                model=self.model,
                dimensions=self.dimensions if self.model.startswith('text-embedding-3') else None
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f'Failed to generate embedding: {e}')
            raise
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in batches.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        embeddings = []
        
        # Process in batches to avoid rate limits
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            
            try:
                response = await self.client.embeddings.create(
                    input=batch,
                    model=self.model,
                    dimensions=self.dimensions if self.model.startswith('text-embedding-3') else None
                )
                
                batch_embeddings = [item.embedding for item in response.data]
                embeddings.extend(batch_embeddings)
                
                logger.info(f'Generated embeddings for batch {i // self.batch_size + 1} ({len(batch)} texts)')
            
            except Exception as e:
                logger.error(f'Failed to generate embeddings for batch {i // self.batch_size + 1}: {e}')
                # Return None for failed embeddings
                embeddings.extend([None] * len(batch))
        
        return embeddings
    
    async def close(self):
        """Close OpenAI client."""
        await self.client.close()

