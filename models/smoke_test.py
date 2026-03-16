#!/usr/bin/env python3
"""
Smoke test for training pipeline components.

Tests model loading, LoRA application, dataset preparation, and forward pass
using a tiny dataset. Does not run full training to keep runtime short.
"""

import os
import sys
import tempfile
import json
import torch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.train import prepare_dataset
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import LoraConfig, get_peft_model, TaskType


def create_tiny_dataset(tmpdir: Path):
    dataset_dir = tmpdir / "dataset"
    dataset_dir.mkdir()
    train_file = dataset_dir / "split_train.jsonl"
    val_file = dataset_dir / "split_val.jsonl"
    train_examples = [
        {
            "code": "def add(a, b):\n    return a + b",
            "review": {
                "severity": "low",
                "line_number": 1,
                "category": "style",
                "suggestion": "Add type hints",
                "explanation": "Type hints improve clarity.",
            },
        },
        {
            "code": "x = 1\ny = 2\nprint(x + y)",
            "review": {
                "severity": "low",
                "line_number": None,
                "category": "style",
                "suggestion": "Use f-strings",
                "explanation": "f-strings are more readable.",
            },
        },
    ]
    val_examples = [
        {
            "code": "def mul(a, b):\n    return a * b",
            "review": {
                "severity": "low",
                "line_number": 1,
                "category": "style",
                "suggestion": "Add docstring",
                "explanation": "Document function purpose.",
            },
        }
    ]
    with open(train_file, "w") as f:
        for ex in train_examples:
            f.write(json.dumps(ex) + "\n")
    with open(val_file, "w") as f:
        for ex in val_examples:
            f.write(json.dumps(ex) + "\n")
    return str(train_file), str(val_file)


def test_components():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        train_file, val_file = create_tiny_dataset(tmp_path)

        print("🚀 Component smoke test")
        model_name = "microsoft/phi-2"
        print(f"  Model: {model_name}")
        print(f"  Train samples: 2, Val samples: 1")
        print(f"  Device: CPU")

        try:
            # Load tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_name, trust_remote_code=True
            )
            tokenizer.pad_token = tokenizer.eos_token
            print("✅ Tokenizer loaded")

            # Load model (use float16 to reduce memory)
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                trust_remote_code=True,
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True,
            )
            print("✅ Model loaded")

            # Apply LoRA with phi-2 compatible target modules
            lora_config = LoraConfig(
                r=16,
                lora_alpha=32,
                target_modules=["q_proj", "k_proj", "v_proj", "dense", "fc1", "fc2"],
                lora_dropout=0.1,
                bias="none",
                task_type=TaskType.CAUSAL_LM,
            )
            model = get_peft_model(model, lora_config)
            model.print_trainable_parameters()
            print("✅ LoRA applied")

            # Prepare dataset (with shorter max_length)
            train_dataset = prepare_dataset(train_file, tokenizer, max_length=512)
            print(f"✅ Dataset prepared: {len(train_dataset)} examples")

            # Forward pass test
            sample = train_dataset[0]
            input_ids = sample["input_ids"].unsqueeze(0)
            attention_mask = sample["attention_mask"].unsqueeze(0)
            with torch.no_grad():
                outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            print("✅ Forward pass successful")

            print("\n🎉 All checks passed! Fine-tuning pipeline is ready.")
            return 0

        except Exception as e:
            print(f"❌ Smoke test failed: {e}")
            import traceback

            traceback.print_exc()
            return 1


if __name__ == "__main__":
    sys.exit(test_components())
