"""IMDb ratings from IMDb's free non-commercial datasets (https://developer.imdb.com/non-commercial-datasets/).
Personal / non-commercial use only. Files are cached in ./data and refreshed weekly."""
import asyncio
import gzip
import json
import os
import time
from pathlib import Path

import httpx

DATA = Path(__file__).parent / "data"
BASE = "https://datasets.imdbws.com/"
KINDS = {"movie": "movie", "tvSeries": "tv", "tvMiniSeries": "tv"}
MAX_AGE = 7 * 86400
MOVIES: list = []         # [tconst, rating, votes, year, [genres], kind]
ready = False


async def _download(name: str) -> Path:
    dest = DATA / name
    if dest.exists() and time.time() - dest.stat().st_mtime < MAX_AGE:
        return dest
    DATA.mkdir(exist_ok=True)
    tmp = dest.with_suffix(".part")
    async with httpx.AsyncClient(timeout=None, follow_redirects=True) as c:
        async with c.stream("GET", BASE + name) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)
    tmp.replace(dest)
    return dest


def _build(ratings_path: Path, basics_path: Path, min_votes: int = 5000) -> list:
    rat = {}
    with gzip.open(ratings_path, "rt", encoding="utf-8") as f:
        next(f)
        for line in f:
            t, r, v = line.rstrip("\n").split("\t")
            if int(v) >= min_votes:
                rat[t] = (float(r), int(v))
    out = []
    with gzip.open(basics_path, "rt", encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[1] in KINDS and p[0] in rat:
                year = int(p[5]) if p[5].isdigit() else 0
                genres = [] if p[8] == "\\N" else p[8].split(",")
                out.append([p[0], rat[p[0]][0], rat[p[0]][1], year, genres, KINDS[p[1]]])
    return out


async def refresh() -> None:
    global MOVIES, ready
    min_votes = int(os.getenv("IMDB_MIN_VOTES", "5000"))  # ignore titles with fewer IMDb votes
    cache = DATA / f"index_{min_votes}.json"
    try:
        if cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE:
            MOVIES = json.loads(cache.read_text())
        else:
            ratings, basics = await asyncio.gather(
                _download("title.ratings.tsv.gz"), _download("title.basics.tsv.gz")
            )
            MOVIES = await asyncio.to_thread(_build, ratings, basics, min_votes)
            DATA.mkdir(exist_ok=True)
            cache.write_text(json.dumps(MOVIES))
        ready = True
        print(f"IMDb index ready: {len(MOVIES)} movies")
    except Exception as e:  # keep the server up; the UI shows a friendly message
        print("IMDb dataset load failed:", type(e).__name__)


def query(kind: str, min_rating: float, genre: str, sort: str, page: int, per: int = 20):
    items = [m for m in MOVIES if m[5] == kind and m[1] >= min_rating and (not genre or genre in m[4])]
    keys = {
        "vote_average.desc": lambda m: (m[1], m[2]),
        "primary_release_date.desc": lambda m: (m[3], m[2]),
    }
    items.sort(key=keys.get(sort, lambda m: m[2]), reverse=True)  # default: most votes (popular)
    return items[(page - 1) * per : page * per], len(items)
