from pydantic import BaseModel

class SearchCriteria(BaseModel):
    province: str
    city: str
    district: str
    street: str
    house_number: int
    room_count: int
    space_sm: float
    floor: int
    max_price: int

class PromptRequest(BaseModel):
    prompt: str