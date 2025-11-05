from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal
from datetime import datetime

# ResqFood Schemas
# Each class name lowercased becomes the collection name in MongoDB

class User(BaseModel):
    """
    users collection
    Collection: "user"
    """
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="SHA256 password hash")
    role: Literal['restaurant', 'ngo', 'society', 'admin'] = Field(..., description="User role")
    address: Optional[str] = Field(None, description="Address or location")
    is_active: bool = Field(True, description="Active status")

class Donation(BaseModel):
    """
    donations collection
    Collection: "donation"
    """
    food_item: str = Field(..., description="Food item name")
    quantity: str = Field(..., description="Quantity (e.g., 10 meals, 5kg)")
    pickup_address: str = Field(..., description="Pickup address")
    expiry_time: datetime = Field(..., description="Expiry date-time in ISO format")
    restaurant_id: str = Field(..., description="Restaurant user id")
    restaurant_name: str = Field(..., description="Restaurant name")
    status: Literal['available', 'claimed', 'delivered'] = Field('available', description="Donation status")
    claimed_by: Optional[str] = Field(None, description="Name of NGO/Society who claimed")
    claimed_by_id: Optional[str] = Field(None, description="User id of claimer")
