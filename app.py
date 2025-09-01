# app.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import requests
import tempfile
import os

# OCP (OpenCascade) imports
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import brepbndlib_Add
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import brepgprop_VolumeProperties
from OCP.TopoDS import TopoDS_Shape

app = FastAPI(title="STEP Analyzer")

# CORS openzetten voor demo
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

def _load_step_to_shape(path: str) -> TopoDS_Shape:
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise HTTPException(status_code=400, detail="STEP bestand kan niet gelezen worden.")
    reader.TransferRoots()
    return reader.OneShape()

def _bbox_mm(shape: TopoDS_Shape):
    box = Bnd_Box()
    brepbndlib_Add(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    # OCC werkt in millimeters
    length = (xmax - xmin)
    width  = (ymax - ymin)
    height = (zmax - zmin)
    return max(length, 0.0), max(width, 0.0), max(height, 0.0)

def _volume_m3(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    brepgprop_VolumeProperties(shape, props)
    vol_mm3 = props.Mass()  # in OCC: Mass() = volume voor solids
    return max(vol_mm3, 0.0) * 1e-9  # mm³ -> m³

def _analyze_step_file(path: str, density: Optional[float]):
    shape = _load_step_to_shape(path)
    L, W, H = _bbox_mm(shape)  # mm
    volume_m3 = _volume_m3(shape)
    result = {
        "length_mm": round(L, 3),
        "width_mm":  round(W, 3),
        "height_mm": round(H, 3),
        "volume_m3": round(volume_m3, 9),
    }
    if density is not None:
        # density in kg/m3
        result["weight_kg"] = round(volume_m3 * float(density), 3)
    return result

@app.post("/analyze")
def analyze(url: Optional[str] = None, density: Optional[float] = None, file: UploadFile = File(None)):
    """
    Gebruik:
    - POST /analyze?url=https://.../part.step&density=7850
    - of multipart upload: file=@part.step
    """
    if not url and not file:
        raise HTTPException(status_code=400, detail="Geef 'url' of upload 'file'.")

    with tempfile.TemporaryDirectory() as tmp:
        step_path = os.path.join(tmp, "input.step")

        if url:
            try:
                r = requests.get(url, timeout=30)
                if r.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Download faalde (HTTP {r.status_code}) vanaf: {url}")
                with open(step_path, "wb") as f:
                    f.write(r.content)
            except requests.RequestException as e:
                raise HTTPException(status_code=400, detail=f"Download faalde vanaf: {url}. Fout: {e}")

        elif file:
            data = file.file.read()
            if not data:
                raise HTTPException(status_code=400, detail="Geüpload bestand is leeg.")
            with open(step_path, "wb") as f:
                f.write(data)

        return _analyze_step_file(step_path, density)
