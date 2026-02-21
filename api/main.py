import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from db.database import init_db
from api.routes import router

app = FastAPI(title="Attendance System API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

dashboard_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")
app.mount("/dashboard", StaticFiles(directory=dashboard_path, html=True), name="dashboard")
app.include_router(router, prefix="/api")

@app.on_event("startup")
async def startup():
    init_db()
    print("[API] Server ready.")
