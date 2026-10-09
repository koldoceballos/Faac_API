from pydantic import BaseModel


class EnqueueRequest(BaseModel):
    licencia: str
    peticion: int
    fichero_peticion: str


class EnqueueResponse(BaseModel):
    success: bool
    id: int
    estado: str
