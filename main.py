import streamlit as st
import time
import asyncio
import pandas as pd
import sqlite3
import json
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
import os
from openai import OpenAI

# ============================================================================
# CONFIGURATION
# ============================================================================

# Load environment variables
load_dotenv(override=True)

# API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)
else:
    client = None

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
DB_FILE = "editorial_reviews.db"

# Cache for documentation content
DOCS_CACHE = {}
CACHE_EXPIRY = 3600  # 1 hour in seconds

# Page configuration
st.set_page_config(
    page_title="Tech writng 101 assistant",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for styling
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 2rem 0;
        background: linear-gradient(135deg, #f8fafc 0%, #e0f2fe 50%, #e8eaf6 100%);
        border-radius: 1rem;
        margin-bottom: 2rem;
    }
    
    .gradient-text {
        background: linear-gradient(135deg, #1e293b, #1e40af, #3730a3);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3rem;
        font-weight: bold;
        margin-bottom: 1rem;
    }
    
    .upload-area {
        border: 2px dashed #cbd5e1;
        border-radius: 1rem;
        padding: 2rem;
        text-align: center;
        background: rgba(248, 250, 252, 0.5);
        margin: 1rem 0;
    }
    
    .badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        font-size: 0.875rem;
        font-weight: 500;
        margin: 0.25rem;
    }
    
    .badge-ai {
        background: #dbeafe;
        color: #1e40af;
        border: 1px solid #bfdbfe;
    }
    
    .badge-secure {
        background: #dcfce7;
        color: #166534;
        border: 1px solid #bbf7d0;
    }
    
    .badge-realtime {
        background: #f3e8ff;
        color: #7c3aed;
        border: 1px solid #ddd6fe;
    }
    
    .analysis-card {
        background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        border: 1px solid #e2e8f0;
        margin: 1rem 0;
    }

    .results-container {
        background: #f8fafc;
        border-radius: 1rem;
        padding: 1.5rem;
        margin-top: 1rem;
        border: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

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
            original_text TEXT NOT NULL,
            review_notes TEXT,
            review_status TEXT DEFAULT 'completed'
        )
        ''')
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"❌ Database error: {e}")
        return False

def save_review(doc_type, doc_title, original_text, review_notes):
    """Save editorial review to database."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO editorial_reviews (timestamp, document_type, document_title, original_text, review_notes)
        VALUES (?, ?, ?, ?, ?)
        ''', (timestamp, doc_type, doc_title, original_text, review_notes))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Database error: {str(e)}")
        return False

def get_reviews():
    """Retrieve all editorial reviews from database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM editorial_reviews ORDER BY timestamp DESC", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

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

# ============================================================================
# MULTI-AGENT ANALYSIS FUNCTIONS
# ============================================================================

async def run_content_analysis(document_text, doc_metadata):
    """Content Analyzer Agent - analyzes content quality issues."""
    log_system_message("Content Analyzer: Starting analysis")
    
    content_guide = fetch_documentation("content_classification_guide")
    wordiness_examples = fetch_documentation("wordiness_examples")
    clarity_examples = fetch_documentation("clarity_examples")
    
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

    Wordiness Examples:
    {wordiness_examples[:800] if wordiness_examples else "Examples not available"}

    Clarity Examples:
    {clarity_examples[:800] if clarity_examples else "Examples not available"}

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
    quick_reference = fetch_documentation("quick_reference")
    
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

    Quick Reference:
    {quick_reference[:800] if quick_reference else "Reference not available"}

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

async def run_link_validation(document_text, doc_metadata):
    """Link Validator Agent - checks external links and suggests fixes."""
    log_system_message("Link Validator: Starting link validation")
    
    import re
    from urllib.parse import urlparse
    
    # Extract all URLs from document
    url_pattern = r'https?://[^\s\)\]\}">]+'
    urls = re.findall(url_pattern, document_text)
    
    if not urls:
        log_system_message("Link Validator: No external links found")
        return {
            "agent": "Link Validator",
            "findings": "✅ **No external links found** - Nothing to validate."
        }
    
    log_system_message(f"Link Validator: Found {len(urls)} links to check")
    
    def check_single_link(url):
        """Check a single URL and suggest fixes if broken."""
        try:
            import urllib.request
            import urllib.error
            
            # Create request with user agent
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'DocumentationBot/1.0'}
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                status = response.getcode()
                
                if status == 200:
                    return {
                        "url": url,
                        "status": "✅ Working",
                        "code": status,
                        "suggestion": None
                    }
                else:
                    return {
                        "url": url,
                        "status": f"⚠️ HTTP {status}",
                        "code": status,
                        "suggestion": "Check if this is the intended behavior"
                    }
                    
        except urllib.error.HTTPError as e:
            if e.code == 404:
                suggestions = suggest_404_fixes(url)
                return {
                    "url": url,
                    "status": "❌ Not Found (404)",
                    "code": 404,
                    "suggestion": suggestions
                }
            elif e.code in [401, 403]:
                return {
                    "url": url,
                    "status": f"🔒 Access Restricted ({e.code})",
                    "code": e.code,
                    "suggestion": "Verify if authentication is required or if link should be public"
                }
            else:
                return {
                    "url": url,
                    "status": f"❌ HTTP {e.code}",
                    "code": e.code,
                    "suggestion": "Check server status or find alternative"
                }
        except Exception as e:
            return {
                "url": url,
                "status": f"❌ Error: {str(e)[:50]}",
                "code": "ERROR",
                "suggestion": suggest_error_fixes(url, str(e))
            }
    
    def suggest_404_fixes(url):
        """Suggest intelligent fixes for 404 errors."""
        parsed = urlparse(url)
        domain = parsed.netloc
        path = parsed.path
        
        suggestions = []
        
        # GitHub specific fixes
        if 'github.com' in domain:
            if '/blob/' in path:
                suggestions.append("• Repository may have moved - check if it was renamed or transferred")
                suggestions.append("• Branch may have changed (master → main)")
            suggestions.append(f"• Try archive: https://web.archive.org/web/{url}")
        
        # Documentation sites
        elif any(doc_site in domain for doc_site in ['docs.', 'documentation.', 'wiki.']):
            suggestions.append("• Documentation may have been restructured - check site's search")
            suggestions.append("• Try removing version numbers from URL path")
        
        # API endpoints
        elif '/api/' in path or any(api_term in path for api_term in ['/v1/', '/v2/', '/rest/']):
            suggestions.append("• API version may have changed - check for newer versions")
            suggestions.append("• Endpoint may have been deprecated - check API changelog")
        
        # General suggestions
        suggestions.append(f"• Check site manually: {parsed.scheme}://{domain}")
        suggestions.append(f"• Search archive: https://web.archive.org/web/{url}")
        
        return "\n".join(suggestions) if suggestions else "Consider removing or finding an alternative"
    
    def suggest_error_fixes(url, error_msg):
        """Suggest fixes based on error type."""
        if "SSL" in error_msg or "certificate" in error_msg.lower():
            return "SSL certificate issue - site may be misconfigured or unsafe"
        elif "Name or service not known" in error_msg or "DNS" in error_msg:
            return "Domain no longer exists - find alternative or remove link"
        elif "Connection refused" in error_msg:
            return "Server is down - check if this is temporary or permanent"
        else:
            return "Network error - verify URL is correct"
    
    # Check all links
    try:
        working_links = []
        issues = []
        
        for url in urls:
            result = check_single_link(url)
            if result["status"].startswith("✅"):
                working_links.append(result)
            else:
                issues.append(result)
        
        # Format findings
        findings = f"**Link Validation Report** ({len(urls)} links checked)\n\n"
        
        if working_links:
            findings += f"✅ **{len(working_links)} working links** - No action needed\n\n"
        
        if issues:
            findings += f"⚠️ **{len(issues)} links need attention:**\n\n"
            for issue in issues:
                findings += f"**{issue['status']}**\n"
                findings += f"URL: `{issue['url']}`\n"
                if issue.get('suggestion'):
                    findings += f"💡 **Suggestion:** {issue['suggestion']}\n"
                findings += "\n"
        
        if not issues:
            findings += "🎉 **All links are working perfectly!**"
        
        log_system_message(f"Link Validator: Completed - {len(working_links)} working, {len(issues)} issues")
        
        return {
            "agent": "Link Validator",
            "findings": findings
        }
        
    except Exception as e:
        log_system_message(f"Link Validator: Error - {str(e)}")
        return {
            "agent": "Link Validator", 
            "error": f"Link validation failed: {str(e)}"
        }

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
    5. Offer to provide a rewritten draft

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
    """Senior Editor Agent - synthesizes all agent findings."""
    log_system_message("Senior Editor: Synthesizing review")
    
    system_prompt = """
    You are a Senior Editor Agent coordinating technical documentation review.

    Responsibilities:
    1. Synthesize findings from specialist agents
    2. Prioritize issues by impact
    3. Provide clear, actionable recommendations
    4. Create comprehensive editorial guidance
    5. Offer to provide a rewritten draft

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

async def run_multi_agent_review(document_text, doc_metadata):
    """Run full multi-agent document review."""
    log_system_message("Orchestrator: Starting multi-agent review")
    
    try:
        # Phase 1: Run content, style, and link analysis in parallel
        content_task = run_content_analysis(document_text, doc_metadata)
        style_task = run_style_analysis(document_text, doc_metadata)
        link_task = run_link_validation(document_text, doc_metadata)
        
        content_result, style_result, link_result = await asyncio.gather(
            content_task, style_task, link_task
        )
        
        # Phase 2: Editorial synthesis
        agent_reports = [content_result, style_result, link_result]
        editorial_result = await run_editorial_synthesis(document_text, doc_metadata, agent_reports)
        
        log_system_message("Orchestrator: Multi-agent review completed")
        
        return editorial_result
        
    except Exception as e:
        log_system_message(f"Orchestrator: Error - {str(e)}")
        return {"error": str(e)}

# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================

def quick_analysis(text):
    """Quick technical writing analysis."""
    issues = []
    
    # Check for passive voice
    if re.search(r'(should be|can be|will be)\s+\w+ed', text, re.IGNORECASE):
        issues.append("⚠️ **Passive Voice**: Use active voice for clearer instructions")
    
    # Check for future tense
    if re.search(r'\bwill\s+\w+', text, re.IGNORECASE):
        issues.append("⚠️ **Future Tense**: Use present tense ('returns' not 'will return')")
    
    # Check for filler words
    fillers = ["actually", "basically", "really", "very"]
    found_fillers = [word for word in fillers if re.search(rf'\b{word}\b', text, re.IGNORECASE)]
    if found_fillers:
        issues.append(f"⚠️ **Wordiness**: Remove unnecessary words: {', '.join(found_fillers)}")
    
    # Check for vague references
    if re.search(r'\b(the button|the link|the field)\b', text, re.IGNORECASE):
        issues.append("⚠️ **Vague Reference**: Be specific ('Save button' not 'the button')")
    
    # Check sentence length
    sentences = re.split(r'[.!?]+', text)
    long_sentences = [s for s in sentences if len(s.split()) > 25]
    if long_sentences:
        issues.append(f"⚠️ **Long Sentences**: {len(long_sentences)} sentences over 25 words")
    
    return issues

async def multi_agent_analysis(text, doc_title, doc_type):
    """Multi-agent AI analysis using GitHub style guides."""
    if not client:
        return "❌ OpenAI API not configured. Add your API key to use AI analysis."
    
    try:
        # Prepare document metadata
        doc_metadata = {
            'title': doc_title,
            'type': doc_type,
            'author': 'User',
            'timestamp': datetime.now().isoformat()
        }
        
        # Run multi-agent review
        result = await run_multi_agent_review(text, doc_metadata)
        
        if "error" in result:
            return f"❌ Multi-agent analysis error: {result['error']}"
        
        # Return the full result object instead of just the review
        return result
        
    except Exception as e:
        return f"❌ Multi-agent analysis error: {str(e)}"

async def generate_rewrite(original_text, doc_title, doc_type, feedback, analysis_result=None):
    """Generate improved version using style guides and link fixes."""
    if not client:
        return "❌ OpenAI API not configured. Add your API key to use rewrite functionality."
    
    try:
        # Fetch style guides for rewrite
        style_guide = fetch_documentation("style_guide")
        content_guide = fetch_documentation("content_classification_guide")
        
        # Extract link fixes from analysis if available
        link_fixes = ""
        if analysis_result and 'agent_reports' in analysis_result:
            for report in analysis_result.get('agent_reports', []):
                if report.get('agent') == 'Link Validator':
                    findings = report.get('findings', '')
                    if 'need attention' in findings and '💡 **Suggestion:**' in findings:
                        link_fixes = f"\n\nLINK FIXES REQUIRED:\n{findings}"
        
        prompt = f"""
        You are a Technical Writer Agent specializing in document improvement.

        CRITICAL RULES: 
        1. Only improve the existing content - never add new information, examples, or sections
        2. Fix all broken/problematic links identified by the Link Validator
        3. Apply style guide standards to existing content only

        Rewriting principles:
        1. Apply all style guide standards to existing content only
        2. Fix content quality issues in current text
        3. Fix broken links with correct URLs
        4. Maintain technical accuracy of existing information
        5. Preserve author intent and scope exactly
        6. Ensure logical flow of existing content
        7. Only optimize existing text - no additions

        Style Guide:
        {style_guide[:800] if style_guide else "Use standard technical writing principles"}
        
        Content Rules:
        {content_guide[:800] if content_guide else "Focus on clarity and precision"}
        
        {link_fixes}
        
        IMPORTANT: 
        - Improve only what exists
        - Fix any broken links identified above
        - Do not add new content, examples, or explanations

        Original Title: {doc_title}
        Document Type: {doc_type}
        
        Original Content: {original_text}
        
        Editorial Guidance: {feedback}
        
        Provide improved version of the EXACT SAME content with:
        - Better writing quality
        - Fixed broken links
        - No additional information
        """
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2500,
            temperature=0.1
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Rewrite error: {str(e)}"

# ============================================================================
# UI COMPONENTS
# ============================================================================

def render_sidebar():
    """Sidebar with storage, navigation, and system status."""
    with st.sidebar:
        st.markdown("### 🏠 Home")
        
        # System activity moved under home
        if 'system_logs' in st.session_state and st.session_state['system_logs']:
            with st.expander("📊 System Activity", expanded=False):
                recent_logs = st.session_state['system_logs'][-5:]
                for log in recent_logs:
                    # Clean up log display
                    if ']' in log:
                        clean_log = log.split(']', 1)[1].strip()
                        if ':' in clean_log:
                            parts = clean_log.split(':', 1)
                            if len(parts) > 1:
                                clean_log = parts[1].strip()
                    else:
                        clean_log = log
                    st.caption(clean_log)
        
        st.markdown("---")
        
        # System status
        st.markdown("### ⚙️ System Status")
        if client:
            st.success("✅ AI Analysis Ready")
            
            # Check GitHub documentation access
            style_guide_status = "✅" if fetch_documentation("style_guide") else "❌"
            content_guide_status = "✅" if fetch_documentation("content_classification_guide") else "❌"
            
            st.markdown(f"**Style Guides:**")
            st.markdown(f"{style_guide_status} Style Guide")
            st.markdown(f"{content_guide_status} Content Guide")
            
        else:
            st.warning("⚠️ AI Analysis Disabled")
            st.caption("Add OPENAI_API_KEY to .env")
        
        st.markdown("---")
        
        # Quick Stats as dropdown
        df = get_reviews()
        with st.expander("📊 Quick Stats", expanded=False):
            if not df.empty:
                st.metric("Total Reviews", len(df))
                st.metric("This Week", len(df[df['timestamp'] >= (datetime.now() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")]))
                
                # Recent doc types
                recent_types = df['document_type'].value_counts().head(3)
                st.caption("**Recent Types:**")
                for doc_type, count in recent_types.items():
                    st.caption(f"• {doc_type}: {count}")
            else:
                st.info("No reviews yet")
        
        st.markdown("---")
        
        # Cache management
        if st.button("🧹 Clear Cache", use_container_width=True, key="clear_cache_btn"):
            DOCS_CACHE.clear()
            st.success("Documentation cache cleared")
            log_system_message("SYSTEM: Documentation cache cleared")

def main():
    """Main application."""
    
    # Initialize database
    init_database()
    
    # Render sidebar
    render_sidebar()
    
    # Main header
    st.markdown("""
    <div class="main-header">
        <div style="font-size: 3rem; margin-bottom: 1rem;">📄</div>
        <h1 class="gradient-text">Documentation MultiAgent</h1>
        <p style="font-size: 1.2rem; color: #64748b; max-width: 600px; margin: 0 auto; line-height: 1.6;">
            Multi-agent AI platform with GitHub-enforced style guides for comprehensive technical writing review. 
            Content Analyzer, Style Guide Enforcer, and Senior Editor agents work together to improve your documentation.
        </p>
        <div style="margin-top: 1.5rem;">
            <span class="badge badge-ai">⚡ AI-Powered</span>
            <span class="badge badge-secure">🛡️ Secure</span>
            <span class="badge badge-realtime">⏱️ Real-time</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Initialize session state
    if 'analysis_results' not in st.session_state:
        st.session_state['analysis_results'] = None
    if 'system_logs' not in st.session_state:
        st.session_state['system_logs'] = []
    
    # Document input section
    st.markdown("## 📤 Document Analysis")
    
    # Document metadata in a more compact layout
    col1, col2 = st.columns([3, 1])
    with col1:
        doc_title = st.text_input("Document Title", placeholder="API Integration Guide", key="doc_title_input")
    with col2:
        doc_type = st.selectbox("Type", [
            "API Documentation", "User Guide", "Tutorial", "Installation Guide",
            "Troubleshooting", "Reference Manual", "Getting Started", "Other"
        ], key="doc_type_select")
    
    # Document input
    document_text = st.text_area(
        "Document Content",
        height=250,
        placeholder="""# API Integration Guide

This guide explains how to integrate with our REST API...

## Authentication
To authenticate, include your API key in the header:
```
Authorization: Bearer YOUR_API_KEY
```

## Making Requests
Send GET requests to retrieve data:
```
GET /api/v1/users
```

The API will return user data in JSON format.

## Additional Resources
- API Documentation: https://api.example.com/docs
- GitHub Repository: https://github.com/example/api-client
- Support: https://support.example.com

For more examples, see our tutorial at https://docs.example.com/tutorials/getting-started""",
        help="Paste your technical documentation here for analysis",
        key="document_content_input"
    )
    
    # Analysis buttons in a single row
    if document_text and doc_title:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button("⚡ Quick Analysis", type="secondary", use_container_width=True, key="quick_analysis_btn"):
                with st.spinner("Analyzing..."):
                    issues = quick_analysis(document_text)
                    
                    if issues:
                        result = f"**Found {len(issues)} issues:**\n\n"
                        for issue in issues:
                            result += f"{issue}\n\n"
                    else:
                        result = "✅ **No immediate issues found!**"
                    
                    st.session_state['analysis_results'] = {
                        'type': 'Quick Analysis',
                        'content': result
                    }
                    st.rerun()
        
        with col2:
            if st.button("🤖 AI Analysis + Rewrite", type="primary", use_container_width=True, key="ai_analysis_rewrite_btn"):
                if client:
                    with st.spinner("Running AI analysis and generating rewrite..."):
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        # Run analysis and rewrite in parallel
                        status_text.text("🔍 Running AI analysis...")
                        progress_bar.progress(25)
                        
                        async def run_parallel_analysis():
                            # Run analysis, link validation, and rewrite
                            status_text.text("🔍 Running content & style analysis...")
                            progress_bar.progress(20)
                            
                            analysis_task = multi_agent_analysis(document_text, doc_title, doc_type)
                            
                            # Wait for analysis to complete first (includes link validation)
                            analysis_result = await analysis_task
                            
                            progress_bar.progress(70)
                            status_text.text("✏️ Generating improved version...")
                            
                            # Then run rewrite based on analysis
                            rewrite_task = generate_rewrite(
                                document_text, 
                                doc_title, 
                                doc_type, 
                                analysis_result.get('review', 'Analysis completed'), 
                                analysis_result
                            )
                            rewrite_result = await rewrite_task
                            
                            return analysis_result, rewrite_result
                        
                        analysis, rewrite = asyncio.run(run_parallel_analysis())
                        
                        progress_bar.progress(100)
                        status_text.text("✅ Analysis, link validation, and rewrite completed!")
                        
                        # Store combined results
                        st.session_state['analysis_results'] = {
                            'type': 'AI Analysis + Rewrite',
                            'rewrite': rewrite,
                            'analysis': analysis,
                            'document': document_text,
                            'title': doc_title,
                            'doc_type': doc_type
                        }
                        
                        # Save to database
                        save_review(doc_type, doc_title, document_text, analysis)
                        
                        progress_bar.empty()
                        status_text.empty()
                        st.rerun()
                else:
                    st.error("❌ AI analysis requires OpenAI API key configuration.")
    
    elif document_text and not doc_title:
        st.warning("⚠️ Please add a document title to enable analysis.")
    elif not document_text:
        st.info("👆 Enter your document content above to begin analysis.")
    
    # Display results directly on the same page
    if st.session_state.get('analysis_results'):
        results = st.session_state['analysis_results']
        
        st.markdown("---")
        st.markdown(f"## 📋 {results['type']} Results")
        
        # Results container with styling
        st.markdown('<div class="results-container">', unsafe_allow_html=True)
        
        if results['type'] == 'AI Analysis + Rewrite':
            # Display rewrite first
            st.markdown("### ✏️ Improved Version")
            st.markdown("```markdown")
            st.markdown(results['rewrite'])
            st.markdown("```")
            
            # Copy button for rewrite
            if st.button("📋 Copy Rewrite to Clipboard", key="copy_rewrite"):
                st.code(results['rewrite'], language="markdown")
                st.success("Rewrite ready to copy!")
            
            st.markdown("---")
            
            # Display analysis below
            st.markdown("### 🔍 AI Analysis Details")
            st.markdown(results['analysis'])
            
        elif results['type'] == 'Improved Draft':
            st.markdown("### ✏️ Improved Version")
            st.markdown("```markdown")
            st.markdown(results['content'])
            st.markdown("```")
            
            # Copy button
            if st.button("📋 Copy to Clipboard", key="copy_rewrite"):
                st.code(results['content'], language="markdown")
                st.success("Content ready to copy!")
                
        else:
            # Quick Analysis or other types
            st.markdown(results['content'])
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Action buttons for results
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if st.button("🔄 New Analysis", key="new_analysis"):
                st.session_state['analysis_results'] = None
                st.rerun()
        
        with col2:
            if results['type'] == 'AI Analysis' and client:
                if st.button("✏️ Get Rewrite", key="get_rewrite"):
                    with st.spinner("Generating improved version..."):
                        rewrite_result = asyncio.run(
                            generate_rewrite(
                                results.get('document', ''),
                                results.get('title', ''),
                                results.get('doc_type', ''),
                                results['content'],
                                results  # Pass the full analysis result
                            )
                        )
                        
                        st.session_state['analysis_results'] = {
                            'type': 'Improved Draft',
                            'content': rewrite_result
                        }
                        st.rerun()
        
        with col3:
            # Show download button for rewrite results
            if results['type'] in ['Improved Draft', 'AI Analysis + Rewrite'] and st.button("💾 Download Rewrite", key="save_results"):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"improved_draft_{timestamp}.md"
                
                # Get the rewrite content based on result type
                rewrite_content = results.get('rewrite', results.get('content', ''))
                
                st.download_button(
                    label="📥 Download",
                    data=rewrite_content,
                    file_name=filename,
                    mime="text/markdown",
                    key="download_results"
                )
    
    # Footer
    st.markdown("---")
    st.markdown(
        "<p style='text-align: center; color: #64748b;'>🚀 Powered by Advanced AI Agents | 📧 support@docmultiagent.com</p>",
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()