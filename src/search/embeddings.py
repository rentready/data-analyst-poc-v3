"""Embeddings generation using OpenAI/Azure OpenAI."""

import logging
import asyncio
from typing import List, Optional, Union
from openai import AsyncAzureOpenAI, AsyncOpenAI, RateLimitError
import tiktoken

logger = logging.getLogger(__name__)

# Constants for retry logic
DEFAULT_MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 30.0
BACKOFF_MULTIPLIER = 2.0
DEFAULT_INTER_BATCH_DELAY = 0.5


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
        """
        Count tokens in text.
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Number of tokens
        """
        return len(self.encoding.encode(text))
    
    async def _execute_with_retry(
        self, 
        api_call_fn, 
        max_retries: int = DEFAULT_MAX_RETRIES,
        context: str = 'API call'
    ) -> any:
        """
        Execute API call with exponential backoff retry logic.
        
        Args:
            api_call_fn: Async function to execute
            max_retries: Maximum number of retry attempts
            context: Context description for logging
            
        Returns:
            API call result
            
        Raises:
            RateLimitError: If rate limit exceeded after all retries
            Exception: If API call fails for other reasons
        """
        retry_delay = INITIAL_RETRY_DELAY
        
        for attempt in range(max_retries):
            try:
                return await api_call_fn()
                
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f'Rate limit hit for {context}, retrying in {retry_delay:.1f}s '
                        f'(attempt {attempt + 1}/{max_retries})'
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * BACKOFF_MULTIPLIER, MAX_RETRY_DELAY)
                else:
                    logger.error(f'Rate limit exceeded for {context} after {max_retries} attempts')
                    raise
                    
            except Exception as e:
                logger.error(f'Failed {context}: {e}')
                raise
    
    async def generate_embedding(
        self, 
        text: str, 
        max_retries: int = DEFAULT_MAX_RETRIES
    ) -> List[float]:
        """
        Generate embedding for a single text with retry logic.
        
        Args:
            text: Text to embed
            max_retries: Maximum number of retry attempts for rate limiting
            
        Returns:
            Embedding vector
            
        Raises:
            RateLimitError: If rate limit exceeded after all retries
            Exception: If API call fails for other reasons
        """
        async def _call_api():
            # Prepare API parameters
            api_params = {
                'input': text,
                'model': self.model
            }
            
            # Only add dimensions for text-embedding-3 models
            if self.model.startswith('text-embedding-3'):
                api_params['dimensions'] = self.dimensions
            
            response = await self.client.embeddings.create(**api_params)
            return response.data[0].embedding
        
        return await self._execute_with_retry(
            _call_api, 
            max_retries=max_retries,
            context='embedding generation'
        )
    
    async def generate_embeddings_batch(
        self, 
        texts: List[str], 
        max_retries: int = DEFAULT_MAX_RETRIES,
        inter_batch_delay: float = DEFAULT_INTER_BATCH_DELAY
    ) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts in batches with rate limit handling.
        
        Args:
            texts: List of texts to embed
            max_retries: Maximum number of retry attempts for rate limiting
            inter_batch_delay: Delay between batches in seconds (to avoid rate limits)
            
        Returns:
            List of embedding vectors (None for failed embeddings)
        """
        if not texts:
            logger.warning('No texts provided for embedding generation')
            return []
        
        logger.info(f'Starting embeddings generation for {len(texts)} texts')
        logger.info(f'Model: {self.model}, Dimensions: {self.dimensions}, Batch size: {self.batch_size}')
        logger.info(f'Use Azure: {self.use_azure}, Inter-batch delay: {inter_batch_delay}s')
        
        embeddings: List[Optional[List[float]]] = []
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size
        
        # Process in batches to avoid rate limits
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            
            try:
                logger.info(f'Processing batch {batch_num}/{total_batches}: {len(batch)} texts')
                
                async def _call_batch_api():
                    # Prepare API parameters
                    api_params = {
                        'input': batch,
                        'model': self.model
                    }
                    
                    # Only add dimensions for text-embedding-3 models
                    if self.model.startswith('text-embedding-3'):
                        api_params['dimensions'] = self.dimensions
                    
                    response = await self.client.embeddings.create(**api_params)
                    return [item.embedding for item in response.data]
                
                batch_embeddings = await self._execute_with_retry(
                    _call_batch_api,
                    max_retries=max_retries,
                    context=f'batch {batch_num}/{total_batches}'
                )
                
                embeddings.extend(batch_embeddings)
                logger.info(
                    f'✅ Generated embeddings for batch {batch_num}/{total_batches} '
                    f'({len(batch)} texts, {len(batch_embeddings)} embeddings)'
                )
                
                # Add delay between batches to avoid rate limiting (except for last batch)
                if i + self.batch_size < len(texts):
                    await asyncio.sleep(inter_batch_delay)
                    
            except Exception as e:
                logger.error(
                    f'❌ Failed to generate embeddings for batch {batch_num}/{total_batches}: {e}',
                    exc_info=True
                )
                # Return None for failed embeddings
                embeddings.extend([None] * len(batch))
        
        successful_count = len([e for e in embeddings if e is not None])
        logger.info(f'Embeddings generation completed: {successful_count}/{len(embeddings)} successful')
        return embeddings
    
    async def close(self):
        """Close OpenAI client."""
        await self.client.close()


        """
        Generate embedding for a single text with retry logic.
        
        Args:
            text: Text to embed
            max_retries: Maximum number of retry attempts for rate limiting
            
        Returns:
            Embedding vector
            
        Raises:
            RateLimitError: If rate limit exceeded after all retries
            Exception: If API call fails for other reasons
        """
        async def _call_api():
            # Prepare API parameters
            api_params = {
                'input': text,
                'model': self.model
            }
            
            # Only add dimensions for text-embedding-3 models
            if self.model.startswith('text-embedding-3'):
                api_params['dimensions'] = self.dimensions
            
            response = await self.client.embeddings.create(**api_params)
            return response.data[0].embedding
        
        return await self._execute_with_retry(
            _call_api, 
            max_retries=max_retries,
            context='embedding generation'
        )
    
    async def generate_embeddings_batch(
        self, 
        texts: List[str], 
        max_retries: int = DEFAULT_MAX_RETRIES,
        inter_batch_delay: float = DEFAULT_INTER_BATCH_DELAY
    ) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts in batches with rate limit handling.
        
        Args:
            texts: List of texts to embed
            max_retries: Maximum number of retry attempts for rate limiting
            inter_batch_delay: Delay between batches in seconds (to avoid rate limits)
            
        Returns:
            List of embedding vectors (None for failed embeddings)
        """
        if not texts:
            logger.warning('No texts provided for embedding generation')
            return []
        
        logger.info(f'Starting embeddings generation for {len(texts)} texts')
        logger.info(f'Model: {self.model}, Dimensions: {self.dimensions}, Batch size: {self.batch_size}')
        logger.info(f'Use Azure: {self.use_azure}, Inter-batch delay: {inter_batch_delay}s')
        
        embeddings: List[Optional[List[float]]] = []
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size
        
        # Process in batches to avoid rate limits
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            
            try:
                logger.info(f'Processing batch {batch_num}/{total_batches}: {len(batch)} texts')
                
                async def _call_batch_api():
                    # Prepare API parameters
                    api_params = {
                        'input': batch,
                        'model': self.model
                    }
                    
                    # Only add dimensions for text-embedding-3 models
                    if self.model.startswith('text-embedding-3'):
                        api_params['dimensions'] = self.dimensions
                    
                    response = await self.client.embeddings.create(**api_params)
                    return [item.embedding for item in response.data]
                
                batch_embeddings = await self._execute_with_retry(
                    _call_batch_api,
                    max_retries=max_retries,
                    context=f'batch {batch_num}/{total_batches}'
                )
                
                embeddings.extend(batch_embeddings)
                logger.info(
                    f'✅ Generated embeddings for batch {batch_num}/{total_batches} '
                    f'({len(batch)} texts, {len(batch_embeddings)} embeddings)'
                )
                
                # Add delay between batches to avoid rate limiting (except for last batch)
                if i + self.batch_size < len(texts):
                    await asyncio.sleep(inter_batch_delay)
                    
            except Exception as e:
                logger.error(
                    f'❌ Failed to generate embeddings for batch {batch_num}/{total_batches}: {e}',
                    exc_info=True
                )
                # Return None for failed embeddings
                embeddings.extend([None] * len(batch))
        
        successful_count = len([e for e in embeddings if e is not None])
        logger.info(f'Embeddings generation completed: {successful_count}/{len(embeddings)} successful')
        return embeddings
    
    async def close(self):
        """Close OpenAI client."""
        await self.client.close()

