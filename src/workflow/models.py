"""Data models for the new orchestrator workflow."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import uuid


@dataclass
class EntityList:
    """List of entities extracted from user query"""
    request_id: str
    user_prompt: str
    entities: List[str] = field(default_factory=list)  # List of entity names/terms
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "request_id": self.request_id,
            "user_prompt": self.user_prompt,
            "entities": self.entities
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityList":
        """Create from dictionary."""
        return cls(
            request_id=data["request_id"],
            user_prompt=data["user_prompt"],
            entities=data.get("entities", [])
        )


@dataclass
class DataExtractionRequest:
    """План извлечения данных"""
    request_id: str
    user_prompt: str
    knowledge_terms: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "request_id": self.request_id,
            "user_prompt": self.user_prompt,
            "knowledge_terms": self.knowledge_terms
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataExtractionRequest":
        """Create from dictionary."""
        return cls(
            request_id=data["request_id"],
            user_prompt=data["user_prompt"],
            knowledge_terms=data["knowledge_terms"],
        )


@dataclass  
class ExecutionResult:
    """Результат выполнения плана"""
    request_id: str
    request: DataExtractionRequest
    extracted_data: str
    analysis: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "request_id": self.request_id,
            "request": self.request.to_dict(),
            "extracted_data": self.extracted_data,
            "analysis": self.analysis
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionResult":
        """Create from dictionary."""
        return cls(
            request_id=data["request_id"],
            request=DataExtractionRequest.from_dict(data["request"]),
            extracted_data=data["extracted_data"],
            analysis=data["analysis"]
        )


@dataclass
class ReviewFeedback:
    """Обратная связь от ревьюера"""
    request_id: str
    approved: bool
    feedback: str
    missing_steps: Optional[List[str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "request_id": self.request_id,
            "approved": self.approved,
            "feedback": self.feedback,
            "missing_steps": self.missing_steps
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewFeedback":
        """Create from dictionary."""
        return cls(
            request_id=data["request_id"],
            approved=data["approved"],
            feedback=data["feedback"],
            missing_steps=data.get("missing_steps")
        )


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())
