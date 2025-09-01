import io
import os
import tempfile
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI(title="STEP Analyzer", version="1.0.0")


@app.get("/", response_class=PlainTextResponse)
def root() -> str:
    return "STEP Analyzer is running. See /healthz and POST /analyze"


@app.get("/healthz")
def healthz():
    """
    Simpele healthcheck die ook controleert of OCP importeerbaar is.
    """
    ocp_ok = False
    ocp_error: Optional[str] = None
    try:
        import OCP  # noqa: F401
        from OCP.STEPControl import STEPControl_Reader  # noqa: F401
        ocp_ok = True
    except Exception as e:  # pragma: no cover
        ocp_error = repr(e)

    return {
        "status": "ok" if ocp_ok else "degraded",
        "ocp_import": ocp_ok,
        "ocp_error": ocp_error,
        "version": app.version,
    }


@app.post("/analyze")
async def analyze_step(file: UploadFile = File(...)):
    """
    Upload een .step/.stp bestand en krijg basisinformatie terug.
    """
    filename = file.filename or "upload.step"
    if not filename.lower().endswith((".step", ".stp")):
        raise HTTPException(
            status_code=400,
            detail="Bestand moet .step of .stp zijn."
        )

    # Probeer OCP pas hier te importeren (fijnere foutmelding naar de client)
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.TopAbs import TopAbs_ShapeEnum
        from OCP.TopoDS import TopoDS_Shape
        from OCP.BRepTools import BRepTools
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"OCP (OpenCascade) kon niet geïmporteerd worden: {e!r}"
        )

    # Sla upload tijdelijk op schijf (STEP-reader verwacht een pad)
    try:
        contents = await file.read()
    finally:
        await file.close()

    try:
        with tempfile.NamedTemporaryFile(suffix=".stp", delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        # Lees STEP
        reader = STEPControl_Reader()
        status = reader.ReadFile(tmp_path)

        if status != IFSelect_RetDone:
            raise HTTPException(
                status_code=400,
                detail=f"STEP lezen mislukt: status={int(status)}"
            )

        ok = reader.TransferRoots()
        if ok == 0:
            raise HTTPException(
                status_code=400,
                detail="Geen shapes getransfereerd uit STEP."
            )

        # Pak het hoofdshape
        shape: TopoDS_Shape = reader.OneShape()

        # Eenvoudige metrics: serialiseer naar BREP in-memory en meet grootte
        brep_buf = io.StringIO()
        # BRepTools::Write schrijft naar file; daarom even naar tijdelijk bestand
        with tempfile.NamedTemporaryFile(suffix=".brep", delete=False) as brep_tmp:
            brep_path = brep_tmp.name
        try:
            BRepTools.Write(shape, brep_path)
            brep_size = os.path.getsize(brep_path)
        finally:
            try:
                os.remove(brep_path)
            except OSError:
                pass

        # Antwoord
        return JSONResponse({
            "filename": filename,
            "transfer_ok": bool(ok),
            "brep_size_bytes": int(brep_size),
            "message": "STEP succesvol gelezen."
        })

    finally:
        # Opruimen
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# Alleen voor lokaal testen (Render gebruikt CMD uit Dockerfile)
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
