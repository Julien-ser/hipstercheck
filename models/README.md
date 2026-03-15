# Phi-2 Model Selection Rationale

## Selected Model: Microsoft Phi-2

**Model ID**: `microsoft/phi-2`  
**Size**: 2.7 billion parameters  
**Type**: Transformer-based language model  
**License**: MIT

## Why Phi-2?

### 1. **Lightweight & Cost-Effective**
- Only 2.7B parameters (vs CodeLlama-7b's 7B, StarCoder's 15.5B)
- ~5GB memory footprint in FP16
- Can run inference on CPU (with quantization) or modest GPU (e.g., T4, RTX 3060+)
- Fast inference times (<100ms per code snippet on modern hardware)

### 2. **Excellent Code Understanding**
- Trained on synthetic academic data + code corpus
- Strong performance on code generation and analysis benchmarks
- Outperforms models 5x its size on reasoning tasks
- Can be fine-tuned effectively with LoRA for specific tasks

### 3. **Deployment Flexibility**
- Quantized versions available (GPTQ, AWQ) for CPU inference
- Compatible with Hugging Face ecosystem
- Works with Vercel's GPU instances and CPU fallback
- Low latency for <60s analysis requirement

### 4. **Commercial Use**
- MIT license - fully permissive for SaaS product
- No usage restrictions or API fees

## Fine-Tuning Strategy

### Approach: LoRA (Low-Rank Adaptation)
- **Rationale**: Parameter-efficient, fast to train, minimal storage overhead
- **Target modules**: Attention Q, K, V, and Dense layers
- **Rank (r)**: 16 (balance between capacity and efficiency)
- **Alpha**: 32 (typically 2x rank)
- **Dropout**: 0.1 to prevent overfitting

### Training Configuration
- **Epochs**: 3-5 (code review dataset is relatively small)
- **Batch size**: 8-16 (adjust based on GPU memory)
- **Learning rate**: 2e-4 (LoRA-specific optimal range)
- **Optimizer**: AdamW with 0.01 weight decay
- **Scheduler**: Cosine with warmup (10% of steps)
- **Mixed precision**: FP16 (GPU) or BF16 (if supported)

### Hardware Requirements

#### GPU Training (Recommended)
- **Minimum**: NVIDIA T4 (16GB) or RTX 3060 (12GB)
- **Optimal**: NVIDIA A10 (24GB) or RTX 4090 (24GB)
- **Estimated time**: 2-4 hours on T4 for 3 epochs
- **Platform options**:
  - Google Colab Pro (T4/2xT4)
  - Vercel Pro GPU (A10)
  - RunPod/Hugging Face Spaces

#### CPU Training (Fallback)
- **RAM**: 32GB+ (for full precision) or 16GB with quantization
- **Estimated time**: 12-24 hours depending on CPU
- **Use case**: Development, small datasets (<1000 samples)

## Input Format

We'll use a structured prompt template for code review:

```
[INST] <<SYS>>
You are an expert code reviewer. Analyze the following code for:
1. Bugs and potential errors
2. Performance optimizations
3. Best practice violations
4. Security issues

Output format (JSON):
{
  "severity": "high|medium|low",
  "line_number": <line number or null>,
  "category": "bug|optimization|style|security",
  "suggestion": "<concise fix>",
  "explanation": "<detailed reasoning>"
}
<</SYS>>

Code file: {filename}
Language: {language}

{code}

Analyze the code above and provide your review. [/INST]
```

## File Structure

```
models/
├── README.md                 # This file
├── config.yaml              # Training configuration
├── train.py                 # Fine-tuning script
├── inference.py             # Inference wrapper for FastAPI
├── prompts/
│   ├── python.txt          # Python-specific prompts
│   ├── ros2.txt            # ROS2-specific prompts
│   └── ml.txt              # ML framework prompts
├── checkpoints/            # LoRA weights (gitignored)
│   └── phi2-code-review/
└── tests/
    └── test_inference.py   # Model inference tests
```

## Next Steps

1. Prepare dataset from `dataset/split_train.jsonl`
2. Run fine-tuning with `python models/train.py`
3. Validate on `dataset/split_val.jsonl`
4. Deploy LoRA weights to production
5. Integrate with FastAPI backend

## References

- Phi-2 Hugging Face: https://huggingface.co/microsoft/phi-2
- Phi-2 Paper: https://arxiv.org/abs/2309.05408
- LoRA Paper: https://arxiv.org/abs/2106.09685
- PEFT Documentation: https://huggingface.co/docs/peft
