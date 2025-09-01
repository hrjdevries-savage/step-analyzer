import io
import os
import logging
from typing import Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException

app = FastAPI(title="STEP Analyzer", version="1.1.0")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("step-analyzer")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def _need_occ() -> Dict[str, Any]:
    """
    Probeer eerst OCP (nieuwe naam), val daarna automatisch terug op OCC.Core (pythonocc-core).
    Geeft nette uitleg als beiden ontbreken.
    """
    # 1) OCP (nieuwere naam; sommige distributies gebruiken dit)
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib_Add
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCP.Message import Message_ProgressRange

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
        }
    except Exception:
        pass

    # 2) OCC.Core (pythonocc-core via pip/conda)
    try:
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.IFSelect import IFSelect_RetDone
        from OCC.Core.Bnd import Bnd_Box
        from OCC.Core.BRepBndLib import brepbndlib_Add
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCC.Core.Message import Message_ProgressRange

        # kleine wrapper zodat rest van code identiek blijft
        def BRepBndLib_Add(shape, box, use_triangulation=True):
            return brepbndlib_Add(shape, box, use_triangulation)

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
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Geen OCC/OCP CAD-backend gevonden. Installeer bijv. "
                "`pythonocc-core` (OCC) of `OCP` (OCP) in requirements.txt. "
                f"Onderliggende import-fout: {type(e).__name__}: {e}"
            ),
        )


def _read_step_shape(occ: Dict[str, Any], data: bytes):
    STEPControl_Reader = occ["STEPControl_Reader"]
    IFSelect_RetDone = occ["IFSelect_RetDone"]
    Message_ProgressRange = occ["Message_ProgressRange"]

    # naar /tmp schrijven (reader kan geen bytes direct)
    tmp = "/tmp/upload.step"
    with open(tmp, "wb") as f:
        f.write(data)

    reader = STEPControl_Reader()
    status = reader.ReadFile(tmp)
    if status != IFSelect_RetDone:
        raise HTTPException(status_code=400, detail="STEP lezen mislukte (status != RetDone).")

    # sommige versies vereisen een ProgressRange arg, andere niet
    try:
        reader.TransferRoots(Message_ProgressRange())
    except TypeError:
        reader.TransferRoots()

    return reader.OneShape()


def _stats(occ: Dict[str, Any], shape) -> Dict[str, Any]:
    TopExp_Explorer = occ["TopExp_Explorer"]
    TopAbs_FACE = occ["TopAbs_FACE"]
    TopAbs_EDGE = occ["TopAbs_EDGE"]
    Bnd_Box = occ["Bnd_Box"]
    BRepBndLib_Add = occ["BRepBndLib_Add"]

    # faces tellen
    faces = 0
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        faces += 1
        ex.Next()

    # edges tellen
    edges = 0
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        edges += 1
        ex.Next()

    # bounding box
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


@app.post("/analyze")
async def analyze_step(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="Upload a.u.b. een .step/.stp-bestand.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Leeg bestand.")

    occ = _need_occ()
    try:
        shape = _read_step_shape(occ, data)
        stats = _stats(occ, shape)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Analyseren faalde")
        raise HTTPException(status_code=500, detail=f"Analyseren faalde: {type(e).__name__}: {e}")

    size = stats["bbox"]["size"]
    largest = max(size["x"], size["y"], size["z"])
    classification = "tiny" if largest < 1 else ("small" if largest < 100 else "large")

    return {
        "filename": file.filename,
        "backend": occ["flavor"],  # 'OCC' of 'OCP' ter info
        "stats": stats,
        "derived": {"largest_dimension": float(largest), "classification": classification},
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
