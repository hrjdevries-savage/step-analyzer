import os
import io
import logging
from typing import Dict, Any, Optional

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="STEP Analyzer", version="1.2.0")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("step-analyzer")

# Request body model voor JSON API
class AnalyzeUrlRequest(BaseModel):
    file_url: HttpUrl
    material: Optional[str] = "steel"
    density_kg_m3: Optional[float] = None

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

def _need_occ() -> Dict[str, Any]:
    """Import OCP of OCC.Core dynamisch"""
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib_Add
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCP.Message import Message_ProgressRange
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        
        def VolumeProperties(shape, props):
            return BRepGProp.VolumeProperties(shape, props)

        return {
            "flavor": "OCP",
            "STEPControl_Reader": STEPControl_Reader,
            "IFSelect_RetDone": IFSelect_RetDone,
            "Bnd_Box": Bnd_Box,
            "BRepBndLib_Add": BRepBndLib_Add,
            "TopExp_Explorer": TopExp_Explorer,
            "TopAbs_FACE": TopAbs_FACE,
            "TopAbs_EDGE": TopAbs_EDGE,
            "Message_ProgressRange": Message_ProgressRange,
            "GProp_GProps": GProp_GProps,
            "VolumeProperties": VolumeProperties,
        }
    except Exception:
        pass

    # Fallback naar OCC.Core
    try:
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.IFSelect import IFSelect_RetDone
        from OCC.Core.Bnd import Bnd_Box
        from OCC.Core.BRepBndLib import brepbndlib_Add
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCC.Core.Message import Message_ProgressRange
        from OCC.Core.GProp import GProp_GProps
        from OCC.Core.BRepGProp import brepgprop_VolumeProperties

        def BRepBndLib_Add(shape, box, use_triangulation=True):
            return brepbndlib_Add(shape, box, use_triangulation)

        def VolumeProperties(shape, props):
            return brepgprop_VolumeProperties(shape, props)

        return {
            "flavor": "OCC",
            "STEPControl_Reader": STEPControl_Reader,
            "IFSelect_RetDone": IFSelect_RetDone,
            "Bnd_Box": Bnd_Box,
            "BRepBndLib_Add": BRepBndLib_Add,
            "TopExp_Explorer": TopExp_Explorer,
            "TopAbs_FACE": TopAbs_FACE,
            "TopAbs_EDGE": TopAbs_EDGE,
            "Message_ProgressRange": Message_ProgressRange,
            "GProp_GProps": GProp_GProps,
            "VolumeProperties": VolumeProperties,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Geen OCC/OCP backend gevonden: {e}"
        )

def _read_step_shape(occ: Dict[str, Any], data: bytes):
    """Laad STEP-bestand en return shape"""
    STEPControl_Reader = occ["STEPControl_Reader"]
    IFSelect_RetDone = occ["IFSelect_RetDone"]
    Message_ProgressRange = occ["Message_ProgressRange"]

    tmp = "/tmp/upload.step"
    with open(tmp, "wb") as f:
        f.write(data)

    reader = STEPControl_Reader()
    status = reader.ReadFile(tmp)
    if status != IFSelect_RetDone:
        raise HTTPException(status_code=400, detail="STEP lezen mislukte")

    try:
        reader.TransferRoots(Message_ProgressRange())
    except TypeError:
        reader.TransferRoots()

    return reader.OneShape()

def _analyze_shape(occ: Dict[str, Any], shape, material: str, density_override: Optional[float]):
    """Analyseer shape en return afmetingen + gewicht"""
    # Bounding box
    Bnd_Box = occ["Bnd_Box"]
    BRepBndLib_Add = occ["BRepBndLib_Add"]
    
    box = Bnd_Box()
    BRepBndLib_Add(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    
    dx = float(xmax - xmin)
    dy = float(ymax - ymin) 
    dz = float(zmax - zmin)
    
    # Sorteer afmetingen (L >= B >= H)
    dims = sorted([dx, dy, dz], reverse=True)
    L, B, H = dims[0], dims[1], dims[2]
    
    # Volume berekening
    GProp_GProps = occ["GProp_GProps"]
    VolumeProperties = occ["VolumeProperties"]
    
    try:
        props = GProp_GProps()
        VolumeProperties(shape, props)
        volume_mm3 = float(props.Mass())
        if volume_mm3 <= 0:
            raise ValueError("Volume <= 0")
        volume_m3 = volume_mm3 * 1e-9  # mm³ -> m³
    except:
        # Fallback: bounding box volume * 0.8
        volume_m3 = (dx * dy * dz) * 1e-9 * 0.8
    
    # Dichtheid en gewicht
    densities = {
        "steel": 7850,
        "stainless": 8000, 
        "aluminum": 2700,
        "brass": 8500,
        "copper": 8960,
        "plastic": 1200
    }
    
    if density_override and density_override > 0:
        density = density_override
    else:
        density = densities.get(material.lower(), 7850)
    
    weight_kg = volume_m3 * density
    
    return {
        "length_mm": round(L, 3),
        "width_mm": round(B, 3), 
        "height_mm": round(H, 3),
        "volume_m3": round(volume_m3, 6),
        "weight_kg": round(weight_kg, 4),
        "solids": 1,  # vereenvoudigd
        "backend": occ["flavor"]
    }

@app.post("/analyze-url")
def analyze_step_url(body: AnalyzeUrlRequest):
    """Analyseer STEP via URL"""
    try:
        # Download bestand
        response = requests.get(str(body.file_url), timeout=30)
        response.raise_for_status()
        data = response.content
        
        if not data or len(data) < 10:
            raise HTTPException(status_code=400, detail="Bestand is leeg")
        
        # Analyseer
        occ = _need_occ()
        shape = _read_step_shape(occ, data)
        result = _analyze_shape(occ, shape, body.material or "steel", body.density_kg_m3)
        result["source"] = str(body.file_url)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyze-url faalde")
        raise HTTPException(status_code=500, detail=f"Fout: {e}")

@app.post("/analyze") 
async def analyze_upload(file: UploadFile = File(...), material: str = "steel", density_kg_m3: Optional[float] = None):
    """Analyseer geüploade STEP"""
    if not file.filename.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="Alleen .step/.stp bestanden")
    
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Leeg bestand")
    
    try:
        occ = _need_occ()
        shape = _read_step_shape(occ, data)
        result = _analyze_shape(occ, shape, material, density_kg_m3)
        result["filename"] = file.filename
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyze faalde")
        raise HTTPException(status_code=500, detail=f"Fout: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
