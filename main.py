from typing import Optional, Any, Dict

from fastapi import FastAPI, HTTPException, Body, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, DuplicateKeyError
from bson import ObjectId
from contextlib import asynccontextmanager

def _doc_to_dict(doc: Dict[str, Any]) -> Dict[str, Any]:
	"""Convert a MongoDB document to a JSON-serializable dict."""
	if not doc:
		return doc
	doc = dict(doc)
	_id = doc.get("_id")
	if isinstance(_id, ObjectId):
		doc["_id"] = str(_id)
	return doc



@asynccontextmanager
async def lifespan(app: FastAPI):
	try:
		yield
	finally:
		global _client
		if _client is not None:
			_client.close()


app = FastAPI(title="Artists API", lifespan=lifespan)

# MongoDB connection settings
MONGO_HOST = "localhost"
MONGO_PORT = 32768
MONGO_DB = "crunchbase"
MONGO_COLLECTION = "artistes"   

def get_db_client() -> MongoClient:
	uri = f"mongodb://{MONGO_HOST}:{MONGO_PORT}"
	client = MongoClient(uri, serverSelectionTimeoutMS=2000)
	try:
		client.admin.command("ping")
	except ServerSelectionTimeoutError as e:
		raise RuntimeError(f"Could not connect to MongoDB at {uri}: {e}")
	return client

_client: Optional[MongoClient] = None

def get_collection():
	global _client
	if _client is None:
		_client = get_db_client()
	db = _client[MONGO_DB]
	return db[MONGO_COLLECTION]

class ArtistUpdate(BaseModel):
	model_config = ConfigDict(extra="allow")


class ArtistCreate(BaseModel):
	model_config = ConfigDict(extra="allow")

@app.get("/artists")
def list_artists(limit: int = Query(100, ge=1, le=1000)):
	"""List all artists (paginated by `limit`)."""
	coll = get_collection()
	docs = coll.find().limit(limit)
	items = [_doc_to_dict(d) for d in docs]
	return {"count": len(items), "items": items}

@app.get("/artists/search")
def find_artist(request: Request):
	"""Search artists by any attribute provided as query parameters.

	Behavior:
	- `_id`: will be treated as an ObjectId when possible, otherwise as a string equality.
	- `name`: will search `first_name` OR `last_name` (case-insensitive substring).
	- Any other attribute: case-insensitive substring match via regex.
	- Optional `limit` query param limits the number of returned items.
	"""
	coll = get_collection()
	params = dict(request.query_params)

	limit_val = params.pop("limit", None)

	clauses = []
	for k, v in params.items():
		if k == "name":
			clauses.append({"$or": [
				{"first_name": {"$regex": v, "$options": "i"}},
				{"last_name": {"$regex": v, "$options": "i"}}
			]})
		elif k == "_id":
			try:
				clauses.append({"_id": ObjectId(v)})
			except Exception:
				clauses.append({"_id": v})
		else:
			clauses.append({k: {"$regex": v, "$options": "i"}})

	if not clauses:
		raise HTTPException(status_code=400, detail="Provide at least one query parameter to search")

	if len(clauses) == 1:
		mongo_filter = clauses[0]
	else:
		mongo_filter = {"$and": clauses}

	cursor = coll.find(mongo_filter)
	if limit_val is not None:
		try:
			n = int(limit_val)
			cursor = cursor.limit(max(1, n))
		except Exception:
			raise HTTPException(status_code=400, detail="Invalid limit value")

	items = [_doc_to_dict(d) for d in cursor]
	return {"count": len(items), "items": items}

@app.put("/artists/{artist_id}")
def update_artist(artist_id: str, payload: ArtistUpdate = Body(...)):
	"""Update an artist document by _id using JSON body with fields to set.

	The `_id` field cannot be changed.
	"""
	coll = get_collection()
	try:
		query_id = ObjectId(artist_id)
	except Exception:
		query_id = artist_id

	body = payload.dict(exclude_unset=True)
	if not body:
		raise HTTPException(status_code=400, detail="Empty update payload")
	if "_id" in body:
		body.pop("_id")

	result = coll.update_one({"_id": query_id}, {"$set": body})
	if result.matched_count == 0:
		raise HTTPException(status_code=404, detail="Artist not found")

	doc = coll.find_one({"_id": query_id})
	return _doc_to_dict(doc)


@app.post("/artists", status_code=201)
def create_artist(payload: ArtistCreate = Body(...)):
	"""Create a new artist document. If `_id` is provided it will be used, otherwise MongoDB will create an ObjectId."""
	coll = get_collection()
	body = payload.model_dump()
	if not body:
		raise HTTPException(status_code=400, detail="Empty payload")

	try:
		res = coll.insert_one(body)
	except DuplicateKeyError:
		raise HTTPException(status_code=409, detail="Artist with this _id already exists")

	inserted_id = res.inserted_id if hasattr(res, "inserted_id") else body.get("_id")
	doc = coll.find_one({"_id": inserted_id})
	return _doc_to_dict(doc)


@app.delete("/artists/{artist_id}", status_code=204)
def delete_artist(artist_id: str):
	"""Delete an artist by _id (ObjectId or string). Returns 204 on success."""
	coll = get_collection()
	try:
		query_id = ObjectId(artist_id)
	except Exception:
		query_id = artist_id

	res = coll.delete_one({"_id": query_id})
	if res.deleted_count == 0:
		raise HTTPException(status_code=404, detail="Artist not found")
	return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/artists/{artist_id}")
def get_artist_by_id(artist_id: str):
	"""Get a single artist by _id (path parameter)."""
	coll = get_collection()
	try:
		query_id = ObjectId(artist_id)
	except Exception:
		query_id = artist_id
	doc = coll.find_one({"_id": query_id})
	if not doc:
		raise HTTPException(status_code=404, detail="Artist not found")
	return _doc_to_dict(doc)

if __name__ == "__main__":
	import uvicorn

	uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
