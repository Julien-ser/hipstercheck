# hipstercheck

**AI-Powered Code Review for Indie Developers**

hipstercheck is an AI-powered code review tool that scans GitHub repositories for bugs, optimization suggestions, and best practices. Built for solo coders and small teams working with Python, ROS2, or ML frameworks, it delivers comprehensive reviews in under 60 seconds through a simple web interface.

## Key Features

- 🔍 **Smart Code Analysis**: Detect bugs, performance issues, and style violations
- 🤖 **AI-Powered Reviews**: Fine-tuned open-source LLM for accurate suggestions
- 🚀 **GitHub Integration**: Seamless OAuth and repository scanning
- 📝 **Manual Upload & Paste**: Try the Quick Demo on the landing page - upload files or paste code snippets directly without GitHub login
- ⚡ **Fast Results**: Analysis completed in under 60 seconds
- 💰 **Affordable**: $10/month per user with free tier (1 repo scan/week)
- 🎯 **Specialized Support**: Python (PEP8), ROS2 best practices, ML frameworks (PyTorch, TensorFlow, scikit-learn)

## Quick Start

### Prerequisites

- Python 3.9+
- Git
- GitHub account (for OAuth)
- Hugging Face account (for AI model, Phase 2)

### 1. Configure GitHub OAuth App

Before running the app, you need to create a GitHub OAuth App:

1. Go to [GitHub Developer Settings → OAuth Apps → New OAuth App](https://github.com/settings/developers)
2. Fill in:
   - **Application name**: hipstercheck (or your preferred name)
   - **Homepage URL**: `http://localhost:8501` (or your deployed URL)
   - **Authorization callback URL**: `http://localhost:8501` (or your deployed URL)
3. Click "Register application"
4. Copy the **Client ID** (generate a new client secret)
5. Create a `.env` file from `.env.example` and add your credentials:
   ```bash
   cp .env.example .env
   ```
 6. Edit `.env`:
    ```bash
    GITHUB_CLIENT_ID=your_client_id
    GITHUB_CLIENT_SECRET=your_client_secret
    APP_URL=http://localhost:8501
    API_URL=http://localhost:8000
    ```
    *(Note: `APP_URL` must match the callback URL from step 2)*
    *(Note: `API_URL` points to the FastAPI backend - start it with `python api.py`)*

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. (Optional) Configure Redis for Caching

To enable persistent caching across app restarts and multiple users:

1. Install and run Redis:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install redis-server
   sudo systemctl start redis
   
   # macOS
   brew install redis
   brew services start redis
   
   # Docker
   docker run -p 6379:6379 redis:alpine
   ```

2. Add to your `.env`:
   ```bash
   REDIS_URL=redis://localhost:6379/0
   ```

   If Redis is not available, the app will fall back to in-memory caching.

### 6. (Optional) Configure Rate Limit Buffer

The app automatically monitors GitHub API rate limits and will wait when approaching the limit. You can adjust the buffer:

```bash
RATE_LIMIT_BUFFER=10
```

This sets how many remaining requests trigger a wait before the reset time.

```bash
streamlit run streamlit_app.py
```

### 3. (Optional) Run FastAPI Backend

The FastAPI microservice provides the code analysis endpoint. To run it separately:

```bash
# Start the API server
python api.py

# Or with uvicorn directly
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000` with:
- `GET /health` - Health check endpoint
- `POST /analyze` - Analyze single code snippet (5s timeout)
- `POST /analyze/batch` - Analyze multiple snippets (max 50)

### 4. Authenticate & Use

1. Click **"Login with GitHub"** in the app
2. Authorize the OAuth app on GitHub
3. View your repositories in the dashboard
4. (Future) Select a repo to analyze code

## Project Structure

```
hipstercheck/
├── api.py                    # FastAPI microservice (Phase 3)
├── streamlit_app.py          # Main Streamlit frontend
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables (create from .env.example)
├── dataset/                  # Code review dataset collection
│   ├── data_collector.py    # Dataset collection script
│   ├── code_reviews.jsonl   # Combined dataset (generated)
│   ├── split_train.jsonl    # Training split
│   ├── split_val.jsonl      # Validation split
│   ├── split_test.jsonl     # Test split
│   └── README.md            # Dataset documentation
├── models/                  # Fine-tuned AI model
├── prompts/                 # Prompt templates for different languages
├── tests/                   # Unit and integration tests
├── README.md               # This file
└── TASKS.md                # Development task tracking
```

## Development Roadmap

### Phase 1: Foundation & GitHub Integration ✅ In Progress
- [x] Initialize Streamlit project structure
- [x] Implement GitHub OAuth authentication
- [x] Build repo scanning engine
- [ ] Configure GitHub API rate limiting

### Phase 2: Model Training & Code Analysis
- [x] Collect code review dataset
- [x] Select base LLM for fine-tuning
- [x] **Fine-tune model on review generation** ✅ Pipeline implemented and validated. Training script (`models/train.py`) successfully loads Phi-2 with LoRA, prepares dataset, and executes training steps. Smoke test passes. Full training requires GPU for practical speed.
- [x] Create prompt engineering templates

### Selected Model: Microsoft Phi-2

We've selected **microsoft/phi-2** (2.7B parameters) as our base model because it's:
- **Lightweight**: Only 2.7B parameters (vs 7B+ for alternatives)
- **Fast**: <100ms inference on CPU or small GPU
- **Capable**: Excellent code understanding and generation
- **Cost-Effective**: MIT license, runs on modest hardware
- **Deployable**: Works with LoRA for efficient fine-tuning

#### Fine-Tuning Approach
We use **LoRA (Low-Rank Adaptation)** for efficient fine-tuning:
- Trains only 1-2% of parameters
- Minimal storage (LoRA weights ~50-100MB)
- Fast training (2-4 hours on T4 GPU)
- Can run inference without full fine-tuned model

#### Training Resources
- **GPU**: NVIDIA T4 (16GB) or RTX 3060+ (12GB minimum)
- **CPU**: 32GB RAM (slower, for development)
- **Time**: ~3 hours for 3 epochs on T4
- **Platform**: Google Colab Pro, Vercel GPU, or local GPU

#### File Structure
```
models/
├── README.md              # Model selection and setup guide
├── config.yaml            # Training configuration
├── train.py               # Fine-tuning script
├── inference.py           # Inference wrapper for FastAPI
├── prompts/               # Language-specific prompt templates
│   ├── python.txt        # Python/PEP8 review guidelines
│   ├── ros2.txt          # ROS2 best practices
│   └── ml.txt            # ML framework checks (PyTorch, TF, sklearn)
└── tests/
    └── test_inference.py  # Unit tests
```

#### How to Fine-Tune

1. **Install training dependencies** (already in requirements.txt):
   ```bash
   pip install torch transformers peft accelerate datasets
   ```

2. **Prepare dataset** (already collected):
   ```bash
   # Dataset is in dataset/split_*.jsonl
   # Format: {"code": "...", "review": {...}}
   ```

3. **Run training**:
   ```bash
   # With GPU
   python models/train.py

   # With CPU (slow)
   # Edit config.yaml: set use_gpu: false
   # python models/train.py
   ```

4. **Monitor training**:
   - Checkpoints saved to `models/checkpoints/phi2-code-review/`
   - Training logs in console
   - Best model automatically saved

5. **Deploy fine-tuned model**:
   - Set environment variable `MODEL_PATH` to checkpoint directory
   - FastAPI backend will load LoRA weights automatically

#### Prompt Engineering

Each language has specialized prompts in `models/prompts/`:
- **Python**: PEP8, style, common bugs
- **ROS2**: Node lifecycle, QoS, callbacks, launch files
- **ML**: Data leakage, overfitting, reproducibility

These templates ensure consistent, high-quality reviews across all supported languages.

### Phase 3: App Integration & Deployment Prep
- [x] Wrap model in FastAPI microservice
- [x] Integrate model calls into Streamlit
- [ ] Implement result caching
- [ ] Set up Stripe subscription

### Phase 4: Testing, Deployment & Validation
- [ ] Test with personal ROS2/ML projects
- [ ] Deploy backend on Vercel
- [ ] Deploy Streamlit frontend on Vercel
- [ ] Validate via Reddit/Indie Hackers

## Architecture

### Tech Stack
- **Frontend**: Streamlit (responsive UI, rapid prototyping)
- **Backend**: FastAPI (async API, high performance)
- **AI Model**: Phi-2 (2.7B parameters) fine-tuned with LoRA for code review
- **Training**: PyTorch + Hugging Face Transformers + PEFT (LoRA)
- **Database**: SQLite/Redis for caching
- **Deployment**: Vercel (serverless)
- **Payment**: Stripe Checkout

### Data Flow
1. User authenticates via GitHub OAuth
2. Repository files are scanned and parsed
3. AI model analyzes code for issues
4. Results displayed with severity levels and suggestions
5. Cached for future reference

## License

MIT License - see LICENSE file for details

## Contributing

This is a solo project for now. For feedback or collaboration, reach out via GitHub Issues.
