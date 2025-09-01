from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import tempfile, os, requests

# from OCC.Core... -> from OCP...
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import brepbndlib_Add
from OCP.BRepGProp import brepgprop_VolumeProperties
from OCP.GProp import GProp_GProps

app = FastAPI(title="STEP Analyzer", version="1.0.0")

# CORS open (frontend mag overal vandaan aanroepen)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _read_step(path: str):
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError("STEP read failed")
    reader.TransferRoots()
    return reader.OneShape()

def _bbox_mm(shape):
    box = Bnd_Box()
    brepbndlib_Add(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    L = (xmax - xmin) * 1000.0
    B = (ymax - ymin) * 1000.0
    H = (zmax - zmin) * 1000.0
    return max(L,0.0), max(B,0.0), max(H,0.0)

def _volume_m3(shape):
    props = GProp_GProps()
    brepgprop_VolumeProperties(shape, props, True, True)
    return max(props.Mass(), 0.0)  # Mass() == volume voor volume-properties

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/analyze")
async def analyze(
    file: UploadFile = File(None),
    url: Optional[str] = Query(None, description="Public URL naar .stp/.step"),
    density: Optional[float] = Query(None, description="kg/m3, bv 7850 staal, 8000 RVS, 2700 alu"),
):
    if not file and not url:
        raise HTTPException(status_code=400, detail="Provide a file or url")

    try:
        with tempfile.TemporaryDirectory() as td:
            step_path = os.path.join(td, "part.step")
            if file:
                content = await file.read()
                with open(step_path, "wb") as f:
                    f.write(content)
            else:
                r = requests.get(url, timeout=30)
                if r.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Download fai_
