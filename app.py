# --- debug startup (optioneel, helpt bij Render-problemen) ---
import sys, pkgutil, logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("uvicorn.error").info("sys.path = %s", sys.path)
mods = {m.name for m in pkgutil.iter_modules()}
logging.getLogger("uvicorn.error").info("Heeft OCP in modules? %s", "OCP" in mods)
# -------------------------------------------------------------

from fastapi import FastAPI, UploadFile, File, HTTPException
# Belangrijk: alleen de 'OCP' variant gebruiken
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopAbs import TopAbs_ShapeEnum
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS_Shape

# app.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import requests
import tempfile
import os

# --- OpenCascade imports ---
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import brepbndlib_Add
from OCP.BRepGProp import brepgprop_VolumeProperties
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS_Shape

# --- FastAPI setup ---
app = FastAPI(title="STEP Analyzer")

# CORS volledig open voor demo/test
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"ok": True}

# --- STEP analyse helpers ---
def _load_step(path: str) -> TopoDS_Shape:
    """Laadt een STEP-bestand en geeft een TopoDS_Shape terug."""
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise HTTPException(status_code=400, detail="STEP-bestand kan niet worden gelezen.")
    reader.TransferRoots()
    return reader.OneShape()

def _bounding_box_mm(shape: TopoDS_Shape):
    """Bereken bounding box (mm)."""
    box = Bnd_Box()
    brepbndlib_Add(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return max(xmax - xmin, 0.0), max(ymax - ymin, 0.0), max(zmax - zmin, 0.0)

def _volume_m3(shape: TopoDS_Shape):
    """Bereken volume (m³)."""
    props = GProp_GProps()
    brepgprop_VolumeProperties(shape, props)
    volume_mm3 = props.Mass()
    return max(volume_mm3, 0.0) * 1e-9  # mm³ → m³

def _analyze_step(path: str, density: Optional[float]):
    shape = _load_step(path)
    L, W, H = _bounding_box_mm(shape)
    volume = _volume_m3(shape)
    result = {
        "length_mm": round(L, 3),
        "width_mm": round(W, 3),
        "height_mm": round(H, 3),
        "volume_m3": round(volume, 9),
    }
    if density is not None:
        result["weight_kg"] = round(volume * density, 3)
    return result

# --- API Endpoints ---
@app.post("/analyze")
async def analyze(url: Optional[str] = None, density: Optional[float] = None, file: UploadFile = File(None)):
    """
    Analyseer een STEP-bestand:
    - POST /analyze?url=https://example.com/part.step&density=7850
    - of upload multipart: file=@part.step
    """
    if not url and not file:
        raise HTTPException(status_code=400, detail="Geef 'url' of upload 'file'.")

    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "part.step")

        # Download van URL
        if url:
            try:
                r = requests.get(url, timeout=30)
                if r.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Download faalde (HTTP {r.status_code}): {url}")
                with open(step_path, "wb") as f:
                    f.write(r.content)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Download faalde van {url}. Fout: {str(e)}")

        # Uploadbestand verwerken
        elif file:
            data = await file.read()
            if not data:
                raise HTTPException(status_code=400, detail="Geüpload bestand is leeg.")
            with open(step_path, "wb") as f:
                f.write(data)

        return _analyze_step(step_path, density)
