#!/usr/bin/env python3
"""
hipstercheck - Model Inference for Code Review

Loads fine-tuned Phi-2 model and provides inference API.
"""

import os
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel, PeftConfig
from typing import Dict, Any, Optional
import logging

try:
    import json5
except ImportError:
    json5 = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CodeReviewInference:
    """Inference wrapper for code review model."""

    def __init__(
        self,
        model_path: Optional[str] = "models/checkpoints/phi2-code-review",
        base_model_name: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.model_path = model_path
        self.base_model_name = base_model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = None
        self.model = None
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load prompt template from config or default."""
        # First, try the config in the model_path (for checkpoint-specific)
        if self.model_path is not None:
            config_path = os.path.join(self.model_path, "config.yaml")
            if os.path.exists(config_path):
                import yaml

                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)
                return config["dataset"]["prompt_template"]
        # Fallback to the project's config.yaml (in same dir as this file)
        project_config = os.path.join(os.path.dirname(__file__), "config.yaml")
        if os.path.exists(project_config):
            import yaml

            with open(project_config, "r") as f:
                config = yaml.safe_load(f)
            return config["dataset"]["prompt_template"]
        # Fallback to a minimal default (should not normally happen)
        return """Analyze this code and provide a code review:
[Language: {language}]

Code:
{code}

Provide a review in JSON format with the following fields:
{
  "severity": "high|medium|low",
  "line_number": <int>,
  "category": "bug|optimization|style|security|best_practice",
  "suggestion": "<concise suggestion>",
  "explanation": "<detailed explanation>",
  "code_example": "<optional corrected code>"
}

Review:"""

    def load(self):
        """Load the fine-tuned model and tokenizer."""
        logger.info(f"Loading model from {self.model_path}")

        # Check if it's a LoRA checkpoint
        config_path = os.path.join(self.model_path, "adapter_config.json")
        if os.path.exists(config_path):
            # LoRA model - need base model
            peft_config = PeftConfig.from_pretrained(self.model_path)
            base_model_path = (
                self.base_model_name or peft_config.base_model_name_or_path
            )

            logger.info(f"Loading base model: {base_model_path}")
            tokenizer = AutoTokenizer.from_pretrained(base_model_path)
            model = AutoModelForCausalLM.from_pretrained(
                base_model_path,
                torch_dtype=torch.bfloat16
                if torch.cuda.is_available()
                else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                trust_remote_code=True,
            )
            model = PeftModel.from_pretrained(model, self.model_path)
        else:
            # Fully merged model
            tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=torch.bfloat16
                if torch.cuda.is_available()
                else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                trust_remote_code=True,
            )

        # Set padding token
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model.eval()
        self.tokenizer = tokenizer
        self.model = model

        logger.info("Model loaded successfully")
        return self

    def generate_review(
        self, code: str, language: str = "python", max_new_tokens: int = 512
    ) -> Dict[str, Any]:
        """
        Generate code review for given code snippet.

        Args:
            code: Source code to review
            language: Programming language (python, cpp, etc.)
            max_new_tokens: Maximum tokens to generate

        Returns:
            Dictionary with review fields: severity, line_number, category, suggestion, explanation, code_example
        """
        if self.model is None or self.tokenizer is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        # Get model's maximum position embeddings
        if hasattr(self.model, "config") and hasattr(
            self.model.config, "max_position_embeddings"
        ):
            max_model_len = self.model.config.max_position_embeddings
        else:
            max_model_len = self.tokenizer.model_max_length

        # Proactively truncate code to fit within context window
        # Compute base prompt length (without code)
        base_prompt = self.prompt_template.format(code="", language=language)
        base_tokens = self.tokenizer(base_prompt, return_tensors="pt")
        base_len = base_tokens.input_ids.shape[1]
        # Determine allowed code token count (leave small margin)
        allowed_code_len = max_model_len - base_len - 5
        if allowed_code_len <= 0:
            return {
                "severity": "error",
                "line_number": 0,
                "category": "system_error",
                "suggestion": "Prompt template too long for model context window",
                "explanation": f"The base prompt length ({base_len}) exceeds model capacity ({max_model_len}).",
                "code_example": None,
            }

        # Tokenize code without special tokens
        code_ids = self.tokenizer.encode(code, add_special_tokens=False)
        if len(code_ids) > allowed_code_len:
            # Truncate code from the beginning (keep the end) to preserve recent code
            truncated_code_ids = code_ids[:allowed_code_len]
            truncated_code = self.tokenizer.decode(
                truncated_code_ids, skip_special_tokens=True
            )
            logger.warning(
                f"Code truncated from {len(code_ids)} to {len(truncated_code_ids)} tokens to fit model context."
            )
            code = truncated_code

        # Create prompt with (possibly truncated) code
        prompt = self.prompt_template.format(code=code, language=language)

        # Tokenize the final prompt
        inputs = self.tokenizer(prompt, return_tensors="pt")
        input_len = inputs.input_ids.shape[1]

        # Double-check length (should be within limit)
        if input_len >= max_model_len:
            # Emergency truncation: cut a few more tokens from code
            excess = input_len - max_model_len + 1
            # Re-truncate code further by removing from the end
            code_ids = self.tokenizer.encode(code, add_special_tokens=False)
            if len(code_ids) > excess:
                truncated_code_ids = code_ids[:-excess]
                code = self.tokenizer.decode(
                    truncated_code_ids, skip_special_tokens=True
                )
                prompt = self.prompt_template.format(code=code, language=language)
                inputs = self.tokenizer(prompt, return_tensors="pt")
                input_len = inputs.input_ids.shape[1]
            if input_len >= max_model_len:
                return {
                    "severity": "error",
                    "line_number": 0,
                    "category": "system_error",
                    "suggestion": "Input code too long for model context window even after truncation",
                    "explanation": f"Input length ({input_len}) still exceeds model max ({max_model_len}).",
                    "code_example": None,
                }

        # Calculate effective max_new_tokens
        effective_max_new_tokens = min(
            max_new_tokens, max(0, max_model_len - input_len)
        )

        # Move inputs to device
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=effective_max_new_tokens,
                temperature=0.2,
                top_p=0.95,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # Decode response
        full_output = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        response_start = full_output.find("Review:") + len("Review:")
        response_text = full_output[response_start:].strip()

        # Parse JSON from response using robust extractor
        review = self._extract_json(response_text)

        return review

    def batch_generate(self, code_snippets: list, language: str = "python") -> list:
        """Generate reviews for multiple code snippets."""
        reviews = []
        for code in code_snippets:
            review = self.generate_review(code, language)
            reviews.append(review)
        return reviews

    def create_prompt(
        self, code: str, filename: Optional[str] = None, language: str = "python"
    ) -> str:
        """Create prompt for code review."""
        # Include filename in the code if provided
        if filename:
            code = f"Code file: {filename}\n{code}"
        # Use simple replacement to avoid conflicts with braces in JSON
        prompt = self.prompt_template.replace("{code}", code).replace(
            "{language}", language
        )
        return prompt

    def _extract_json(self, response: str) -> Dict[str, Any]:
        """Extract the first balanced JSON object from the response."""
        # Find the first opening brace
        start = response.find("{")
        if start == -1:
            return {
                "severity": "unknown",
                "line_number": 0,
                "category": "parsing_error",
                "suggestion": "Model output could not be parsed as JSON",
                "explanation": response[:500],
                "code_example": None,
            }
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(response)):
            char = response[i]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    json_str = response[start : i + 1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        if json5 is not None:
                            try:
                                return json5.loads(json_str)
                            except Exception:
                                pass
                        # Break to fallback
                        break
        # Fallback to simple first-last brace method
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start != -1 and json_end != -1:
            json_str = response[json_start:json_end]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                if json5 is not None:
                    try:
                        return json5.loads(json_str)
                    except Exception:
                        pass
        return {
            "severity": "unknown",
            "line_number": 0,
            "category": "parsing_error",
            "suggestion": "Model output could not be parsed as JSON",
            "explanation": response[:500],
            "code_example": None,
        }

    def review_code(self, code: str, language: str = "python") -> Dict[str, Any]:
        """Review code and return structured output."""
        if self.model is None or self.tokenizer is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        response = self.generate_review(code, language)
        # Add raw response for debugging
        response["_raw_response"] = response.get("explanation", "")
        return response

    def batch_review(self, files: list) -> list:
        """Review multiple files."""
        results = []
        for file_info in files:
            code = file_info.get("code", "")
            filename = file_info.get("filename", "unknown")
            language = file_info.get("language", "python")

            try:
                review = self.review_code(code, language)
                review["filename"] = filename
                review["_success"] = True
            except Exception as e:
                review = {
                    "filename": filename,
                    "severity": "error",
                    "line_number": 0,
                    "category": "system_error",
                    "suggestion": str(e),
                    "explanation": f"Failed to review file: {e}",
                    "code_example": None,
                    "_success": False,
                    "_error": str(e),
                }
            results.append(review)
        return results


if __name__ == "__main__":
    # Quick test
    import argparse

    parser = argparse.ArgumentParser(description="Test code review inference")
    parser.add_argument(
        "--model_path", type=str, default="models/checkpoints/phi2-code-review"
    )
    parser.add_argument("--code_file", type=str, help="Path to code file to review")
    args = parser.parse_args()

    inference = CodeReviewInference(model_path=args.model_path)
    inference.load()

    if args.code_file:
        with open(args.code_file, "r") as f:
            code = f.read()
    else:
        code = """
def compute(x, y):
    temp = x + y
    return x * y
"""

    review = inference.generate_review(code)
    print(json.dumps(review, indent=2))


# Alias for compatibility with tests
CodeReviewModel = CodeReviewInference


def get_model(model_path: str = None, device: str = None):
    """Factory function to get a code review model."""
    if model_path is None:
        model_path = "models/checkpoints/phi2-code-review"
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    return CodeReviewInference(model_path=model_path, device=device)
