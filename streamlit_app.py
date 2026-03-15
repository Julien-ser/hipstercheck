import streamlit as st

st.set_page_config(
    page_title="hipstercheck - AI Code Review", page_icon="🔍", layout="wide"
)

st.title("🔍 hipstercheck")
st.markdown("### AI-Powered Code Review for Indie Developers")

st.markdown("---")

st.header("🚀 Getting Started")
st.markdown("""
**hipstercheck** analyzes your GitHub repositories for bugs, optimization opportunities, 
and best practices in under 60 seconds.

#### Features:
- ✅ Scan Python, ROS2, and ML framework code
- ✅ AI-powered code review suggestions
- ✅ Supports .py, .launch, .msg, .ipynb, .yaml files
- ✅ Fast analysis with progress tracking

#### Status:
This is the initial setup phase. GitHub integration coming soon!
""")

st.markdown("---")

# Placeholder for future components
col1, col2 = st.columns(2)

with col1:
    st.subheader("📦 Project Setup")
    st.info("Virtual environment configured with Streamlit, FastAPI, and PyGithub")

with col2:
    st.subheader("🔧 Next Steps")
    st.markdown("""
    1. Implement GitHub OAuth
    2. Build repo scanning engine
    3. Integrate AI model
    4. Deploy and validate
    """)

st.markdown("---")
st.caption("hipstercheck v0.1.0 | AI Code Review Tool")
