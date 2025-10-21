from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import os
import shutil

app = FastAPI(title="Stremer Mock Server")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "storage"))
os.makedirs(ROOT, exist_ok=True)

USERS = {"admin": "password"}

class LoginRequest(BaseModel):
    username: str
    password: str

class CopyRequest(BaseModel):
    src: str
    dst: str

@app.post("/auth/login")
async def login(req: LoginRequest):
    if USERS.get(req.username) == req.password:
        return {"token": "mock-token"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/files")
async def list_files(path: str = Query("/")):
    abs_path = os.path.normpath(os.path.join(ROOT, path.lstrip('/')))
    if not abs_path.startswith(ROOT):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="Not found")
    items = []
    for name in os.listdir(abs_path):
        p = os.path.join(abs_path, name)
        rel = os.path.join(path.rstrip('/'), name) if path != '/' else f"/{name}"
        items.append({
            "name": name,
            "type": "dir" if os.path.isdir(p) else "file",
            "size": os.path.getsize(p) if os.path.isfile(p) else ""
        })
    return {"items": items}

@app.get("/stream")
async def stream(path: str = Query("/")):
    abs_path = os.path.normpath(os.path.join(ROOT, path.lstrip('/')))
    if not abs_path.startswith(ROOT) or not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(abs_path)

@app.delete("/file")
async def delete_file(path: str = Query("/")):
    abs_path = os.path.normpath(os.path.join(ROOT, path.lstrip('/')))
    if not abs_path.startswith(ROOT) or not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="Not found")
    if os.path.isdir(abs_path):
        shutil.rmtree(abs_path)
    else:
        os.remove(abs_path)
    return JSONResponse({"status": "deleted"})

@app.post("/copy")
async def copy_file(req: CopyRequest):
    src = os.path.normpath(os.path.join(ROOT, req.src.lstrip('/')))
    dst = os.path.normpath(os.path.join(ROOT, req.dst.lstrip('/')))
    if not src.startswith(ROOT) or not dst.startswith(ROOT):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="Source missing")
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return {"status": "copied"}
