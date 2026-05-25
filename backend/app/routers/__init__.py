from fastapi import FastAPI

from ..database import Base, engine

from ..routers import printers

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ricoh Monitor")

app.include_router(printers.router)

@app.get("/")

def root():

    return {"message": "Sistema Ricoh funcionando"}
 