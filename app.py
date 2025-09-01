import os
import io
import math
import logging
from typing import Dict, Any, Optional

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="STEP Analyzer", version="1.1.0")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("step-analyzer")

# -------------------------
# Config / constants
# -------------------------
REQUEST_TIMEOUT = (10, 60)  # (connect, read) seconds
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB hard limit
TMP_STEP_PATH = "/tmp/upload.step"

# ruwe dichtheden (kg/m3)
MATERIAL_DENSITIES = {
    "steel": 7850,
    "stainless": 8000,
    "aluminum": 2700,
    "brass": 8500,
    "copper": 8960,
    "plastic": 1200,
    "steel_s235": 7850,
    "steel_s355": 7850,
}

DEFAULT_MATERIAL = "steel"


# -------------------------
# Health
# -------------------------
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# -------------------------
# OCC/OCP dynamic import
# -------------------------
def _need_occ() -> Dict[str, Any]:
    """
    Probeer eerst OCP (nieuwere naam), val daarna automatisch terug op OCC.Core (pythonocc-core).
    Biedt één uniforme API terug via een dict met callables/symbols.
    """
    # 1) OCP
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib_Add
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCP.Message import Message_ProgressRange
        from OCP.BRepGProp import BRepGProp_VolumeProperties
        from OCP.GProp import GProp_GProps

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
            "BRepGProp_VolumeProperties": BRepGProp_VolumeProperties,
            "GProp_GProps": GProp_GProps,
        }
    except Exception:
        pass

    # 2) OCC.Core (pythonocc-core)
    try:
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.IFSelect import IFSelect_RetDone
        from OCC.Core.Bnd import Bnd_Box
        from OCC.Core.BRepBndLib import brepbndlib_Add
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCC.Core.Message import Message_ProgressRange
        from OCC.Core.BRepGProp import brepgprop_VolumeProperties
        from OCC.Core.GProp import GProp_GProps

        def BRepBndLib_Add(shape, box, use_triangulation=True):
            return brepbndlib_Add(shape, box, use_triangulation)

        def BRepGProp_VolumeProperties(shape, props, is_skip_shared=False, is_use_mesh=False, tol=1e-3):
            # OCC variant heeft een andere signatuur; wrap naar identieke call:
            return brepgprop_VolumeProperties(shape, props, tol)

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
            "BRepGProp_VolumeProperties": BRepGProp_VolumeProperties,
            "GProp_GProps": GProp_GProps,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Geen OCC/OCP CAD-backend gevonden. Installeer bijv. "
                "`pythonocc-core` (OCC) of `OCP` (OCP). "
                f"Onderliggende import-fout: {type(e).__name__}: {e}"
            ),
        )


# -------------------------
# STEP helpers
# -------------------------
def _read_step_shape(occ: Dict[str, Any], data: bytes):
    STEPControl_Reader = occ["STEPControl_Reader"]
    IFSelect_RetDone = occ["IFSelect_RetDone"]
    Message_ProgressRange = occ["Message_ProgressRange"]

    with open(TMP_STEP_PATH, "wb") as f:
        f.write(data)

    reader = STEPControl_Reader()
    status = reader.ReadFile(TMP_STEP_PATH)
    if status != IFSelect_RetDone:
        raise HTTPException(status_code=400, detail="STEP lezen mislukte (status != RetDone).")

    try:
        reader.TransferRoots(Message_ProgressRange())
    except TypeError:
        # sommige builds hebben geen progress-range nodig
        reader.TransferRoots()

    return reader.OneShape()


def _bbox_stats(occ: Dict[str, Any], shape) -> Dict[str, Any]:
    TopExp_Explorer = occ["TopExp_Explorer"]
    TopAbs_FACE = occ["TopAbs_FACE"]
    TopAbs_EDGE = occ["TopAbs_EDGE"]
    Bnd_Box = occ["Bnd_Box"]
    BRepBndLib_Add = occ["BRepBndLib_Add"]

    # faces
    faces = 0
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        faces += 1
        ex.Next()

    # edges
    edges = 0
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        edges += 1
        ex.Next()

    # bbox
    box = Bnd_Box()
    BRepBndLib_Add(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()

    size_x = float(xmax - xmin)
    size_y = float(ymax - ymin)
    size_z = float(zmax - zmin)

    return {
        "faces": faces,
        "edges": edges,
        "bbox": {
            "min": {"x": float(xmin), "y": float(ymin), "z": float(zmin)},
            "max": {"x": float(xmax), "y": float(ymax), "z": float(zmax)},
            "size": {"x": size_x, "y": size_y, "z": size_z},
        },
    }


def _volume_m3(occ: Dict[str, Any], shape) -> float:
    """Bereken volume (m^3) via mass-properties. Als dat niet lukt: 0.0."""
    GProp_GProps = occ["GProp_GProps"]
    BRepGProp_VolumeProperties = occ["BRepGProp_VolumeProperties"]

    try:
        props = GProp_GProps()
        # OCP/OCC verschillen; wrapper probeert beide varianten te dekken
        BRepGProp_VolumeProperties(shape, props)
        vol_mm3 = float(props.Mass())  # bij STEP = volume in mm^3
        if not math.isfinite(vol_mm3) or vol_mm3 <= 0:
            return 0.0
        return vol_mm3 / 1e9  # mm^3 -> m^3
    except Exception:
        return 0.0


def _sort_dims_mm(x: float, y: float, z: float):
    dims = sorted([float(x), float(y), float(z)], reverse=True)
    return dims[0], dims[1], dims[2]  # L >= B >= H


def _material_density(material: Optional[str], density_override: Optional[float]) -> float:
    if isinstance(density_override, (int, float)) and density_override > 0:
        return float(density_override)
    key = (material or DEFAULT_MATERIAL).lower()
    return float(MATERIAL_DENSITIES.get(key, MATERIAL_DENSITIES[DEFAULT_MATERIAL]))


def _analyze_bytes(data: bytes, material: Optional[str], density_override: Optional[float]) -> Dict[str, Any]:
    occ = _need_occ()
    shape = _read_step_shape(occ, data)
    stats = _bbox_stats(occ, shape)

    size = stats["bbox"]["size"]  # verondersteld mm
    L_mm, B_mm, H_mm = _sort_dims_mm(size["x"], size["y"], size["z"])

    vol_m3 = _volume_m3(occ, shape)
    rho = _material_density(material, density_override)
    weight_kg = vol_m3 * rho if vol_m3 > 0 else 0.0

    return {
        "backend": occ["flavor"],
        "faces": int(stats["faces"]),
        "edges": int(stats["edges"]),
        "length_mm": float(round(L_mm, 3)),
        "width_mm": float(round(B_mm, 3)),
        "height_mm": float(round(H_mm, 3)),
        "volume_m3": float(round(vol_m3, 6)),
        "weight_kg": float(round(weight_kg, 4)),
    }


# -------------------------
# Schemas voor JSON-route
# -------------------------
class AnalyzeRequest(BaseModel):
    file_url: HttpUrl
    material: Optional[str] = DEFAULT_MATERIAL
    density_kg_m3: Optional[float] = None


# -------------------------
# Routes
# -------------------------
@app.post("/analyze")
def analyze_via_url(req: AnalyzeRequest):
    """
    JSON body:
    {
      "file_url": "https://....step",
      "material": "steel",
      "density_kg_m3": 7850
    }
    """
    url = str(req.file_url)
    if not url.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="file_url moet eindigen op .step of .stp")

    try:
        with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT, allow_redirects=True) as r:
            if r.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Download faalde (HTTP {r.status_code})")

            total = 0
            buf = io.BytesIO()
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    buf.write(chunk)
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Bestand te groot (>50MB)")
            data = buf.getvalue()
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Download fout")
        raise HTTPException(status_code=400, detail=f"Download fout: {type(e).__name__}: {e}")

    if not data:
        raise HTTPException(status_code=400, detail="Leeg bestand gedownload")

    try:
        result = _analyze_bytes(data, req.material, req.density_kg_m3)
        result["source"] = url
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyseren faalde")
        raise HTTPException(status_code=500, detail=f"Analyseren faalde: {type(e).__name__}: {e}")


@app.post("/analyze-upload")
async def analyze_upload(file: UploadFile = File(...), material: Optional[str] = DEFAULT_MATERIAL,
                         density_kg_m3: Optional[float] = None):
    """
    Multipart upload route (handig voor handtests via Swagger):
    - field name: file
    - optional fields: material, density_kg_m3
    """
    if not file.filename.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="Upload a.u.b. een .step/.stp-bestand.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Leeg bestand.")

    try:
        result = _analyze_bytes(data, material, density_kg_m3)
        result["filename"] = file.filename
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyseren faalde")
        raise HTTPException(status_code=500, detail=f"Analyseren faalde: {type(e).__name__}: {e}")


# -------------------------
# Dev server
# -------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
