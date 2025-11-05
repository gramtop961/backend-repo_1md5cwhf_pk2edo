import os
from datetime import datetime
from typing import Optional, Literal, List, Any, Dict
from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="ResqFood API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

############################
# Utility helpers
############################

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID")


def serialize_doc(doc: Dict[str, Any]):
    if not doc:
        return doc
    doc = dict(doc)
    _id = doc.get("_id")
    if isinstance(_id, ObjectId):
        doc["id"] = str(_id)
        del doc["_id"]
    # Convert datetimes to iso
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


############################
# Schemas for requests
############################

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Literal['restaurant', 'ngo', 'society', 'admin']
    address: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class DonationCreateRequest(BaseModel):
    food_item: str
    quantity: str
    pickup_address: str
    expiry_time: datetime
    restaurant_id: str
    restaurant_name: str

class DonationUpdateRequest(BaseModel):
    food_item: Optional[str] = None
    quantity: Optional[str] = None
    pickup_address: Optional[str] = None
    expiry_time: Optional[datetime] = None

class ClaimRequest(BaseModel):
    user_id: str
    user_name: str
    role: Literal['ngo', 'society']

class DeliverRequest(BaseModel):
    delivered: bool = True

############################
# Simple hashing (SHA256) for demo
############################
import hashlib

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


############################
# Health & Test
############################
@app.get("/")
def read_root():
    return {"message": "ResqFood API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


############################
# Auth
############################
@app.post("/auth/register")
def register(req: RegisterRequest):
    # Check if email exists
    existing = db["user"].find_one({"email": req.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_doc = {
        "name": req.name,
        "email": req.email,
        "password_hash": hash_password(req.password),
        "role": req.role,
        "address": req.address,
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = db["user"].insert_one(user_doc)
    user_doc["id"] = str(result.inserted_id)
    del user_doc["password_hash"]
    user_doc.pop("_id", None)
    return user_doc


@app.post("/auth/login")
def login(req: LoginRequest):
    user = db["user"].find_one({"email": req.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("password_hash") != hash_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = serialize_doc(user)
    user.pop("password_hash", None)
    return user


############################
# Donations
############################
@app.post("/donations")
def create_donation(req: DonationCreateRequest):
    # Ensure restaurant exists and role matches
    restaurant = db["user"].find_one({"_id": oid(req.restaurant_id)})
    if not restaurant or restaurant.get("role") != "restaurant":
        raise HTTPException(status_code=400, detail="Invalid restaurant user")

    donation = {
        "food_item": req.food_item,
        "quantity": req.quantity,
        "pickup_address": req.pickup_address,
        "expiry_time": req.expiry_time,
        "restaurant_id": req.restaurant_id,
        "restaurant_name": req.restaurant_name,
        "status": "available",
        "claimed_by": None,
        "claimed_by_id": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = db["donation"].insert_one(donation)
    donation["id"] = str(result.inserted_id)
    donation.pop("_id", None)
    return donation


@app.get("/donations")
def list_donations(
    status: Optional[Literal['available', 'claimed', 'delivered']] = Query(None),
    restaurant_id: Optional[str] = Query(None),
    exclude_claimed: Optional[bool] = Query(False),
    search: Optional[str] = Query(None)
):
    filt: Dict[str, Any] = {}
    if status:
        filt["status"] = status
    if restaurant_id:
        filt["restaurant_id"] = restaurant_id
    if exclude_claimed:
        filt["status"] = "available"
    if search:
        filt["$or"] = [
            {"food_item": {"$regex": search, "$options": "i"}},
            {"restaurant_name": {"$regex": search, "$options": "i"}},
            {"pickup_address": {"$regex": search, "$options": "i"}},
        ]

    docs = db["donation"].find(filt).sort("created_at", -1)
    return [serialize_doc(d) for d in docs]


@app.patch("/donations/{donation_id}")
def update_donation(donation_id: str, req: DonationUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        return serialize_doc(db["donation"].find_one({"_id": oid(donation_id)}))
    updates["updated_at"] = datetime.utcnow()
    res = db["donation"].update_one({"_id": oid(donation_id)}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Donation not found")
    return serialize_doc(db["donation"].find_one({"_id": oid(donation_id)}))


@app.delete("/donations/{donation_id}")
def delete_donation(donation_id: str):
    res = db["donation"].delete_one({"_id": oid(donation_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Donation not found")
    return {"success": True}


@app.post("/donations/{donation_id}/claim")
def claim_donation(donation_id: str, req: ClaimRequest):
    # ensure user exists and role is ngo or society
    user = db["user"].find_one({"_id": oid(req.user_id)})
    if not user or user.get("role") not in ("ngo", "society"):
        raise HTTPException(status_code=400, detail="Invalid claimer")

    donation = db["donation"].find_one({"_id": oid(donation_id)})
    if not donation:
        raise HTTPException(status_code=404, detail="Donation not found")
    if donation.get("status") != "available":
        raise HTTPException(status_code=400, detail="Donation not available")

    db["donation"].update_one(
        {"_id": oid(donation_id)},
        {"$set": {
            "status": "claimed",
            "claimed_by": f"{req.role.capitalize()}: {req.user_name}",
            "claimed_by_id": req.user_id,
            "updated_at": datetime.utcnow()
        }}
    )
    return serialize_doc(db["donation"].find_one({"_id": oid(donation_id)}))


@app.post("/donations/{donation_id}/deliver")
def mark_delivered(donation_id: str, _req: DeliverRequest):
    donation = db["donation"].find_one({"_id": oid(donation_id)})
    if not donation:
        raise HTTPException(status_code=404, detail="Donation not found")

    db["donation"].update_one(
        {"_id": oid(donation_id)},
        {"$set": {"status": "delivered", "updated_at": datetime.utcnow()}}
    )
    return serialize_doc(db["donation"].find_one({"_id": oid(donation_id)}))


############################
# Admin overview
############################
@app.get("/admin/overview")
def admin_overview():
    counts = {
        "restaurants": db["user"].count_documents({"role": "restaurant"}),
        "ngos": db["user"].count_documents({"role": "ngo"}),
        "societies": db["user"].count_documents({"role": "society"}),
        "admins": db["user"].count_documents({"role": "admin"}),
        "donations": db["donation"].count_documents({}),
        "available": db["donation"].count_documents({"status": "available"}),
        "claimed": db["donation"].count_documents({"status": "claimed"}),
        "delivered": db["donation"].count_documents({"status": "delivered"}),
    }
    return counts


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
