import streamlit as st
import streamlit_authenticator as stauth
from github import Github
import os
import requests
import json
import logging
from repo_scanner import RepoScanner

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="hipstercheck - AI Code Review", page_icon="🔍", layout="wide"
)

# Load environment variables
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
APP_URL = os.getenv("APP_URL", "http://localhost:8501")
API_URL = os.getenv("API_URL", "http://localhost:8000")

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
if "repo_scanner" not in st.session_state:
    st.session_state.repo_scanner = None
if "scan_result" not in st.session_state:
    st.session_state.scan_result = None
if "selected_files" not in st.session_state:
    st.session_state.selected_files = []
if "selected_repo" not in st.session_state:
    st.session_state.selected_repo = None
if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = None
if "analysis_error" not in st.session_state:
    st.session_state.analysis_error = None


def fetch_file_content_from_github(
    github_token: str, repo_full_name: str, file_path: str
) -> str:
    """
    Fetch file content from GitHub using the API.

    Args:
        github_token: GitHub OAuth token
        repo_full_name: Repository full name (e.g., "user/repo")
        file_path: Path to file within repository

    Returns:
        File content as string, or None if failed
    """
    try:
        gh = Github(github_token)
        repo = gh.get_repo(repo_full_name)
        file_content = repo.get_contents(file_path)
        # Check if it's a file (not a directory)
        if isinstance(file_content, list):
            return None
        return file_content.decoded_content.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to fetch {file_path}: {e}")
        return None


def analyze_files_with_api(code_snippets, api_url):
    """
    Send code snippets to FastAPI backend for analysis.

    Args:
        code_snippets: List of dicts with keys: code, language, filename
        api_url: FastAPI backend URL

    Returns:
        Tuple of (list of analysis results, cache_hits count) or (None, 0) if error occurred
    """
    try:
        # Send batch request
        response = requests.post(
            f"{api_url.rstrip('/')}/analyze/batch",
            json={"code_snippets": code_snippets},
            timeout=30,  # Allow up to 30s for batch processing
        )

        if response.status_code == 200:
            result = response.json()
            if "results" in result:
                cache_hits = result.get("cache_hits", 0)
                return result["results"], cache_hits
            else:
                st.error(f"Unexpected response format: {result}")
                return None, 0
        else:
            st.error(f"API request failed: {response.status_code} - {response.text}")
            return None, 0

    except requests.exceptions.RequestException as e:
        st.error(f"Failed to connect to API backend: {str(e)}")
        st.info(f"Make sure the FastAPI backend is running at {api_url}")
        return None, 0
    except Exception as e:
        st.error(f"Analysis failed: {str(e)}")
        return None, 0


def display_analysis_results(analysis_results):
    """Display analysis results in expanders with color-coded severity."""
    st.markdown("---")
    st.header("📋 Code Review Results")

    # Summary metrics
    total_reviews = len(analysis_results)
    high_count = sum(1 for r in analysis_results if r.get("severity") == "high")
    medium_count = sum(1 for r in analysis_results if r.get("severity") == "medium")
    low_count = sum(1 for r in analysis_results if r.get("severity") in ["low", "info"])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Reviews", total_reviews)
    with col2:
        st.metric("🟡 High", high_count, delta_color="inverse")
    with col3:
        st.metric("🔵 Medium", medium_count)
    with col4:
        st.metric("🟢 Low/Info", low_count)

    st.markdown("---")

    # Display individual results in expanders
    for idx, review in enumerate(analysis_results):
        file_path = review.get("file_path", "Unknown file")
        severity = review.get("severity", "unknown")
        category = review.get("category", "unknown")
        suggestion = review.get("suggestion", "No suggestion")
        explanation = review.get("explanation", "No explanation")
        line_number = review.get("line_number", 0)
        code_example = review.get("code_example")

        # Determine color based on severity
        if severity == "high":
            label_color = "🟡"  # Yellow for high
            expander_color = "yellow"
        elif severity == "medium":
            label_color = "🔵"
            expander_color = "blue"
        elif severity in ["low", "info"]:
            label_color = "🟢"
            expander_color = "green"
        else:
            label_color = "⚪"
            expander_color = "gray"

        # Create expander with file name and severity
        expander_title = (
            f"{label_color} {file_path} (Line {line_number}) - {severity.upper()}"
        )
        with st.expander(expander_title, expanded=False):
            st.markdown(f"**Category:** `{category}`")
            st.markdown(f"**Suggestion:** {suggestion}")
            st.markdown("**Explanation:**")
            st.markdown(f"> {explanation}")
            if code_example:
                st.markdown("**Code Example:**")
                st.code(
                    code_example,
                    language=file_path.split(".")[-1] if "." in file_path else "python",
                )
            st.caption(f"File: `{file_path}`")


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
                # Initialize repo scanner
                st.session_state.repo_scanner = RepoScanner(token["access_token"])
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
            st.markdown(
                f"**Name:** {user.name or 'N/A'}  \n**Bio:** {user.bio or 'N/A'}"
            )
        st.markdown("---")

        # Cache and rate limit status
        if st.session_state.repo_scanner:
            scan_stats = st.session_state.repo_scanner.get_cache_stats()
        else:
            scan_stats = {"memory_cache_size": 0, "backend": "none"}

        # Fetch review cache stats
        review_stats = None
        try:
            cache_resp = requests.get(
                f"{API_URL.rstrip('/')}/cache/stats", timeout=2
            )
            if cache_resp.status_code == 200:
                review_stats = cache_resp.json()
        except:
            pass

        # Display stats in columns
        col1, col2, col3, col4 = st.columns([1, 2, 2, 2])
        with col1:
            if st.button("🔄 Refresh", type="secondary", use_container_width=True):
                st.rerun()
        with col2:
            if st.session_state.repo_scanner:
                backend = scan_stats.get("backend", "unknown")
                total = scan_stats.get("total_cached", 0)
                if backend == "redis+memory":
                    st.success(f"✅ Scan Cache: {total} entries (Redis+Memory)")
                elif backend == "memory":
                    st.info(f"⚠️ Scan Cache: {total} entries (Memory)")
                else:
                    st.warning("⚠️ Scan Cache: Offline")
        with col3:
            if review_stats:
                hit_rate = review_stats.get("hit_rate_pct", 0)
                backend = review_stats.get("backend", "unknown")
                st.success(f"✅ Review Cache: {hit_rate}% hits ({backend})")
            else:
                st.warning("⚠️ Review Cache: Offline")
        with col4:
            if st.button("🗑️ Clear All Cache", type="secondary", use_container_width=True):
                # Clear scan cache
                if st.session_state.repo_scanner:
                    st.session_state.repo_scanner._cache.clear()
                    try:
                        if (
                            st.session_state.repo_scanner.use_redis
                            and st.session_state.repo_scanner.redis_client
                        ):
                            st.session_state.repo_scanner.redis_client.flushdb()
                    except:
                        pass
                # Clear review cache
                try:
                    requests.post(f"{API_URL.rstrip('/')}/cache/clear", timeout=2)
                except:
                    pass
                st.success("All caches cleared!")
                st.rerun()

        # Detailed cache statistics in expander
        with st.expander("📊 Detailed Cache Statistics", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Scan Cache**")
                if st.session_state.repo_scanner:
                    st.write(f"- Backend: {scan_stats.get('backend', 'N/A')}")
                    st.write(f"- Total cached repos: {scan_stats.get('total_cached', 0)}")
                    st.write(f"- Memory entries: {scan_stats.get('memory_cache_size', 0)}")
                    if scan_stats.get('redis_cache_size') is not None:
                        st.write(f"- Redis entries: {scan_stats.get('redis_cache_size', 0)}")
                else:
                    st.write("- Not available")
            with col2:
                st.markdown("**Review Cache**")
                if review_stats:
                    st.write(f"- Backend: {review_stats.get('backend', 'N/A')}")
                    st.write(f"- Total requests: {review_stats.get('total_requests', 0)}")
                    st.write(f"- Hits: {review_stats.get('hits', 0)}")
                    st.write(f"- Misses: {review_stats.get('misses', 0)}")
                    st.write(f"- Hit rate: {review_stats.get('hit_rate_pct', 0)}%")
                    st.write(f"- Memory entries: {review_stats.get('memory_cache_size', 0)}")
                else:
                    st.write("- Not available")
        with col2:
            if (
                st.session_state.repo_scanner
                and st.session_state.repo_scanner.use_redis
            ):
                st.success("✅ Redis Scan Cache")
            else:
                st.info("⚠️ Memory Scan Cache")
        with col3:
            # Show review cache status if available
            try:
                cache_resp = requests.get(
                    f"{API_URL.rstrip('/')}/cache/stats", timeout=2
                )
                if cache_resp.status_code == 200:
                    cache_data = cache_resp.json()
                    hit_rate = cache_data.get("hit_rate_pct", 0)
                    backend = cache_data.get("backend", "unknown")
                    st.success(f"✅ Review Cache: {hit_rate}% hits ({backend})")
                else:
                    st.warning("⚠️ Review Cache: N/A")
            except:
                st.warning("⚠️ Review Cache: Offline")
        with col4:
            if st.button(
                "🗑️ Clear All Cache", type="secondary", use_container_width=True
            ):
                # Clear scan cache
                if st.session_state.repo_scanner:
                    st.session_state.repo_scanner._cache.clear()
                    try:
                        if (
                            st.session_state.repo_scanner.use_redis
                            and st.session_state.repo_scanner.redis_client
                        ):
                            st.session_state.repo_scanner.redis_client.flushdb()
                    except:
                        pass
                # Clear review cache
                try:
                    requests.post(f"{API_URL.rstrip('/')}/cache/clear", timeout=2)
                except:
                    pass
                st.success("All caches cleared!")
                st.rerun()

    # Display GitHub API rate limit
    if st.session_state.repo_scanner:
        rate_info = st.session_state.repo_scanner.check_rate_limit()
        if "error" not in rate_info:
            remaining = rate_info.get("remaining", 0)
            limit = rate_info.get("limit", 0)
            pct = (remaining / limit * 100) if limit > 0 else 0

            if pct < 20:
                st.error(
                    f"⚠️ GitHub API: {remaining}/{limit} requests remaining ({pct:.1f}%)"
                )
            elif pct < 50:
                st.warning(
                    f"⚠️ GitHub API: {remaining}/{limit} requests remaining ({pct:.1f}%)"
                )
            else:
                st.info(
                    f"✅ GitHub API: {remaining}/{limit} requests remaining ({pct:.1f}%)"
                )

            if rate_info.get("reset_time"):
                from datetime import datetime

                reset_dt = datetime.fromisoformat(rate_info["reset_time"])
                st.caption(f"Resets at: {reset_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            st.error(f"Rate limit check failed: {rate_info['error']}")

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
        st.header("🔍 Repository Scanner")
        st.markdown("""
        Select a repository to scan and analyze files:
        1. Pick a repository from above
        2. Click **Scan Repository** to extract file tree
        3. Select specific files for analysis
        4. Click **Analyze Selected Files** for AI-powered review
        """)

        # Repository selection for scanning
        if repos:
            # Create list of repo full names for selectbox
            repo_options = [r.full_name for r in repos]
            selected_repo = st.selectbox(
                "Select repository to scan",
                options=repo_options,
                index=None,
                placeholder="Choose a repository...",
                key="repo_select",
            )

                if selected_repo:
                    st.session_state.selected_repo = selected_repo

                    col_scan1, col_scan2, col_scan3 = st.columns([2, 1, 1])
                    with col_scan1:
                        scan_button = st.button(
                            "🔍 Scan Repository", type="primary", use_container_width=True
                        )
                    with col_scan2:
                        if st.button("🔄 Re-Scan", use_container_width=True, type="secondary"):
                            # Force fresh scan by invalidating cache first
                            if st.session_state.repo_scanner:
                                st.session_state.repo_scanner.invalidate_cache(selected_repo)
                                st.session_state.scan_result = None
                            st.rerun()
                    with col_scan3:
                        if st.button("🗑️ Clear Scan", use_container_width=True):
                            st.session_state.scan_result = None
                            st.session_state.selected_files = []
                            st.session_state.analysis_results = None
                            st.session_state.analysis_error = None
                            st.rerun()

                if scan_button or st.session_state.scan_result:
                    # Show progress during scan
                    with st.spinner(f"Scanning {selected_repo}..."):
                        try:
                            if scan_button or not st.session_state.scan_result:
                                # Perform the scan
                                progress_bar = st.progress(
                                    0, text="Initializing scan..."
                                )

                                def progress_callback(repo_name, current, total):
                                    pct = (
                                        int((current / total) * 100) if total > 0 else 0
                                    )
                                    progress_bar.progress(
                                        pct, text=f"Scanning files: {current}/{total}"
                                    )

                                # Execute scan
                                scan_result = (
                                    st.session_state.repo_scanner.scan_repository(
                                        selected_repo,
                                        progress_callback=progress_callback,
                                    )
                                )
                                st.session_state.scan_result = scan_result
                                progress_bar.empty()

                            # Display scan results
                            result = st.session_state.scan_result
                            st.success(
                                f"✅ Scan complete! Found {result['total_files']} files ({result['supported_files']} supported)"
                            )

                            # Summary metrics
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Total Files", result["total_files"])
                            with col2:
                                st.metric("Supported Files", result["supported_files"])
                            with col3:
                                coverage = (
                                    (
                                        result["supported_files"]
                                        / result["total_files"]
                                        * 100
                                    )
                                    if result["total_files"] > 0
                                    else 0
                                )
                                st.metric("Coverage", f"{coverage:.1f}%")

                            # File tree display
                            st.markdown("---")
                            st.subheader("📁 File Tree")

                            # Filter options
                            col_filter1, col_filter2 = st.columns(2)
                            with col_filter1:
                                show_only_supported = st.checkbox(
                                    "Show only supported files", value=True
                                )
                            with col_filter2:
                                search_filter = st.text_input(
                                    "🔎 Search files", placeholder="Filter by name..."
                                )

                            # Filter files
                            file_tree = result["file_tree"]
                            if show_only_supported:
                                file_tree = [f for f in file_tree if f["is_supported"]]

                            if search_filter:
                                search_lower = search_filter.lower()
                                file_tree = [
                                    f
                                    for f in file_tree
                                    if search_lower in f["path"].lower()
                                ]

                            # Create dataframe for display
                            if file_tree:
                                file_data = []
                                for f in file_tree:
                                    file_data.append(
                                        {
                                            "Select": False,
                                            "Path": f["path"],
                                            "Name": f["name"],
                                            "Language": f["language"] or "Other",
                                            "Size (KB)": f["size"] / 1024,
                                        }
                                    )

                                # Use data_editor for selection
                                edited_df = st.data_editor(
                                    file_data,
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config={
                                        "Select": st.column_config.CheckboxColumn(
                                            "✓", width="small"
                                        ),
                                        "Path": st.column_config.TextColumn(
                                            "File Path", width="large"
                                        ),
                                        "Name": st.column_config.TextColumn(
                                            "Name", width="medium"
                                        ),
                                        "Language": st.column_config.TextColumn(
                                            "Language", width="medium"
                                        ),
                                        "Size (KB)": st.column_config.NumberColumn(
                                            "Size (KB)", format="%.1f", width="small"
                                        ),
                                    },
                                    disabled=["Path", "Name", "Language", "Size (KB)"],
                                    key="file_editor",
                                )

                                # Update selected files
                                selected_files = []
                                if "Select" in edited_df.columns:
                                    for idx, row in edited_df.iterrows():
                                        if row["Select"]:
                                            # Find original file info
                                            original_file = next(
                                                (
                                                    f
                                                    for f in result["file_tree"]
                                                    if f["path"] == row["Path"]
                                                ),
                                                None,
                                            )
                                            if original_file:
                                                selected_files.append(original_file)

                                st.session_state.selected_files = selected_files

                                # Display selection info
                                if len(selected_files) > 0:
                                    st.info(
                                        f"📌 Selected {len(selected_files)} files for analysis"
                                    )

                                # Analyze button
                                if st.button(
                                    "🚀 Analyze Selected Files",
                                    type="primary",
                                    use_container_width=True,
                                ):
                                    with st.spinner(
                                        "Fetching file contents from GitHub..."
                                    ):
                                        # Fetch code content for each selected file
                                        code_snippets = []
                                        github_token = st.session_state.token[
                                            "access_token"
                                        ]
                                        selected_repo = st.session_state.selected_repo

                                        for (
                                            file_info
                                        ) in st.session_state.selected_files:
                                            file_path = file_info["path"]
                                            file_language = file_info.get(
                                                "language", "Python"
                                            )

                                            # Fetch file content from GitHub
                                            content = fetch_file_content_from_github(
                                                github_token, selected_repo, file_path
                                            )

                                            if content is not None:
                                                code_snippets.append(
                                                    {
                                                        "code": content,
                                                        "language": file_language,
                                                        "filename": file_path,
                                                    }
                                                )
                                            else:
                                                st.warning(
                                                    f"⚠️ Could not fetch content for {file_path}"
                                                )

                                        if not code_snippets:
                                            st.error(
                                                "❌ No file content could be fetched. Please try again."
                                            )
                                            st.stop()

                                        st.info(
                                            f"📦 Prepared {len(code_snippets)} files for analysis"
                                        )

                                    with st.spinner("Analyzing files with AI..."):
                                        # Call FastAPI backend with actual code content
                                        response = analyze_files_with_api(
                                            code_snippets, API_URL
                                        )

                                        if response:
                                            # Map results back to files using index
                                            enriched_results = []
                                            for result in response:
                                                idx = result.get("index", 0)
                                                review = result.get("review", {})

                                                # Add file information from our code_snippets
                                                if idx < len(code_snippets):
                                                    snippet = code_snippets[idx]
                                                    review["file_path"] = snippet[
                                                        "filename"
                                                    ]

                                                enriched_results.append(review)

                                            st.session_state.analysis_results = (
                                                enriched_results
                                            )
                                            st.session_state.analysis_error = None
                                            st.success(
                                                f"✅ Analysis complete! Found {len(enriched_results)} reviews."
                                            )
                                        else:
                                            st.session_state.analysis_results = None
                                            st.session_state.analysis_error = True
                                        st.rerun()

                                # Display analysis results if available
                                if st.session_state.analysis_results:
                                    st.markdown("---")
                                    st.header("📋 Code Review Results")

                                    # Summary metrics
                                    total_reviews = len(
                                        st.session_state.analysis_results
                                    )
                                    high_count = sum(
                                        1
                                        for r in st.session_state.analysis_results
                                        if r.get("severity") == "high"
                                    )
                                    medium_count = sum(
                                        1
                                        for r in st.session_state.analysis_results
                                        if r.get("severity") == "medium"
                                    )
                                    low_count = sum(
                                        1
                                        for r in st.session_state.analysis_results
                                        if r.get("severity") in ["low", "info"]
                                    )

                                    col1, col2, col3, col4 = st.columns(4)
                                    with col1:
                                        st.metric("Total Reviews", total_reviews)
                                    with col2:
                                        st.metric(
                                            "🟡 High", high_count, delta_color="inverse"
                                        )
                                    with col3:
                                        st.metric("🔵 Medium", medium_count)
                                    with col4:
                                        st.metric("🟢 Low/Info", low_count)

                                    st.markdown("---")

                                    # Display individual results in expanders
                                    for idx, review in enumerate(
                                        st.session_state.analysis_results
                                    ):
                                        file_path = review.get(
                                            "file_path", "Unknown file"
                                        )
                                        severity = review.get("severity", "unknown")
                                        category = review.get("category", "unknown")
                                        suggestion = review.get(
                                            "suggestion", "No suggestion"
                                        )
                                        explanation = review.get(
                                            "explanation", "No explanation"
                                        )
                                        line_number = review.get("line_number", 0)
                                        code_example = review.get("code_example")

                                        # Determine color based on severity
                                        if severity == "high":
                                            label_color = "🟡"
                                            expander_color = "red"
                                        elif severity == "medium":
                                            label_color = "🔵"
                                            expander_color = "blue"
                                        elif severity in ["low", "info"]:
                                            label_color = "🟢"
                                            expander_color = "green"
                                        else:
                                            label_color = "⚪"
                                            expander_color = "gray"

                                        # Create expander with file name and severity
                                        expander_title = f"{label_color} {file_path} (Line {line_number}) - {severity.upper()}"
                                        with st.expander(
                                            expander_title, expanded=False
                                        ):
                                            st.markdown(f"**Category:** `{category}`")
                                            st.markdown(f"**Suggestion:** {suggestion}")
                                            st.markdown("**Explanation:**")
                                            st.markdown(f"> {explanation}")
                                            if code_example:
                                                st.markdown("**Code Example:**")
                                                st.code(
                                                    code_example,
                                                    language=file_path.split(".")[-1]
                                                    if "." in file_path
                                                    else "python",
                                                )
                                            st.caption(f"File: `{file_path}`")

                                elif st.session_state.analysis_error:
                                    st.error(
                                        "❌ Analysis failed. Please try again or check the backend connection."
                                    )
                                else:
                                    st.caption(
                                        "Select files by checking the boxes above"
                                    )
                            else:
                                st.warning("No files match the current filters")

                        except Exception as e:
                            st.error(f"❌ Scan failed: {str(e)}")
                            st.exception(e)
                else:
                    st.info(
                        "👆 Select a repository and click **Scan Repository** to begin"
                    )
            else:
                st.info("📋 Please select a repository from the dropdown above")
        else:
            st.warning("No repositories available to scan")

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
    st.header("🛠️ Quick Demo")
    st.markdown("""
    Try a quick code review before signing in:
    1. Upload a file or paste code below
    2. Select language if pasting
    3. Click **Analyze** to see AI-powered feedback
    """)

    demo_method = st.radio(
        "Input method",
        ["Upload File", "Paste Code"],
        horizontal=True,
        key="demo_method",
    )
    demo_snippets = []

    if demo_method == "Upload File":
        demo_uploaded = st.file_uploader(
            "Upload a code file",
            type=[
                "py",
                "js",
                "ts",
                "java",
                "c",
                "cpp",
                "yaml",
                "txt",
                "ipynb",
                "launch",
                "msg",
            ],
            accept_multiple_files=False,
            key="demo_uploader",
        )
        if demo_uploaded:
            content = demo_uploaded.getvalue().decode("utf-8")
            ext = (
                demo_uploaded.name.split(".")[-1].lower()
                if "." in demo_uploaded.name
                else ""
            )
            # Simple language mapping
            lang_map = {
                "py": "python",
                "js": "javascript",
                "ts": "typescript",
                "java": "java",
                "c": "c",
                "cpp": "cpp",
                "h": "c",
                "hpp": "cpp",
                "yaml": "yaml",
                "yml": "yaml",
                "ipynb": "python",
                "launch": "ros2",
                "msg": "ros2",
                "txt": "text",
            }
            language = lang_map.get(ext, "text")
            demo_snippets.append(
                {"code": content, "language": language, "filename": demo_uploaded.name}
            )
            st.info(f"Loaded: {demo_uploaded.name}")
    else:
        demo_language = st.selectbox(
            "Language",
            [
                "python",
                "javascript",
                "typescript",
                "java",
                "c",
                "cpp",
                "yaml",
                "ros2",
                "text",
            ],
            key="demo_language",
        )
        demo_code = st.text_area("Paste your code", height=300, key="demo_code")
        if demo_code.strip():
            demo_snippets.append(
                {
                    "code": demo_code,
                    "language": demo_language,
                    "filename": "pasted_code",
                }
            )

    if demo_snippets and st.button(
        "🚀 Analyze Demo", type="primary", key="demo_analyze"
    ):
        with st.spinner("Analyzing..."):
            results = analyze_files_with_api(demo_snippets, API_URL)
            if results:
                st.session_state.demo_analysis_results = results
                st.session_state.demo_analysis_error = None
                st.success(f"✅ Analysis complete! Found {len(results)} reviews.")
            else:
                st.session_state.demo_analysis_error = True
        st.rerun()

    if st.session_state.get("demo_analysis_results"):
        st.markdown("---")
        display_analysis_results(st.session_state.demo_analysis_results)
    elif st.session_state.get("demo_analysis_error"):
        st.error(
            "❌ Analysis failed. Please try again or check the backend connection."
        )

    # Separator before sign-in
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
