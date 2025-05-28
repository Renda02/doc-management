import os
import asyncio
import pandas as pd
import sqlite3
import json
import streamlit as st
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

# ============================================================================
# CONFIGURATION AND SETUP
# ============================================================================

# Load environment variables
load_dotenv(override=True)

# API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("OpenAI API Key not configured. Please add it to your .env file.")
    st.stop()

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Documentation Repository Configuration
GITHUB_REPO_BASE = "https://raw.githubusercontent.com/Renda02/tech-101-handbook/main"
DOCUMENTATION_URLS = {
    "content_classification_guide": f"{GITHUB_REPO_BASE}/editing-rules/content-classification-guide.md",
    "style_guide": f"{GITHUB_REPO_BASE}/handbook/style-guide.md", 
    "wordiness_examples": f"{GITHUB_REPO_BASE}/editing-rules/examples/wordiness-examples.md",
    "clarity_examples": f"{GITHUB_REPO_BASE}/editing-rules/examples/clarity-vague-language.md",
    "quick_reference": f"{GITHUB_REPO_BASE}/editing-rules/quick-reference.md"
}

# Database Configuration
DB_FILE = os.getenv("DB_FILE", "editorial_reviews.db")

# Cache for documentation content
DOCS_CACHE = {}
CACHE_EXPIRY = 3600  # 1 hour in seconds

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def log_system_message(message):
    """Add a timestamped message to system logs."""
    if 'system_logs' not in st.session_state:
        st.session_state['system_logs'] = []
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state['system_logs'].append(f"[{timestamp}] {message}")

def fetch_documentation(doc_key):
    """Fetch documentation from GitHub with caching."""
    now = datetime.now().timestamp()
    
    # Check cache first
    if doc_key in DOCS_CACHE:
        cache_entry = DOCS_CACHE[doc_key]
        if now - cache_entry["timestamp"] < CACHE_EXPIRY:
            log_system_message(f"DOCS: Using cached {doc_key}")
            return cache_entry["content"]
    
    # Fetch from GitHub
    url = DOCUMENTATION_URLS.get(doc_key)
    if not url:
        log_system_message(f"DOCS: Unknown documentation key: {doc_key}")
        return None
    
    try:
        log_system_message(f"DOCS: Fetching {doc_key} from GitHub")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        content = response.text
        DOCS_CACHE[doc_key] = {
            "content": content,
            "timestamp": now
        }
        
        log_system_message(f"DOCS: Successfully fetched {doc_key}")
        return content
        
    except requests.RequestException as e:
        log_system_message(f"DOCS ERROR: Failed to fetch {doc_key}: {str(e)}")
        return None

def analyze_technical_writing_issues(text):
    """Quick analysis for immediate feedback."""
    issues = []
    
    # Passive voice detection
    passive_patterns = [r'should be\s+\w+ed', r'can be\s+\w+ed', r'will be\s+\w+ed']
    for pattern in passive_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append({
                "type": "Passive Voice",
                "priority": "High",
                "suggestion": "Use active voice in instructions"
            })
    
    # Future tense detection
    if re.search(r'\bwill\s+\w+', text, re.IGNORECASE):
        issues.append({
            "type": "Future Tense",
            "priority": "Medium",
            "suggestion": "Use present tense: 'returns' not 'will return'"
        })
    
    # Wordiness detection
    filler_words = ["actually", "basically", "really", "very"]
    for word in filler_words:
        if re.search(rf'\b{word}\b', text, re.IGNORECASE):
            issues.append({
                "type": "Wordiness",
                "priority": "High", 
                "suggestion": f"Remove unnecessary '{word}'"
            })
    
    # Vague UI references
    if re.search(r'\bthe button\b|\bthe link\b|\bthe field\b', text, re.IGNORECASE):
        issues.append({
            "type": "Vague UI Reference",
            "priority": "High",
            "suggestion": "Specify UI elements: 'the Save button' not 'the button'"
        })
    
    return issues

# ============================================================================
# MULTI-AGENT FUNCTIONS
# ============================================================================

async def run_content_analysis(document_text, doc_metadata):
    """Content Analyzer Agent - analyzes content quality issues."""
    log_system_message("Content Analyzer: Starting analysis")
    
    content_guide = fetch_documentation("content_classification_guide")
    
    system_prompt = f"""
    You are a Content Analyzer Agent specializing in technical documentation quality.

    Focus on identifying:
    1. Wordiness and filler text
    2. Vague language and unclear references  
    3. Missing context and logical gaps
    4. Abstract content lacking visualization
    5. Redundant information
    6. Missing outcomes and value statements

    Content Guide Reference:
    {content_guide[:1500] if content_guide else "Guide not available"}

    Provide specific examples and actionable suggestions.
    """
    
    user_prompt = f"""
    Analyze this {doc_metadata.get('type', 'document')} for content quality issues:
    
    Title: {doc_metadata.get('title', 'Untitled')}
    
    Content:
    {document_text}
    
    Focus on clarity, precision, and reader comprehension.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1000,
            temperature=0.2
        )
        
        analysis = response.choices[0].message.content
        log_system_message("Content Analyzer: Analysis completed")
        return {
            "agent": "Content Analyzer",
            "findings": analysis
        }
        
    except Exception as e:
        log_system_message(f"Content Analyzer: Error - {str(e)}")
        return {"agent": "Content Analyzer", "error": str(e)}

async def run_style_analysis(document_text, doc_metadata):
    """Style Guide Agent - checks style compliance."""
    log_system_message("Style Guide Enforcer: Starting compliance check")
    
    style_guide = fetch_documentation("style_guide")
    
    system_prompt = f"""
    You are a Style Guide Enforcer Agent specializing in technical writing standards.

    Check for:
    1. Active vs passive voice
    2. Present tense usage
    3. Sentence length (max 26 words)
    4. UI element specifications
    5. Capitalization and formatting
    6. Grammar and punctuation

    Style Guide Reference:
    {style_guide[:1500] if style_guide else "Guide not available"}

    Identify specific violations with corrections.
    """
    
    user_prompt = f"""
    Check this {doc_metadata.get('type', 'document')} for style guide compliance:
    
    Title: {doc_metadata.get('title', 'Untitled')}
    
    Content:
    {document_text}
    
    Focus on voice, tense, and formatting standards.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1000,
            temperature=0.1
        )
        
        compliance_check = response.choices[0].message.content
        log_system_message("Style Guide Enforcer: Check completed")
        return {
            "agent": "Style Guide Enforcer",
            "findings": compliance_check
        }
        
    except Exception as e:
        log_system_message(f"Style Guide Enforcer: Error - {str(e)}")
        return {"agent": "Style Guide Enforcer", "error": str(e)}

async def run_editorial_synthesis(document_text, doc_metadata, agent_reports):
    """Senior Editor Agent - synthesizes all agent findings."""
    log_system_message("Senior Editor: Synthesizing review")
    
    system_prompt = """
    You are a Senior Editor Agent coordinating technical documentation review.

    Responsibilities:
    1. Synthesize findings from specialist agents
    2. Prioritize issues by impact
    3. Provide clear, actionable recommendations
    4. Create comprehensive editorial guidance
    5. Ask if user wants a rewritten draft

    Create a professional review combining all specialist insights.
    """
    
    # Combine agent reports
    combined_findings = ""
    for report in agent_reports:
        if "findings" in report:
            combined_findings += f"\n--- {report['agent']} Report ---\n{report['findings']}\n"
        elif "error" in report:
            combined_findings += f"\n--- {report['agent']} ---\nError: {report['error']}\n"
    
    user_prompt = f"""
    Create comprehensive editorial review based on specialist agent reports:
    
    Document: {doc_metadata.get('title', 'Untitled')} ({doc_metadata.get('type', 'Unknown')})
    
    SPECIALIST FINDINGS:
    {combined_findings}
    
    DOCUMENT PREVIEW:
    {document_text[:800]}...
    
    Provide:
    1. Executive summary
    2. Priority issues
    3. Specific improvements
    4. Overall assessment
    5. Ask if user wants rewritten draft
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1500,
            temperature=0.3
        )
        
        editorial_review = response.choices[0].message.content
        log_system_message("Senior Editor: Review completed")
        return {
            "agent": "Senior Editor",
            "review": editorial_review,
            "agent_reports": agent_reports
        }
        
    except Exception as e:
        log_system_message(f"Senior Editor: Error - {str(e)}")
        return {"agent": "Senior Editor", "error": str(e)}

async def run_document_rewrite(original_text, doc_metadata, editorial_guidance):
    """Technical Writer Agent - rewrites document with improvements."""
    log_system_message("Technical Writer: Starting rewrite")
    
    style_guide = fetch_documentation("style_guide")
    content_guide = fetch_documentation("content_classification_guide")
    
    system_prompt = f"""
    You are a Technical Writer Agent specializing in document improvement.

    Rewriting principles:
    1. Apply all style guide standards
    2. Fix content quality issues  
    3. Maintain technical accuracy
    4. Preserve author intent
    5. Ensure logical flow
    6. Optimize for user experience

    Style Guide:
    {style_guide[:800] if style_guide else ""}
    
    Content Rules:
    {content_guide[:800] if content_guide else ""}
    
    Create a polished, professional version.
    """
    
    user_prompt = f"""
    Rewrite this document incorporating editorial feedback:
    
    ORIGINAL:
    {original_text}
    
    EDITORIAL GUIDANCE:
    {editorial_guidance}
    
    Document: {doc_metadata.get('title', 'Untitled')} ({doc_metadata.get('type', 'Unknown')})
    
    Provide complete improved version addressing all issues.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=2500,
            temperature=0.2
        )
        
        rewritten_draft = response.choices[0].message.content
        log_system_message("Technical Writer: Rewrite completed")
        return {
            "agent": "Technical Writer",
            "improved_draft": rewritten_draft
        }
        
    except Exception as e:
        log_system_message(f"Technical Writer: Error - {str(e)}")
        return {"agent": "Technical Writer", "error": str(e)}

async def handle_chat_question(user_question, context=None):
    """Chat Assistant Agent - handles user questions."""
    log_system_message("Chat Assistant: Answering question")
    
    # Fetch relevant docs based on question
    docs_to_fetch = []
    if any(word in user_question.lower() for word in ["style", "format", "voice", "tense"]):
        docs_to_fetch.append("style_guide")
    if any(word in user_question.lower() for word in ["content", "clarity", "wordiness"]):
        docs_to_fetch.append("content_classification_guide")
    
    reference_material = ""
    for doc_key in docs_to_fetch:
        content = fetch_documentation(doc_key)
        if content:
            reference_material += f"{doc_key}: {content[:600]}\n\n"
    
    system_prompt = f"""
    You are a Chat Assistant Agent for technical writers.

    Expertise:
    1. Technical writing principles
    2. Style guide standards
    3. Content improvement techniques
    4. Documentation processes

    Reference Material:
    {reference_material if reference_material else "Using general technical writing knowledge"}
    
    Provide helpful, specific guidance.
    """
    
    user_prompt = f"""
    User Question: {user_question}
    
    Context: {context[:300] if context else "General inquiry"}
    
    Provide helpful technical writing guidance.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=800,
            temperature=0.3
        )
        
        guidance = response.choices[0].message.content
        log_system_message("Chat Assistant: Response provided")
        return {
            "agent": "Chat Assistant",
            "guidance": guidance
        }
        
    except Exception as e:
        log_system_message(f"Chat Assistant: Error - {str(e)}")
        return {"agent": "Chat Assistant", "error": str(e)}

# ============================================================================
# ORCHESTRATOR FUNCTIONS
# ============================================================================

async def run_multi_agent_review(document_text, doc_metadata):
    """Run full multi-agent document review."""
    log_system_message("Orchestrator: Starting multi-agent review")
    
    try:
        # Phase 1: Run content and style analysis in parallel
        content_task = run_content_analysis(document_text, doc_metadata)
        style_task = run_style_analysis(document_text, doc_metadata)
        
        content_result, style_result = await asyncio.gather(content_task, style_task)
        
        # Phase 2: Editorial synthesis
        agent_reports = [content_result, style_result]
        editorial_result = await run_editorial_synthesis(document_text, doc_metadata, agent_reports)
        
        log_system_message("Orchestrator: Multi-agent review completed")
        
        # Store for potential rewrite
        if "review" in editorial_result:
            st.session_state['last_review'] = editorial_result["review"]
            st.session_state['last_document'] = document_text
            st.session_state['agent_reports'] = agent_reports
        
        return editorial_result
        
    except Exception as e:
        log_system_message(f"Orchestrator: Error - {str(e)}")
        return {"error": str(e)}

# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

def init_database():
    """Initialize SQLite database for editorial reviews."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS editorial_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            document_type TEXT NOT NULL,
            document_title TEXT,
            author TEXT,
            original_text TEXT NOT NULL,
            review_notes TEXT,
            issues_found TEXT,
            readability_score TEXT,
            review_status TEXT DEFAULT 'in_progress',
            reviewer_feedback TEXT
        )
        ''')
        conn.commit()
        conn.close()
        st.sidebar.success(f"✅ Connected to editorial database: {DB_FILE}")
        return True
    except Exception as e:
        st.sidebar.error(f"❌ Failed to initialize database: {e}")
        return False

def save_editorial_review(doc_type, doc_title, author, original_text, review_notes=None, issues=None, readability=None, status="in_progress"):
    """Save editorial review to database."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO editorial_reviews (timestamp, document_type, document_title, author, original_text, review_notes, issues_found, readability_score, review_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp, doc_type, doc_title, author, original_text, review_notes or "", 
              json.dumps(issues) if issues else "", json.dumps(readability) if readability else "", status))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log_system_message(f"Database error: {str(e)}")
        return False

def get_editorial_reviews():
    """Retrieve all editorial reviews from database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM editorial_reviews ORDER BY timestamp DESC", conn)
        conn.close()
        return df
    except Exception as e:
        log_system_message(f"Database error: {str(e)}")
        return pd.DataFrame()

# ============================================================================
# STREAMLIT UI
# ============================================================================

def render_sidebar():
    """Render clean side navigation with organized dropdowns."""
    st.sidebar.title("📚 Tech 101 Assistant")
    
    # System Status
    with st.sidebar.expander("⚙️ System Status", expanded=True):
        if OPENAI_API_KEY:
            st.success("✅ System Ready")
        else:
            st.error("❌ Setup Required")
            st.info("Add OpenAI API key to .env file")
            return
    
    # Document Actions
    with st.sidebar.expander("📝 Document Actions", expanded=False):
        if st.button("🔄 New Session", use_container_width=True):
            # Clear session state
            for key in ['messages', 'document_metadata', 'last_review', 'last_document', 'agent_reports']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
        
        if st.button("📊 View History", use_container_width=True):
            df = get_editorial_reviews()
            if not df.empty:
                st.write(f"📝 {len(df)} reviews completed")
                # Show recent reviews
                recent_reviews = df.head(5)[['timestamp', 'document_title', 'document_type']]
                st.dataframe(recent_reviews, use_container_width=True)
            else:
                st.info("No reviews yet")
    
    # Writing Guidelines
    with st.sidebar.expander("📋 Writing Guidelines", expanded=False):
        st.markdown("""
        **Essential Rules:**
        - Use active voice, not passive
        - Write in present tense  
        - Keep sentences under 26 words
        - Be specific, avoid vague terms
        - Specify UI elements clearly
        
        **Common Fixes:**
        - Remove "actually", "basically", "really"
        - Use "Click **Save**" not "click the button"
        - "The API returns" not "will return"
        - "Configure settings" not "Settings should be configured"
        """)
    
    # Document Types Guide
    with st.sidebar.expander("📖 Document Types", expanded=False):
        st.markdown("""
        **API Documentation:**
        - Clear endpoints and parameters
        - Code examples with responses
        - Authentication requirements
        
        **User Guides:**
        - Step-by-step procedures
        - Screenshots and examples
        - Troubleshooting sections
        
        **Tutorials:**
        - Progressive skill building
        - Hands-on exercises
        - Learning objectives
        
        **Installation Guides:**
        - System requirements
        - Detailed setup steps
        - Verification procedures
        """)
    
    # Quality Checklist
    with st.sidebar.expander("✅ Quality Checklist", expanded=False):
        st.markdown("""
        **Before Review:**
        - [ ] Document title provided
        - [ ] Content is complete draft
        - [ ] Spell check completed
        - [ ] Links verified
        
        **After Review:**
        - [ ] Fixed high-priority issues
        - [ ] Applied style guide rules
        - [ ] Tested procedures
        - [ ] Updated formatting
        """)
    
    # Help & Support
    with st.sidebar.expander("❓ Help & Support", expanded=False):
        st.markdown("""
        **How to Use:**
        1. Enter document title and type
        2. Paste your content
        3. Click "Full Review"
        4. Review suggestions
        5. Request rewrite if needed
        
        **Need Help?**
        - Use the chat for specific questions
        - Check writing guidelines above
        - Review quality checklist
        """)
    
    # System Tools
    with st.sidebar.expander("🔧 System Tools", expanded=False):
        if st.button("🧹 Clear Cache", use_container_width=True):
            DOCS_CACHE.clear()
            st.success("Documentation cache cleared")
            log_system_message("SYSTEM: Documentation cache cleared")
        
        if st.button("📤 Export Reviews", use_container_width=True):
            df = get_editorial_reviews()
            if not df.empty:
                json_data = df.to_json(orient="records", indent=4)
                st.download_button(
                    label="📋 Download Reviews",
                    data=json_data,
                    file_name="editorial_reviews_export.json",
                    mime="application/json",
                    use_container_width=True
                )
            else:
                st.info("No reviews to export")

def main():
    """Main Streamlit application for Tech 101 Assistant."""
    # Page configuration
    st.set_page_config(
        page_title="Tech 101 Assistant",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Custom CSS for styling
    st.markdown("""
    <style>
    .stApp {
        background-color: #22577a;
    }
    .main .block-container {
        background-color: rgba(255, 255, 255, 0.95);
        padding: 2rem;
        border-radius: 10px;
        margin-top: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .sidebar .block-container {
        background-color: rgba(255, 255, 255, 0.9);
        border-radius: 10px;
        margin-top: 1rem;
    }
    h1 {
        color: #22577a;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .stButton > button {
        background-color: #22577a;
        color: white;
        border: none;
        border-radius: 5px;
        transition: all 0.3s;
    }
    .stButton > button:hover {
        background-color: #1a4a66;
        transform: translateY(-2px);
    }
    .stTextInput > div > div > input {
        background-color: #f0f8ff;
        border: 2px solid #22577a;
        border-radius: 5px;
        color: #22577a;
    }
    .stSelectbox > div > div > div {
        background-color: #f0f8ff;
        border: 2px solid #22577a;
        border-radius: 5px;
        color: #22577a;
    }
    .stTextArea > div > div > textarea {
        background-color: #f8fbff;
        border: 2px solid #22577a;
        border-radius: 5px;
        color: #22577a;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.title("📚 Tech 101 Assistant")
    st.markdown("**AI-powered technical writing review** • Get comprehensive feedback on your documentation")
    
    # Initialize session state
    if 'messages' not in st.session_state:
        st.session_state['messages'] = []
    if 'system_logs' not in st.session_state:
        st.session_state['system_logs'] = []
    
    # Initialize database
    if not init_database():
        st.warning("Failed to initialize editorial database.")
    
    # Render sidebar
    render_sidebar()
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Document input section
        st.subheader("📝 Document Review")
        
        # Essential metadata
        col1a, col1b = st.columns(2)
        with col1a:
            doc_title = st.text_input("Title", placeholder="API Integration Guide")
        with col1b:
            doc_type = st.selectbox("Type", [
                "API Docs", "User Guide", "Tutorial", "Installation", 
                "Troubleshooting", "Reference", "Getting Started", "Other"
            ])
        
        # Store metadata
        if doc_title:
            st.session_state['document_metadata'] = {
                'title': doc_title,
                'type': doc_type,
                'author': 'User',
                'audience': 'General'
            }
        
        # Document input
        document_text = st.text_area(
            "Paste your documentation here:",
            height=250,
            placeholder="# Getting Started\n\nThis guide shows you how to...",
            help="Paste your draft documentation for multi-agent AI review"
        )
        
        # Action buttons
        if document_text:
            col1a, col1b = st.columns(2)
            
            with col1a:
                if st.button("🔍 Quick Check", use_container_width=True):
                    with st.spinner("Analyzing..."):
                        issues = analyze_technical_writing_issues(document_text)
                        if issues:
                            st.error(f"Found {len(issues)} issues to fix")
                            for issue in issues[:3]:
                                st.warning(f"**{issue['type']}**: {issue['suggestion']}")
                        else:
                            st.success("✅ Looks good!")
            
            with col1b:
                if st.button("✨ Full Review", use_container_width=True):
                    if doc_title:
                        with st.spinner("Running comprehensive analysis..."):
                            review_result = asyncio.run(
                                run_multi_agent_review(
                                    document_text,
                                    st.session_state['document_metadata']
                                )
                            )
                            
                            if "error" not in review_result:
                                st.session_state['messages'].append({
                                    "role": "assistant", 
                                    "content": f"## ✨ Comprehensive Editorial Review\n\n{review_result.get('review', 'Review completed')}"
                                })
                                
                                # Save to database
                                save_editorial_review(
                                    st.session_state['document_metadata']['type'],
                                    doc_title,
                                    'User',
                                    document_text,
                                    review_result.get('review', 'Comprehensive review completed')
                                )
                            else:
                                st.error(f"Review error: {review_result['error']}")
                        st.rerun()
                    else:
                        st.warning("Add a title first")
        
        # Chat interface
        if st.session_state['messages']:
            st.subheader("💬 Review & Chat")
            
            for message in st.session_state['messages']:
                with st.chat_message(message["role"]):
                    st.write(message["content"])
        
        # Chat input
        user_input = st.chat_input("Ask questions or request rewrite...")
        if user_input:
            st.session_state['messages'].append({"role": "user", "content": user_input})
            
            with st.spinner("Processing your request..."):
                # Check for rewrite request
                rewrite_keywords = ["rewrite", "yes, rewrite", "yes please", "go ahead", "yes, go ahead", "create new version", "improve draft"]
                is_rewrite_request = any(keyword in user_input.lower() for keyword in rewrite_keywords)
                
                if is_rewrite_request and document_text and 'last_review' in st.session_state:
                    # Handle rewrite request
                    rewrite_result = asyncio.run(
                        run_document_rewrite(
                            document_text,
                            st.session_state.get('document_metadata', {}),
                            st.session_state['last_review']
                        )
                    )
                    
                    if "error" not in rewrite_result:
                        response = f"""## ✏️ Improved Draft

{rewrite_result['improved_draft']}

---

### 🔄 Improvements Applied:
- Fixed clarity and structure issues
- Applied style guide rules (voice, tense, formatting)
- Coordinated overall improvements
- Rewrote for professional quality

You can copy this improved version or ask for specific adjustments!"""
                    else:
                        response = f"I apologize, but there was an error with the rewrite: {rewrite_result['error']}"
                
                else:
                    # Handle regular chat question
                    chat_result = asyncio.run(
                        handle_chat_question(
                            user_input, 
                            context=document_text[:500] if document_text else None
                        )
                    )
                    
                    if "error" not in chat_result:
                        response = f"## 💬 Assistant Response\n\n{chat_result['guidance']}"
                    else:
                        response = f"I apologize, but there was an error: {chat_result['error']}"
                
                st.session_state['messages'].append({"role": "assistant", "content": response})
            
            st.rerun()
    
    with col2:
        # Current document status
        if 'document_metadata' in st.session_state:
            st.subheader("📄 Current Document")
            metadata = st.session_state['document_metadata']
            st.info(f"**{metadata.get('title', 'Untitled')}**")
            st.caption(f"Type: {metadata.get('type', 'N/A')}")
        
        # Review process
        with st.expander("🔄 Review Process", expanded=True):
            st.markdown("""
            **How It Works:**
            1. **Content Analysis** → Check clarity & structure
            2. **Style Review** → Verify compliance  
            3. **Editorial Synthesis** → Combined recommendations
            4. **Rewrite Option** → Improved draft (if requested)
            5. **Chat Support** → Answer questions
            """)
        
        # Quick tips
        with st.expander("💡 Quick Tips", expanded=False):
            st.markdown("""
            **Common Issues:**
            - Passive voice in instructions
            - Future tense instead of present
            - Vague UI references
            - Unnecessary filler words
            - Long, complex sentences
            """)
        
        # System activity
        if st.session_state['system_logs']:
            with st.expander("📊 Recent Activity", expanded=False):
                # Show recent system logs
                recent_logs = st.session_state['system_logs'][-6:]
                for log in recent_logs:
                    # Clean up log display - remove timestamps and agent names for cleaner view
                    if ']' in log:
                        clean_log = log.split(']', 1)[1].strip()
                        # Further clean by removing agent names
                        if ':' in clean_log:
                            parts = clean_log.split(':', 1)
                            if len(parts) > 1:
                                clean_log = parts[1].strip()
                    else:
                        clean_log = log
                    st.caption(clean_log)

if __name__ == "__main__":
    main()