# PlanGenie Backend Environment Configuration
# Copy this file to .env and fill in your actual API keys

# ============================================================================
# REQUIRED: EXTERNAL API KEYS
# ============================================================================
# SerpAPI - Used for flight and hotel searches
# Get your key from: https://serpapi.com/
SERPAPI_API_KEY=714164915155e585f284dd416b74988ad6a4c3abcc95df3f12e9ffce7a0ed158

# Tavily - Used for POI, restaurant, and experience searches
# Get your key from: https://tavily.com/
TAVILY_API_KEY=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

# ============================================================================
# REQUIRED: SUPABASE CONFIGURATION
# ============================================================================
# Supabase project URL
# Get from: https://supabase.com/dashboard/project/_/settings/api
SUPABASE_URL=https://qjiakopmjsdcfbdjvtyw.supabase.co

# Supabase service role key (has full access)
# Get from: https://supabase.com/dashboard/project/_/settings/api
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFqaWFrb3BtanNkY2ZiZGp2dHl3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MzM5Mzg5MiwiZXhwIjoyMDc4OTY5ODkyfQ.I4PCJCTdH7GF-fmrCRfx0cuM0Xf2pQ6CZdvddrCkAq4

OLAMA_MODEL=llama3.1:8b
# Base URL for Ollama API (default: http://localhost:11434)
OLAMA_BASE_URL=http://localhost:11434
# Timeout in seconds for Ollama requests
OLAMA_TIMEOUT_S=15

API_HOST=0.0.0.0

# Port to run the server on
API_PORT=8000

CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173
VITE_API_URL=https://api.yourdomain.com