import os
import logging
from typing import Dict, Any, Optional

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="STEP Analyzer", version="1.3.0")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("step-analyzer")

# ===== CORS: laat frontend (Lovable/Quotecoat) direct praten met de API =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # wil je strakker maken? Zet hier je eigen domein(s)
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Pydantic model voor analyze-url =====
class AnalyzeUrlRequest(BaseModel):
    file_url: HttpUrl
    material: Optional[str] = "steel"
    density_kg_m3: Optional[float] = None


@app.get("/")
def root():
    return {
        "name": "STEP Analyzer",
        "version": app.version if hasattr(app, "version") else "n/a",
        "endpoints": ["/healthz", "/analyze (multipart upload)", "/analyze-url (json)"],
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ===== Dynamische OCC/OCP import =====
def _need_occ() -> Dict[str, Any]:
    """
    Probeer eerst OCP (nieuwe naam), val daarna automatisch terug op OCC.Core (pythonocc-core).
    Geeft een dict met de gebruikte symbolen terug.
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


# ===== STEP inlezen en OCCT-shape leveren =====
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

    # Sommige OCCT builds vereisen een progress-range, andere niet
    try:
        reader.TransferRoots(Message_ProgressRange())
    except TypeError:
        reader.TransferRoots()

    return reader.OneShape()


# ===== Shape -> maten/volume/gewicht =====
def _analyze_shape(
    occ: Dict[str, Any],
    shape,
    material: str,
    density_override: Optional[float],
) -> Dict[str, Any]:
    # Bounding box
    Bnd_Box = occ["Bnd_Box"]
    BRepBndLib_Add = occ["BRepBndLib_Add"]

    box = Bnd_Box()
    BRepBndLib_Add(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()

    dx = float(xmax - xmin)
    dy = float(ymax - ymin)
    dz = float(zmax - zmin)

    # Sorteer afmetingen (L ≥ B ≥ H)
    dims = sorted([dx, dy, dz], reverse=True)
    L, B, H = dims[0], dims[1], dims[2]

    # Volume via OCCT (Mass == volume bij dichtheid 1.0)
    GProp_GProps = occ["GProp_GProps"]
    VolumeProperties = occ["VolumeProperties"]
    volume_m3: float

    try:
        props = GProp_GProps()
        VolumeProperties(shape, props)
        volume_mm3 = float(props.Mass())
        if volume_mm3 <= 0:
            raise ValueError("Volume <= 0")
        volume_m3 = volume_mm3 * 1e-9  # mm^3 -> m^3
    except Exception:
        # Fallback: conservatieve schatting (80% van bbox-volume)
        volume_m3 = (dx * dy * dz) * 1e-9 * 0.8

    # Dichtheden (kg/m^3)
    densities = {
        "steel": 7850,
        "stainless": 8000,
        "aluminum": 2700,
        "brass": 8500,
        "copper": 8960,
        "plastic": 1200,
    }
    if density_override and density_override > 0:
        density = float(density_override)
    else:
        density = float(densities.get((material or "steel").lower(), 7850))

    weight_kg = volume_m3 * density

    # Derived classificatie
    largest = max(L, B, H)
    classification = "tiny" if largest < 1 else ("small" if largest < 100 else "large")

    return {
        "length_mm": round(L, 3),
        "width_mm": round(B, 3),
        "height_mm": round(H, 3),
        "volume_m3": round(volume_m3, 6),
        "weight_kg": round(weight_kg, 4),
        "solids": 1,  # simplificatie
        "backend": occ["flavor"],
        "derived": {"largest_dimension": float(round(largest, 3)), "classification": classification},
    }


# ====== Analyze via URL (JSON) ======
@app.post("/analyze-url")
def analyze_step_url(body: AnalyzeUrlRequest):
    """
    Download een STEP vanaf body.file_url en analyseer deze.
    """
    # 1) Download
    try:
        headers = {
            "User-Agent": "step-analyzer/1.0 (+https://step-analyzer.onrender.com)",
            "Accept": "*/*",
        }
        resp = requests.get(
            str(body.file_url),
            headers=headers,
            timeout=45,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Download mislukt: HTTP {resp.status_code} voor URL {body.file_url}",
            )
        data = resp.content

        if not data or len(data) < 1024:
            raise HTTPException(
                status_code=400,
                detail="Gedownloade file is leeg of verdacht klein. Is de URL juist en publiek toegankelijk?",
            )

        # STEP tekstbestanden bevatten meestal deze marker in de header
        head = data[:4096]
        if b"ISO-10303-21" not in head and b"STEP" not in head.upper():
            log.warning("Downloaded content mist typische STEP-header; ga toch proberen te parsen.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Download exception: {type(e).__name__}: {e}")

    # 2) Parse + analyse
    try:
        occ = _need_occ()
        shape = _read_step_shape(occ, data)
        result = _analyze_shape(occ, shape, body.material or "steel", body.density_kg_m3)
        result["source"] = str(body.file_url)
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyze-url faalde")
        raise HTTPException(status_code=500, detail=f"Analyseren faalde: {type(e).__name__}: {e}")


# ====== Analyze via upload (multipart/form-data) ======
@app.post("/analyze")
async def analyze_upload(
    file: UploadFile = File(...),
    material: str = "steel",
    density_kg_m3: Optional[float] = None,
):
    """
    Upload een .step/.stp en krijg L/B/H (mm), volume (m^3) en gewicht (kg) terug.
    """
    if not file.filename.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="Alleen .step/.stp bestanden zijn toegestaan.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Leeg bestand.")

    try:
        occ = _need_occ()
        shape = _read_step_shape(occ, data)
        result = _analyze_shape(occ, shape, material, density_kg_m3)
        result["filename"] = file.filename
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyze (upload) faalde")
        raise HTTPException(status_code=500, detail=f"Analyseren faalde: {type(e).__name__}: {e}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
