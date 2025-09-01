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


# ---------- Models ----------
class AnalyzeUrlRequest(BaseModel):
    file_url: HttpUrl
    material: Optional[str] = "steel"
    density_kg_m3: Optional[float] = None  # als None -> default per materiaal


# ---------- Health ----------
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ---------- OCC / OCP bridge ----------
def _need_occ() -> Dict[str, Any]:
    """
    Probeer eerst OCP (nieuwe naam), val daarna terug op OCC.Core (pythonocc-core).
    Geeft een dict terug met unified symbolen.
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
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        # unified mass-props call
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

    # 2) OCC.Core (pythonocc-core)
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
            detail=(
                "Geen OCC/OCP CAD-backend gevonden. Installeer bijv. "
                "`pythonocc-core` (OCC) of `OCP` (OCP). "
                f"Onderliggende import-fout: {type(e).__name__}: {e}"
            ),
        )


# ---------- STEP helpers ----------
def _read_step_shape(occ: Dict[str, Any], data: bytes):
    STEPControl_Reader = occ["STEPControl_Reader"]
    IFSelect_RetDone = occ["IFSelect_RetDone"]
    Message_ProgressRange = occ["Message_ProgressRange"]

    tmp = "/tmp/upload.step"
    with open(tmp, "wb") as f:
        f.write(data)

    reader = STEPControl_Reader()
    status = reader.ReadFile(tmp)
    if status != IFSelect_RetDone:
        raise HTTPException(status_code=400, detail="STEP lezen mislukte (status != RetDone).")

    try:
        reader.TransferRoots(Message_ProgressRange())
    except TypeError:
        reader.TransferRoots()

    return reader.OneShape()


def _bbox_mm(occ: Dict[str, Any], shape) -> Dict[str, float]:
    Bnd_Box = occ["Bnd_Box"]
    BRepBndLib_Add = occ["BRepBndLib_Add"]

    box = Bnd_Box()
    # True -> triangulation gebruiken voor betere nauwkeurigheid
    BRepBndLib_Add(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()

    # We nemen hier mm aan (gangbaar in STEP van maakindustrie). Als je in meters werkt, pas dan de schaal aan.
    return {
        "xmin": float(xmin),
        "ymin": float(ymin),
        "zmin": float(zmin),
        "xmax": float(xmax),
        "ymax": float(ymax),
        "zmax": float(zmax),
        "dx": float(xmax - xmin),
        "dy": float(ymax - ymin),
        "dz": float(zmax - zmin),
    }


def _faces_edges(occ: Dict[str, Any], shape) -> Dict[str, int]:
    TopExp_Explorer = occ["TopExp_Explorer"]
    TopAbs_FACE = occ["TopAbs_FACE"]
    TopAbs_EDGE = occ["TopAbs_EDGE"]

    faces = 0
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        faces += 1
        ex.Next()

    edges = 0
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        edges += 1
        ex.Next()

    return {"faces": faces, "edges": edges}


def _volume_m3(occ: Dict[str, Any], shape) -> float:
    """
    Berekent volume via mass properties. OCCT werkt metrisch; in praktijk zijn STEP-modellen vaak mm.
    We interpreteren de uitkomst als mm^3 en converteren naar m^3 (1e-9 factor).
    Fallback: bbox-volume * 0.9 (ruwe schatting).
    """
    GProp_GProps = occ["GProp_GProps"]
    VolumeProperties = occ["VolumeProperties"]

    try:
        props = GProp_GProps()
        VolumeProperties(shape, props)
        vol_mm3 = float(props.Mass())  # bij density=1 gedraagt Mass zich als volume
        if vol_mm3 <= 0:
            raise ValueError("Volume ≤ 0")
        return vol_mm3 * 1e-9  # mm^3 -> m^3
    except Exception:
        # Fallback naar bbox-volume * factor
        bb = _bbox_mm(occ, shape)
        bbox_vol_mm3 = max(bb["dx"], 0) * max(bb["dy"], 0) * max(bb["dz"], 0)
        return float(bbox_vol_mm3) * 1e-9 * 0.9


def _density_for(material: Optional[str], override: Optional[float]) -> float:
    if isinstance(override, (int, float)) and override > 0:
        return float(override)

    mat = (material or "steel").strip().lower()
    table = {
        "steel": 7850.0,
        "stainless": 8000.0,
        "aluminum": 2700.0,
        "aluminium": 2700.0,
        "brass": 8500.0,
        "copper": 8960.0,
        "plastic": 1200.0,
    }
    return table.get(mat, 7850.0)


def _analyze_core(data: bytes, material: Optional[str], density_kg_m3: Optional[float]) -> Dict[str, Any]:
    occ = _need_occ()
    shape = _read_step_shape(occ, data)

    bb = _bbox_mm(occ, shape)
    fe = _faces_edges(occ, shape)
    vol_m3 = _volume_m3(occ, shape)

    rho = _density_for(material, density_kg_m3)
    weight_kg = vol_m3 * rho

    dims_sorted = sorted([bb["dx"], bb["dy"], bb["dz"]], reverse=True)
    L, B, H = dims_sorted[0], dims_sorted[1], dims_sorted[2]

    return {
        "backend": occ["flavor"],
        "faces": fe["faces"],
        "edges": fe["edges"],
        "length_mm": float(L),
        "width_mm": float(B),
        "height_mm": float(H),
        "volume_m3": float(vol_m3),
        "weight_kg": float(weight_kg),
    }


# ---------- Routes ----------
@app.post("/analyze")
async def analyze_step(file: UploadFile = File(...), material: Optional[str] = "steel", density_kg_m3: Optional[float] = None):
    if not file.filename.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="Upload a.u.b. een .step/.stp-bestand.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Leeg bestand.")

    try:
        result = _analyze_core(data, material, density_kg_m3)
        result["filename"] = file.filename
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyseren faalde")
        raise HTTPException(status_code=500, detail=f"Analyseren faalde: {type(e).__name__}: {e}")


@app.post("/analyze-url")
def analyze_step_url(body: AnalyzeUrlRequest):
    # Download bestand
    try:
        r = requests.get(str(body.file_url), timeout=30)
        r.raise_for_status()
        data = r.content
        if not data or len(data) < 10:
            raise HTTPException(status_code=400, detail="Gedownloade file is leeg of te klein.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Download mislukt: {type(e).__name__}: {e}")

    try:
        result = _analyze_core(data, body.material, body.density_kg_m3)
        result["source"] = str(body.file_url)
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyze-url faalde")
        raise HTTPException(status_code=500, detail=f"Analyseren faalde: {type(e).__name__}: {e}")


# ---------- Main ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
