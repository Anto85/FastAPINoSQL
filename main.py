import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional
from bson import ObjectId
from fastapi import Body, FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError


def _doc_to_dict(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc = dict(doc)
    document_id = doc.get("_id")
    if isinstance(document_id, ObjectId):
        doc["_id"] = str(document_id)
    return doc


def _normalize_object_id(value: str) -> Any:
    try:
        return ObjectId(value)
    except Exception:
        return value


def _build_search_filter(params: Dict[str, str]) -> Dict[str, Any]:
    clauses = []
    for key, value in params.items():
        if key == "name":
            clauses.append(
                {
                    "$or": [
                        {"first_name": {"$regex": value, "$options": "i"}},
                        {"last_name": {"$regex": value, "$options": "i"}},
                    ]
                }
            )
        elif key == "_id":
            clauses.append({"_id": _normalize_object_id(value)})
        else:
            clauses.append({key: {"$regex": value, "$options": "i"}})

    if not clauses:
        raise HTTPException(status_code=400, detail="Provide at least one query parameter to search")

    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _parse_limit(raw_limit: Optional[str]) -> Optional[int]:
    if raw_limit is None:
        return None
    try:
        parsed = int(raw_limit)
    except Exception as exc:  # FastAPI converts to str, any failure should surface
        raise HTTPException(status_code=400, detail="Invalid limit value") from exc
    return max(1, parsed)


def _load_environment() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        load_dotenv = None

    if load_dotenv:
        load_dotenv()

    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = [piece.strip() for piece in line.split("=", 1)]
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_environment()

MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
try:
    MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
except (TypeError, ValueError):
    MONGO_PORT = 27017
MONGO_DB = os.getenv("MONGO_DB", "crunchbase")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "artistes")


def get_db_client() -> MongoClient:
    uri = f"mongodb://{MONGO_HOST}:{MONGO_PORT}"
    client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except ServerSelectionTimeoutError as exc:
        raise RuntimeError(f"Could not connect to MongoDB at {uri}: {exc}") from exc
    return client


_client: Optional[MongoClient] = None


def get_collection():
    global _client
    if _client is None:
        _client = get_db_client()
    return _client[MONGO_DB][MONGO_COLLECTION]


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        global _client
        if _client is not None:
            _client.close()


app = FastAPI(title="Artists API", lifespan=lifespan)


class ArtistUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")


class ArtistCreate(BaseModel):
    model_config = ConfigDict(extra="allow")


@app.get("/artists")
def list_artists(limit: int = Query(100, ge=1, le=1000)):
    coll = get_collection()
    documents = coll.find().limit(limit)
    items = [_doc_to_dict(document) for document in documents]
    return {"count": len(items), "items": items}


@app.get("/artists/search")
def find_artist(request: Request):
    params = dict(request.query_params)
    raw_limit = params.pop("limit", None)
    search_filter = _build_search_filter(params)

    coll = get_collection()
    cursor = coll.find(search_filter)

    parsed_limit = _parse_limit(raw_limit)
    if parsed_limit is not None:
        cursor = cursor.limit(parsed_limit)

    items = [_doc_to_dict(document) for document in cursor]
    return {"count": len(items), "items": items}


@app.put("/artists/{artist_id}")
def update_artist(artist_id: str, payload: ArtistUpdate = Body(...)):
    coll = get_collection()
    query_id = _normalize_object_id(artist_id)

    body = payload.model_dump(exclude_unset=True)
    if not body:
        raise HTTPException(status_code=400, detail="Empty update payload")
    body.pop("_id", None)

    result = coll.update_one({"_id": query_id}, {"$set": body})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Artist not found")

    document = coll.find_one({"_id": query_id})
    return _doc_to_dict(document)


@app.post("/artists", status_code=201)
def create_artist(payload: ArtistCreate = Body(...)):
    coll = get_collection()
    body = payload.model_dump()
    if not body:
        raise HTTPException(status_code=400, detail="Empty payload")

    try:
        result = coll.insert_one(body)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Artist with this _id already exists") from exc

    inserted_id = getattr(result, "inserted_id", body.get("_id"))
    document = coll.find_one({"_id": inserted_id})
    return _doc_to_dict(document)


@app.delete("/artists/{artist_id}", status_code=204)
def delete_artist(artist_id: str):
    coll = get_collection()
    query_id = _normalize_object_id(artist_id)

    result = coll.delete_one({"_id": query_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Artist not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/artists/{artist_id}")
def get_artist_by_id(artist_id: str):
    coll = get_collection()
    query_id = _normalize_object_id(artist_id)

    document = coll.find_one({"_id": query_id})
    if not document:
        raise HTTPException(status_code=404, detail="Artist not found")
    return _doc_to_dict(document)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
