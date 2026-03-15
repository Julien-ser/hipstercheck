import streamlit as st
import streamlit_authenticator as stauth
from github import Github
import os

# Page configuration
st.set_page_config(
    page_title="hipstercheck - AI Code Review", page_icon="🔍", layout="wide"
)

# Load environment variables
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
APP_URL = os.getenv("APP_URL", "http://localhost:8501")

# Validate credentials
if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
    st.error("⚠️ GitHub OAuth credentials not configured!")
    st.markdown("""
    Please set up your GitHub OAuth App:
    1. Go to GitHub Settings → Developer settings → OAuth Apps → New OAuth App
    2. Set **Authorization callback URL** to your app URL (e.g., http://localhost:8501)
    3. Copy **Client ID** and **Client Secret**
    4. Create a `.env` file with:
       ```
       GITHUB_CLIENT_ID=your_client_id
       GITHUB_CLIENT_SECRET=your_client_secret
       APP_URL=your_app_url
       ```
    5. Restart the app
    """)
    st.stop()

# Configure OAuth2 provider
provider = stauth.OAuth2Provider(
    name="GitHub",
    authorize_url="https://github.com/login/oauth/authorize",
    access_token_url="https://github.com/login/oauth/access_token",
    userinfo_endpoint="https://api.github.com/user",
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    scope="repo",  # Access to public and private repos
)

# Initialize session state for OAuth and user data
if "token" not in st.session_state:
    st.session_state.token = None
if "github_user" not in st.session_state:
    st.session_state.github_user = None
if "repos" not in st.session_state:
    st.session_state.repos = None

# Handle OAuth callback
query_params = st.query_params
if "code" in query_params and "state" in query_params:
    with st.spinner("Completing authentication..."):
        try:
            token = stauth.oauth2_callback(
                provider, state=query_params["state"][0], code=query_params["code"][0]
            )
            if token:
                st.session_state.token = token
                # Fetch GitHub user and repositories
                gh = Github(token["access_token"])
                user = gh.get_user()
                st.session_state.github_user = user
                st.session_state.repos = list(user.get_repos())
                # Clear query parameters and rerun
                st.query_params.clear()
                st.rerun()
            else:
                st.error("❌ Authentication failed. Please try again.")
                st.stop()
        except Exception as e:
            st.error(f"❌ Authentication error: {str(e)}")
            st.stop()

# Main app logic
if st.session_state.token and st.session_state.github_user:
    user = st.session_state.github_user
    repos = st.session_state.repos

    # Header with user info
    col1, col2 = st.columns([1, 4])
    with col1:
        st.image(user.avatar_url, width=100)
    with col2:
        st.title(f"👋 Welcome, {user.login}!")
        st.markdown(f"**Name:** {user.name or 'N/A'}  \n**Bio:** {user.bio or 'N/A'}")
    st.markdown("---")

    # Display connected repositories
    st.header("📚 Your GitHub Repositories")
    if repos:
        st.markdown(f"**Total repositories:** {len(repos)}")
        # Filter options
        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            sort_by = st.selectbox("Sort by", ["Name", "Stars", "Updated"], index=2)
        with col_filter2:
            repo_type = st.selectbox("Type", ["All", "Public", "Private"], index=0)

        # Apply filters
        filtered_repos = repos.copy()
        if repo_type == "Public":
            filtered_repos = [r for r in filtered_repos if not r.private]
        elif repo_type == "Private":
            filtered_repos = [r for r in filtered_repos if r.private]

        if sort_by == "Stars":
            filtered_repos.sort(key=lambda r: r.stargazers_count, reverse=True)
        elif sort_by == "Name":
            filtered_repos.sort(key=lambda r: r.name.lower())
        elif sort_by == "Updated":
            filtered_repos.sort(key=lambda r: r.updated_at, reverse=True)

        # Display repos in a table
        repo_data = []
        for repo in filtered_repos[:50]:  # Limit display
            repo_data.append(
                {
                    "Name": repo.full_name,
                    "Stars": repo.stargazers_count,
                    "Forks": repo.forks_count,
                    "Language": repo.language or "",
                    "Private": "🔒" if repo.private else "🌍",
                    "Updated": repo.updated_at.strftime("%Y-%m-%d")
                    if repo.updated_at
                    else "",
                }
            )

        if repo_data:
            st.dataframe(
                repo_data,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Name": st.column_config.TextColumn("Repository", width="large"),
                    "Stars": st.column_config.NumberColumn("⭐ Stars", format="%d"),
                    "Forks": st.column_config.NumberColumn("🍴 Forks", format="%d"),
                    "Language": st.column_config.TextColumn("💻 Language"),
                    "Private": st.column_config.TextColumn("Type", width="small"),
                    "Updated": st.column_config.TextColumn("📅 Updated", width="small"),
                },
            )
            st.caption(
                f"Showing {len(repo_data)} of {len(filtered_repos)} repositories"
            )
        else:
            st.info("No repositories match the selected filters.")

        st.markdown("---")
        st.header("🔍 Next: Code Analysis")
        st.markdown("""
        Select a repository above, then choose files to analyze:
        1. Pick a repository from the table
        2. Select specific files or scan the entire repo
        3. Click **Analyze Code** to get AI-powered review
        """)
        # Placeholder for analysis UI (Phase 3)
        st.info("🚧 Code analysis feature coming in Phase 3!")

    else:
        st.info(
            "You don't have any repositories yet or they are not accessible with the current OAuth scope."
        )

    # Logout button
    st.markdown("---")
    if st.button("🚪 Logout", type="secondary"):
        st.session_state.clear()
        st.rerun()

else:
    # Landing page for unauthenticated users
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
    """)

    st.markdown("---")
    st.header("🔐 Sign in with GitHub")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        # Generate OAuth authorization URL
        redirect_uri = APP_URL
        try:
            auth_url = stauth.get_authorize_url(provider, redirect_uri)
            st.link_button("🔗 Login with GitHub", auth_url, use_container_width=True)
        except Exception as e:
            st.error(f"Failed to generate auth URL: {e}")
            st.stop()

    st.markdown("---")
    st.caption("hipstercheck v0.1.0 | AI Code Review Tool")
