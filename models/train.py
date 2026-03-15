#!/usr/bin/env python3
"""
Fine-tune Phi-2 model on code review dataset using LoRA.

Usage:
    python models/train.py

Prerequisites:
    1. Dataset prepared in dataset/split_*.jsonl
    2. Hugging Face token set (HF_TOKEN env var)
    3. GPU recommended (or set use_gpu: false in config.yaml)
"""

import os
import sys
import json
import yaml
import logging
from pathlib import Path
from datetime import datetime

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
    set_seed,
)
from peft import LoraConfig, get_peft_model, TaskType
from datasets import Dataset, load_dataset
import numpy as np

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """Load training configuration from YAML."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    logger.info(f"Loaded config from {config_path}")
    return config


def prepare_dataset(file_path: str, tokenizer, max_length: int) -> Dataset:
    """
    Load and preprocess dataset for training.

    Args:
        file_path: Path to JSONL file with examples
        tokenizer: Hugging Face tokenizer
        max_length: Maximum sequence length

    Returns:
        Tokenized Dataset object
    """
    logger.info(f"Loading dataset from {file_path}")

    # Load JSONL dataset
    dataset = load_dataset("json", data_files=file_path, split="train")

    logger.info(f"Loaded {len(dataset)} examples")

    def format_example(example):
        """Format example into instruction tuning format."""
        # Expecting: {"code": "...", "review": {...}}
        code = example.get("code", "")
        review = example.get("review", {})

        # Format review as JSON string
        if isinstance(review, dict):
            review_str = json.dumps(review, indent=2)
        else:
            review_str = str(review)

        # Construct prompt
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

Code file: example.py
Language: python

{code}

Analyze the code above and provide your review. [/INST]"""

        # Target response
        target = f"\n\n```json\n{review_str}\n```"

        # Combine prompt + target for training
        full_text = prompt + target

        tokenized = tokenizer(
            full_text,
            truncation=True,
            max_length=max_length,
            padding="max_length",
            return_tensors="pt",
        )

        # Labels are same as input_ids for causal LM
        labels = tokenized.input_ids[0].clone()

        # Mask out prompt tokens (set to -100) so we only compute loss on response
        prompt_len = len(tokenizer(prompt, truncation=False)["input_ids"])
        labels[:prompt_len] = -100

        return {
            "input_ids": tokenized.input_ids[0],
            "attention_mask": tokenized.attention_mask[0],
            "labels": labels,
        }

    # Tokenize dataset
    tokenized_dataset = dataset.map(
        format_example, remove_columns=dataset.column_names, desc="Tokenizing dataset"
    )

    logger.info(f"Dataset prepared with {len(tokenized_dataset)} examples")
    return tokenized_dataset


def compute_metrics(eval_pred):
    """Compute evaluation metrics."""
    predictions, labels = eval_pred
    predictions = np.argmax(predictions, axis=-1)

    # Compute cross-entropy loss
    loss = torch.nn.functional.cross_entropy(
        torch.tensor(predictions).float(), torch.tensor(labels).long()
    )

    return {"eval_loss": loss.item()}


def train(config: dict):
    """Main training function."""

    # Set seed for reproducibility
    set_seed(42)

    # Device setup
    use_gpu = config.get("use_gpu", True)
    if use_gpu and torch.cuda.is_available():
        device = torch.device("cuda")
        logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")
        logger.info(
            f"GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB"
        )
    else:
        device = torch.device("cpu")
        logger.info("Using CPU for training")
        # Disable mixed precision on CPU
        config["training"]["fp16"] = False
        config["training"]["bf16"] = False
        config["training"]["gradient_checkpointing"] = False

    # Load tokenizer and model
    model_name = config["model"]["name"]
    logger.info(f"Loading model: {model_name}")

    tokenizer = AutoTokenizer.from_pretrained(
        model_name, trust_remote_code=config["model"]["trust_remote_code"]
    )
    tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=config["model"]["trust_remote_code"],
        torch_dtype=torch.float16
        if config["training"]["fp16"] and use_gpu
        else torch.float32,
    )
    model.to(device)

    # Apply LoRA
    logger.info("Applying LoRA adapters...")
    lora_config = LoraConfig(
        r=config["lora"]["r"],
        lora_alpha=config["lora"]["lora_alpha"],
        target_modules=config["lora"]["target_modules"],
        lora_dropout=config["lora"]["lora_dropout"],
        bias=config["lora"]["bias"],
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Prepare datasets
    train_dataset = prepare_dataset(
        config["training"]["train_file"], tokenizer, config["tokenizer"]["max_length"]
    )
    eval_dataset = (
        prepare_dataset(
            config["training"]["val_file"], tokenizer, config["tokenizer"]["max_length"]
        )
        if os.path.exists(config["training"]["val_file"])
        else None
    )

    # Data collator
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,  # Causal LM, not masked LM
    )

    # Training arguments
    training_args = TrainingArguments(
        output_dir=config["training"]["output_dir"],
        num_train_epochs=config["training"]["num_train_epochs"],
        per_device_train_batch_size=config["training"]["per_device_train_batch_size"],
        per_device_eval_batch_size=config["training"]["per_device_eval_batch_size"],
        gradient_accumulation_steps=config["training"]["gradient_accumulation_steps"],
        optim=config["training"]["optim"],
        learning_rate=config["training"]["learning_rate"],
        weight_decay=config["training"]["weight_decay"],
        warmup_ratio=config["training"]["warmup_ratio"],
        lr_scheduler_type=config["training"]["lr_scheduler_type"],
        logging_steps=config["training"]["logging_steps"],
        save_steps=config["training"]["save_steps"],
        eval_steps=config["training"].get("eval_steps"),
        evaluation_strategy=config["training"]["evaluation_strategy"],
        save_strategy=config["training"]["save_strategy"],
        save_total_limit=config["training"]["save_total_limit"],
        load_best_model_at_end=config["training"]["load_best_model_at_end"],
        metric_for_best_model=config["training"]["metric_for_best_model"],
        greater_is_better=config["training"]["greater_is_better"],
        fp16=config["training"]["fp16"] and use_gpu,
        bf16=config["training"]["bf16"] and use_gpu,
        gradient_checkpointing=config["training"]["gradient_checkpointing"] and use_gpu,
        tf32=config["training"].get("tf32", True) and use_gpu,
        report_to="none",  # Disable wandb/tensorboard for now
        push_to_hub=False,
        remove_unused_columns=False,
    )

    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics if eval_dataset else None,
    )

    # Train
    logger.info("Starting training...")
    train_result = trainer.train()
    metrics = train_result.metrics

    # Log training metrics
    logger.info(f"Training completed. Metrics: {metrics}")

    # Save model
    logger.info(f"Saving model to {config['training']['output_dir']}")
    trainer.save_model(config["training"]["output_dir"])
    tokenizer.save_pretrained(config["training"]["output_dir"])

    # Save training metrics
    output_dir = Path(config["training"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "train_results.txt", "w") as f:
        f.write(json.dumps(metrics, indent=2))

    logger.info("Training complete!")


def main():
    """Entry point."""
    try:
        # Load config
        config_path = Path(__file__).parent / "config.yaml"
        if not config_path.exists():
            logger.error(f"Config file not found: {config_path}")
            sys.exit(1)

        config = load_config(str(config_path))

        # Check for HF token
        if not os.getenv("HF_TOKEN"):
            logger.warning(
                "HF_TOKEN environment variable not set. "
                "You may need to authenticate for gated models."
            )

        # Check dataset files exist
        for key in ["train_file", "val_file"]:
            path = Path(config["training"][key])
            if not path.exists():
                logger.error(f"Dataset file not found: {path}")
                logger.error("Please run dataset collection first.")
                sys.exit(1)

        # Create output directory
        output_dir = Path(config["training"]["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        # Run training
        train(config)

    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
