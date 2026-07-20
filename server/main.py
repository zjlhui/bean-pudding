from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .service import GenerationOptions, generate_pattern_files


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "server" / "runtime"
JOB_ROOT = RUNTIME_ROOT / "jobs"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
JOB_TTL_SECONDS = 24 * 60 * 60
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

logger = logging.getLogger(__name__)

JOB_ROOT.mkdir(parents=True, exist_ok=True)
PROCESSING_SEMAPHORE = asyncio.Semaphore(1)

app = FastAPI(title="Bean Pudding API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.mount("/files", StaticFiles(directory=JOB_ROOT), name="files")


def _remove_expired_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    for path in JOB_ROOT.iterdir():
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
        except OSError:
            continue


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    total = 0
    with destination.open("wb") as file:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="图片不能超过 10MB。")
            file.write(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="没有收到图片内容。")


def _file_url(request: Request, job_id: str, filename: str) -> str:
    base_url = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return f"{base_url}/files/{job_id}/{filename}"


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "Bean Pudding"}


@app.post("/api/v1/patterns")
async def create_pattern(
    request: Request,
    file: UploadFile = File(...),
    max_size: int = Form(78),
    color_limit: int = Form(10),
    global_color_merge_distance: float = Form(6.0),
    outline_simplify: bool = Form(True),
    bright_detail_recovery: bool = Form(True),
    source_coverage_recovery: bool = Form(True),
    near_white_cleanup: bool = Form(True),
    title: str = Form("拼豆图纸"),
) -> dict[str, object]:
    _remove_expired_jobs()
    job_id = uuid.uuid4().hex
    job_dir = JOB_ROOT / job_id
    job_dir.mkdir(parents=True)
    upload_path = job_dir / "upload.bin"

    try:
        await _save_upload(file, upload_path)
        options = GenerationOptions(
            max_size=max_size,
            color_limit=color_limit,
            global_color_merge_distance=global_color_merge_distance,
            outline_simplify=outline_simplify,
            bright_detail_recovery=bright_detail_recovery,
            source_coverage_recovery=source_coverage_recovery,
            near_white_cleanup=near_white_cleanup,
            title=title.strip(),
        )
        async with PROCESSING_SEMAPHORE:
            result = await run_in_threadpool(generate_pattern_files, upload_path, job_dir, options)
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except ValueError as error:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Pattern generation failed for job %s", job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="生成失败，请检查服务端日志。") from error
    finally:
        await file.close()

    upload_path.unlink(missing_ok=True)
    return {
        "job_id": job_id,
        "width": result.width,
        "height": result.height,
        "bead_count": result.bead_count,
        "color_count": result.color_count,
        "pattern_url": _file_url(request, job_id, result.pattern_path.name),
        "rgb_url": _file_url(request, job_id, result.rgb_path.name),
        "summary_url": _file_url(request, job_id, result.summary_path.name),
        "summary": result.summary,
        "source": {
            "width": result.source.width,
            "height": result.source.height,
            "resized": result.source.resized,
        },
        "expires_in": JOB_TTL_SECONDS,
    }
