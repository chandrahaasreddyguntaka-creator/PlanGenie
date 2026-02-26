# PlanGenie Backend Environment Configuration
# Copy this file to .env and fill in your actual API keys

# ============================================================================
# REQUIRED: EXTERNAL API KEYS
# ============================================================================
# SerpAPI - Used for flight and hotel searches
# Get your key from: https://serpapi.com/
SERPAPI_API_KEY=your_serpapi_key_here

# Tavily - Used for POI, restaurant, and experience searches
# Get your key from: https://tavily.com/
TAVILY_API_KEY=your_tavily_key_here

# ============================================================================
# REQUIRED: SUPABASE CONFIGURATION
# ============================================================================
# Supabase project URL
# Get from: https://supabase.com/dashboard/project/_/settings/api
SUPABASE_URL=https://your-project-id.supabase.co

# Supabase service role key (has full access)
# Get from: https://supabase.com/dashboard/project/_/settings/api
SUPABASE_KEY=your_supabase_service_role_key_here
