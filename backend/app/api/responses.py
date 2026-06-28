from fastapi import HTTPException
from fastapi.responses import JSONResponse


def error_response(message: str, status_code: int = 400, **extra):
    body = {"error": message}
    body.update(extra)
    return JSONResponse(body, status_code=status_code)


def raise_json_error(message: str, status_code: int = 400, **extra):
    if extra:
        raise HTTPException(status_code=status_code, detail={"error": message, **extra})
    raise HTTPException(status_code=status_code, detail=message)
