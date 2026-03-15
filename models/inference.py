#!/usr/bin/env python3
"""
Inference wrapper for fine-tuned Phi-2 code review model.

This module provides a simple interface for loading the model and generating
code reviews. Designed to be used by the FastAPI backend.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel, PeftConfig

logger = logging.getLogger(__name__)


class CodeReviewModel:
    """Wrapper for fine-tuned Phi-2 code review model."""

    def __init__(
        self,
        model_path: str = "./models/checkpoints/phi2-code-review",
        base_model_name: str = "microsoft/phi-2",
        device: Optional[str] = None,
        max_new_tokens: int = 512,
        temperature: float = 0.2,
        top_p: float = 0.9,
        repetition_penalty: float = 1.1,
    ):
        """
        Initialize the code review model.

        Args:
            model_path: Path to LoRA fine-tuned model (or None for base model only)
            base_model_name: Hugging Face model name for the base model
            device: Device to use ('cuda', 'cpu', or None for auto-detect)
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0 = greedy)
            top_p: Top-p sampling parameter
            repetition_penalty: Penalty for repeating tokens
        """
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.repetition_penalty = repetition_penalty

        logger.info(f"Loading model on device: {self.device}")

        # Load tokenizer
        logger.info(f"Loading tokenizer from {base_model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(
            base_model_name, trust_remote_code=True
        )
        self.tokenizer.pad_token = self.tokenizer.eos_token

        # Load base model
        logger.info(f"Loading base model: {base_model_name}")
        torch_dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            trust_remote_code=True,
            torch_dtype=torch_dtype,
        )
        self.model.to(self.device)
        self.model.eval()

        # Load LoRA weights if available
        if model_path and Path(model_path).exists():
            logger.info(f"Loading LoRA weights from {model_path}")
            self.model = PeftModel.from_pretrained(
                self.model,
                model_path,
                torch_dtype=torch_dtype,
            )
            logger.info("LoRA weights loaded successfully")
        else:
            logger.warning("No LoRA weights found. Using base model only.")

        logger.info("Model loaded and ready for inference")

    def create_prompt(
        self, code: str, filename: str = "example.py", language: str = "python"
    ) -> str:
        """
        Create the instruction prompt for code review.

        Args:
            code: Source code to review
            filename: Name of the file (for context)
            language: Programming language

        Returns:
            Formatted prompt string
        """
        prompt = f"""[INST] <<SYS>>
You are an expert code reviewer. Analyze the following code for:
1. Bugs and potential errors
2. Performance optimizations
3. Best practice violations
4. Security issues

Output format (JSON):
{{
  "severity": "high|medium|low",
  "line_number": <line number or null>,
  "category": "bug|optimization|style|security",
  "suggestion": "<concise fix>",
  "explanation": "<detailed reasoning>"
}}
<</SYS>>

Code file: {filename}
Language: {language}

{code}

Analyze the code above and provide your review. [/INST]"""
        return prompt

    def generate(self, prompt: str) -> str:
        """
        Generate a code review from the model.

        Args:
            prompt: Input prompt with code to review

        Returns:
            Generated review text (may include JSON)
        """
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=2048,
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                repetition_penalty=self.repetition_penalty,
                do_sample=(self.temperature > 0),
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        # Extract only the generated part (after the prompt)
        response = response[len(prompt) :].strip()
        return response

    def review_code(
        self, code: str, filename: str = None, language: str = "python"
    ) -> Dict[str, Any]:
        """
        Complete code review with structured output parsing.

        Args:
            code: Source code to review
            filename: Optional filename for context
            language: Programming language

        Returns:
            Dictionary with review results
        """
        if filename is None:
            filename = f"example.{language}"

        prompt = self.create_prompt(code, filename, language)
        response = self.generate(prompt)

        # Try to extract JSON from response
        review = self._extract_json(response)

        # Add metadata
        review["_raw_response"] = response
        review["_model"] = "phi-2-finetuned"

        return review

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Extract JSON object from model response.

        The model may output JSON within markdown code blocks or as plain text.
        """
        import re

        # Try to find JSON in code blocks
        json_match = re.search(r"```(?:json)?\s*({.*?})\s*```", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find any JSON object
            json_match = re.search(r"({.*?})", text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Fallback: parse entire response
                json_str = text

        try:
            parsed = json.loads(json_str)
            # Ensure required fields
            defaults = {
                "severity": "medium",
                "line_number": None,
                "category": "general",
                "suggestion": "",
                "explanation": "",
            }
            for key, default in defaults.items():
                if key not in parsed:
                    parsed[key] = default
            return parsed
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON: {e}")
            return {
                "severity": "medium",
                "line_number": None,
                "category": "general",
                "suggestion": "Review output could not be parsed",
                "explanation": text[:500],  # Include raw response truncated
                "_parse_error": True,
            }

    def batch_review(self, code_files: list) -> list:
        """
        Review multiple code files in batch.

        Args:
            code_files: List of dicts with keys: 'code', 'filename', 'language'

        Returns:
            List of review results
        """
        results = []
        for file in code_files:
            try:
                review = self.review_code(
                    code=file["code"],
                    filename=file.get("filename"),
                    language=file.get("language", "python"),
                )
                results.append(review)
            except Exception as e:
                logger.error(f"Failed to review {file.get('filename')}: {e}")
                results.append(
                    {
                        "severity": "error",
                        "line_number": None,
                        "category": "system",
                        "suggestion": "Review failed",
                        "explanation": str(e),
                        "_error": True,
                    }
                )
        return results


# Singleton instance for the FastAPI backend
_model_instance = None


def get_model() -> CodeReviewModel:
    """
    Get or create the singleton model instance.
    This ensures the model is loaded only once in memory.
    """
    global _model_instance
    if _model_instance is None:
        # Check for model path in environment
        model_path = os.getenv("MODEL_PATH", "./models/checkpoints/phi2-code-review")
        base_model = os.getenv("BASE_MODEL", "microsoft/phi-2")

        _model_instance = CodeReviewModel(
            model_path=model_path if Path(model_path).exists() else None,
            base_model_name=base_model,
        )
    return _model_instance


if __name__ == "__main__":
    # Test inference
    logging.basicConfig(level=logging.INFO)

    test_code = """
def calculate_sum(a, b):
    return a + b

print(calculate_sum(5, 10))
"""

    model = get_model()
    review = model.review_code(test_code, filename="test.py")

    print(json.dumps(review, indent=2))
