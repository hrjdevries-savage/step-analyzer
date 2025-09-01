import io
import os
import logging
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="STEP Analyzer", version="1.0.0")

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("step-analyzer")

# ---------- Gezondheidscheck ----------
@app.get("/healthz")
def healthz():
    return {"status": "ok"}

# ---------- Helpers die alleen importeren wanneer nodig ----------
def _need_ocp():
    """
    Importeer OCP (pythonocc) pas wanneer we het echt nodig hebben.
    Gooit een duidelijke fout als het pakket ontbreekt.
    """
    try:
        # Kern imports
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.TopLoc import TopLoc_Location
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib_Add
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCP.TopoDS import TopoDS_Shape
        from OCP.BRep import BRep_Builder
        from OCP.Message import Message_ProgressRange

        # return als namespace-achtig dict zodat we overal exact weten wat we gebruiken
        return {
            "STEPControl_Reader": STEPControl_Reader,
            "IFSelect_RetDone": IFSelect_RetDone,
            "TopLoc_Location": TopLoc_Location,
            "Bnd_Box": Bnd_Box,
            "BRepBndLib_Add": BRepBndLib_Add,
            "TopExp_Explorer": TopExp_Explorer,
            "TopAbs_FACE": TopAbs_FACE,
            "TopAbs_EDGE": TopAbs_EDGE,
            "TopoDS_Shape": TopoDS_Shape,
            "BRep_Builder": BRep_Builder,
            "Message_ProgressRange": Message_ProgressRange,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "OCP (pythonocc) is niet geïnstalleerd in deze runtime. "
                "Zorg dat het pakket beschikbaar is (bijv. OCP==0.1.9) in requirements.txt "
                f"of container image. Onderliggende import-fout: {type(e).__name__}: {e}"
            ),
        )


def _shape_stats(ocp: Dict[str, Any], shape) -> Dict[str, Any]:
    """Tel edges/faces en bereken bounding box."""
    TopExp_Explorer = ocp["TopExp_Explorer"]
    TopAbs_FACE = ocp["TopAbs_FACE"]
    TopAbs_EDGE = ocp["TopAbs_EDGE"]
    Bnd_Box = ocp["Bnd_Box"]
    BRepBndLib_Add = ocp["BRepBndLib_Add"]

    # Aantal faces/edges
    faces = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        faces += 1
        exp.Next()

    edges = 0
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edges += 1
        exp.Next()

    # Bounding box
    box = Bnd_Box()
    # kleine toleranties/gaps kan je eventueel op 0 laten; default werkt meestal prima
    BRepBndLib_Add(shape, box, True)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()

    bbox = {
        "min": {"x": float(xmin), "y": float(ymin), "z": float(zmin)},
        "max": {"x": float(xmax), "y": float(ymax), "z": float(zmax)},
        "size": {
            "x": float(xmax - xmin),
            "y": float(ymax - ymin),
            "z": float(zmax - zmin),
        },
    }

    return {"faces": faces, "edges": edges, "bbox": bbox}


def _read_step_to_shape(ocp: Dict[str, Any], data: bytes):
    """Lees STEP bytes in naar een TopoDS_Shape."""
    STEPControl_Reader = ocp["STEPControl_Reader"]
    IFSelect_RetDone = ocp["IFSelect_RetDone"]
    Message_ProgressRange = ocp["Message_ProgressRange"]

    # Reader instantiëren
    reader = STEPControl_Reader()

    # Voor in-memory bytes heeft de reader standaard geen directe API; we schrijven kort naar /tmp
    tmp_path = "/tmp/upload.step"
    with open(tmp_path, "wb") as f:
        f.write(data)

    status = reader.ReadFile(tmp_path)
    if status != IFSelect_RetDone:
        raise HTTPException(
            status_code=400,
            detail="Kon STEP niet inlezen (IFSelect_RetDone != status).",
        )

    # Alles overzetten naar shape
    # ProgressRange optioneel; sommige versies verwachten een arg, anderen niet.
    try:
        reader.TransferRoots(Message_ProgressRange())
    except TypeError:
        reader.TransferRoots()

    shape = reader.OneShape()
    return shape


# ---------- API: analyseer STEP ----------
@app.post("/analyze")
async def analyze_step(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="Upload a.u.b. een .step/.stp bestand.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Leeg bestand.")

    ocp = _need_ocp()  # valideert beschikbaarheid OCP/pythonocc

    try:
        shape = _read_step_to_shape(ocp, data)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("STEP inlezen faalde")
        raise HTTPException(status_code=400, detail=f"STEP inlezen faalde: {type(e).__name__}: {e}")

    try:
        stats = _shape_stats(ocp, shape)
    except Exception as e:
        log.exception("Analyseren faalde")
        raise HTTPException(status_code=500, detail=f"Analyseren faalde: {type(e).__name__}: {e}")

    # Simpele extra afleiding voor frontend/controle
    size = stats["bbox"]["size"]
    largest_dim = max(size["x"], size["y"], size["z"])
    classification = (
        "tiny" if largest_dim < 1.0
        else "small" if largest_dim < 100.0
        else "large"
    )

    return {
        "filename": file.filename,
        "stats": stats,
        "derived": {
            "largest_dimension": float(largest_dim),
            "classification": classification,
        },
    }


# ---------- Entrypoint voor Render (niet verplicht wanneer je via CMD uvicorn start) ----------
if __name__ == "__main__":
    # Render zet PORT in env; lokaal default 8000
    port = int(os.getenv("PORT", "8000"))
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
