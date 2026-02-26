# PlanGenie Backend

Modular FastAPI backend with streaming SSE, multi-Gemini keys, OLAMA shimmer, and Supabase memory.

## Requirements

- **Python 3.11 or 3.12** (Python 3.14 is not yet fully supported by LangChain/Pydantic)
- Check your Python version: `python --version`

## Setup

1. **Create virtual environment:**
   ```bash
   python3.11 -m venv venv  # or python3.12
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and fill in your API keys
   ```
   
   **Required keys:**
   - `GEMINI_KEYS` - At least one Gemini API key (get from https://aistudio.google.com/app/apikey)
   - `SERPAPI_API_KEY` - For flight/hotel searches (get from https://serpapi.com/)
   - `TAVILY_API_KEY` - For POI/restaurant searches (get from https://tavily.com/)
   - `SUPABASE_URL` and `SUPABASE_KEY` - For persistence (get from Supabase dashboard)

4. **Run the server:**
   
   **Option 1: Direct Python execution (recommended)**
   ```bash
   python main.py
   ```
   
   **Option 2: Using uvicorn directly**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```
   
   The server will start on `http://localhost:8000`
   API documentation available at: `http://localhost:8000/docs`

## API Endpoints

- `POST /api/chat/message/stream` - Start a streaming plan generation
- `GET /api/chat/{threadId}/stream?streamId=...` - SSE stream endpoint
- `GET /api/chat/{threadId}/plan` - Fetch latest plan (non-streaming)
- `GET /api/health` - Health check

## Architecture

- **FastAPI** → **Orchestrator** → **Agents** → **Tools** → **Supabase**
- Multi-Gemini key support with round-robin fallback
- OLAMA shimmer for progress messages
- LangChain for LLM integration
- SerpAPI for flights/hotels
- Tavily for POIs and experiences

