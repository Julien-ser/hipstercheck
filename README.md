# hipstercheck

**AI-Powered Code Review for Indie Developers**

hipstercheck is an AI-powered code review tool that scans GitHub repositories for bugs, optimization suggestions, and best practices. Built for solo coders and small teams working with Python, ROS2, or ML frameworks, it delivers comprehensive reviews in under 60 seconds through a simple web interface.

## Key Features

- 🔍 **Smart Code Analysis**: Detect bugs, performance issues, and style violations
- 🤖 **AI-Powered Reviews**: Fine-tuned open-source LLM for accurate suggestions
- 🚀 **GitHub Integration**: Seamless OAuth and repository scanning
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
   ```
   *(Note: `APP_URL` must match the callback URL from step 2)*

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the App

```bash
streamlit run streamlit_app.py
```

### 4. Authenticate & Use

1. Click **"Login with GitHub"** in the app
2. Authorize the OAuth app on GitHub
3. View your repositories in the dashboard
4. (Future) Select a repo to analyze code

## Project Structure

```
hipstercheck/
├── streamlit_app.py          # Main Streamlit frontend
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables (create from .env.example)
├── backend/                 # FastAPI microservice (Phase 3)
│   └── main.py
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
- [ ] Collect code review dataset
- [ ] Select base LLM for fine-tuning
- [ ] Fine-tune model on review generation
- [ ] Create prompt engineering templates

### Phase 3: App Integration & Deployment Prep
- [ ] Wrap model in FastAPI microservice
- [ ] Integrate model calls into Streamlit
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
- **AI Model**: Fine-tuned open-source LLM (CodeLlama/StarCoder/Phi-2)
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
