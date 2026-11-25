"""Movie App server: serves the UI and proxies TMDB/OMDb so API keys never reach the browser."""
import asyncio
import os
import re
import time
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

import imdb

load_dotenv()
TMDB_KEY = os.getenv("TMDB_API_KEY")
OMDB_KEY = os.getenv("OMDB_API_KEY")
if not TMDB_KEY:
    raise SystemExit("Missing TMDB_API_KEY. Copy .env.example to .env and add your key.")

@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(imdb.refresh())  # download/parse IMDb ratings in the background
    yield
    task.cancel()


app = FastAPI(title="Movie App", lifespan=lifespan)
client = httpx.AsyncClient(timeout=10)

# Only these TMDB endpoints and query params can be reached through the proxy.
ALLOWED_PATH = re.compile(
    r"^(discover/movie|search/(movie|tv)|trending/(movie|tv)/week|genre/(movie|tv)/list|(movie|tv)/\d+(/recommendations)?)$"
)
ALLOWED_PARAMS = {
    "query", "page", "sort_by", "with_genres", "vote_average.gte", "vote_count.gte",
    "primary_release_date.lte", "include_adult", "append_to_response",
}

_cache: dict = {}
TTL = 300  # seconds


async def fetch(url: str, params: dict, secret: dict):
    key = (url, tuple(sorted(params.items())))  # the secret is never part of the cache key
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    try:
        r = await client.get(url, params={**params, **secret})
    except httpx.HTTPError:
        raise HTTPException(502, "Upstream request failed")  # generic: errors can contain the URL
    if r.status_code != 200:
        raise HTTPException(r.status_code if r.status_code in (401, 404, 429) else 502, "Upstream error")
    data = r.json()
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (time.time(), data)
    return data


@app.get("/api/tmdb/{path:path}")
async def tmdb(path: str, request: Request):
    if not ALLOWED_PATH.match(path):
        raise HTTPException(404, "Not allowed")
    params = {k: v for k, v in request.query_params.items() if k in ALLOWED_PARAMS}
    return await fetch(f"https://api.themoviedb.org/3/{path}", params, {"api_key": TMDB_KEY})


@app.get("/api/omdb")
async def omdb(i: str):
    if not OMDB_KEY:
        raise HTTPException(404, "OMDb not configured")
    if not re.fullmatch(r"tt\d{6,10}", i):
        raise HTTPException(400, "Bad IMDb id")
    return await fetch("https://www.omdbapi.com/", {"i": i}, {"apikey": OMDB_KEY})


@app.get("/api/imdb/movies")
async def imdb_movies(
    min_rating: float = Query(0, alias="min"), genre: str = "", sort_by: str = "popularity.desc", page: int = 1, kind: str = "movie"
):
    """Movies or series filtered/sorted by real IMDb rating, enriched with TMDB posters and metadata."""
    if not imdb.ready:
        raise HTTPException(503, "IMDb data still loading")
    if kind not in ("movie", "tv"):
        raise HTTPException(400, "Bad kind")
    rows, total = imdb.query(kind, min_rating, genre, sort_by, max(1, min(page, 500)))

    async def one(row):
        try:
            d = await fetch(f"https://api.themoviedb.org/3/find/{row[0]}", {"external_source": "imdb_id"}, {"api_key": TMDB_KEY})
        except HTTPException:
            return None
        res = d.get("movie_results" if kind == "movie" else "tv_results") or []
        return {**res[0], "imdb_id": row[0], "imdb_rating": row[1], "imdb_votes": row[2]} if res else None

    found = await asyncio.gather(*(one(r) for r in rows))
    return {"results": [x for x in found if x], "total_results": total, "total_pages": -(-total // 20)}


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
