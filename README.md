# Movie App

Movie browser with TMDB data, IMDb ratings via OMDb, and TF-IDF recommendations.
A small FastAPI server holds the API keys, so the browser never sees them.

## Run
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then add your keys (Windows: copy .env.example .env)
uvicorn main:app --reload
```
Open http://127.0.0.1:8000. Opening `static/index.html` directly will not work; the page needs the server.

## Keys
- `.env` is listed in `.gitignore`. Commit `.env.example` only.
- Get keys: themoviedb.org/settings/api and omdbapi.com/apikey.aspx
- On Render, Railway or Fly, set `TMDB_API_KEY` and `OMDB_API_KEY` as environment variables instead of uploading `.env`.
- If a key was ever committed, regenerate it. Deleting the file does not remove it from git history.

This product uses the TMDB API but is not endorsed or certified by TMDB.

## IMDb ratings
The rating filter and sort use real IMDb ratings from IMDb's free non-commercial datasets (personal use only).
On first start the server downloads two files (~200 MB) into `data/` and builds a small index; this takes a minute or two and the
page shows a "still downloading" message until it's done. It refreshes weekly. Only movies with 5,000+ IMDb votes are included.
Hosts with temporary disks (Render free tier) will re-download on each restart.
