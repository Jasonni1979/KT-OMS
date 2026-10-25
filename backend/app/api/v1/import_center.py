"""导入中心 API（SRS-D01.06 FR-01/FR-02/FR-03）

路由前缀 /api/v1/import
"""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.services import import_center as svc
from app.services import importers  # noqa: F401  # 导入即注册模板与导入器
from app.services.master import get_redis

router = APIRouter(tags=["import-导入导出"])


@router.get("/templates", summary="导入模板列表")
async def list_templates(session: AsyncSession = Depends(get_session)):
    templates = await svc.ImportService(session, await get_redis()).list_templates()
    return ok(
        [
            {
                "template_code": t.template_code,
                "template_name": t.template_name,
                "domain_code": t.domain_code,
                "entity_ref": t.entity_ref,
                "version": t.version,
                "columns": t.to_columns_json(),
            }
            for t in templates
        ]
    )


@router.get("/templates/{template_code}/file", summary="下载标准模板文件")
async def download_template(
    template_code: str, session: AsyncSession = Depends(get_session)
):
    content = svc.ImportService(session, await get_redis()).template_file(template_code)
    spec = svc.get_template(template_code)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{spec.template_code}_template.xlsx"'
        },
    )


@router.post("/tasks", summary="上传文件创建导入任务")
async def create_task(
    file: UploadFile = File(...),
    template_code: str = Form(...),
    creator: str = Form(default=""),
    session: AsyncSession = Depends(get_session),
):
    content = await file.read()
    task = await svc.ImportService(session, await get_redis()).create_task(
        template_code, file.filename or "upload.xlsx", content, creator
    )
    return ok(
        {
            "id": task.id,
            "task_bn": task.task_bn,
            "template_code": task.template_code,
            "status": task.status,
            "file_md5": task.file_md5,
        }
    )


@router.post("/tasks/{task_id}/run", summary="执行导入任务（解析→校验→批次提交→报告）")
async def run_task(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await svc.ImportService(session, await get_redis()).run_task(task_id)
    return ok(
        {
            "id": task.id,
            "task_bn": task.task_bn,
            "status": task.status,
            "row_count_total": task.row_count_total,
            "progress": task.progress_json,
            "result": task.result_json,
            "cost_ms": task.cost_ms,
            "fail_reason": task.fail_reason,
        }
    )


@router.get("/tasks", summary="导入任务列表")
async def list_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    tasks = await svc.ImportService(session, await get_redis()).list_tasks(limit)
    return ok(
        [
            {
                "id": t.id,
                "task_bn": t.task_bn,
                "template_code": t.template_code,
                "status": t.status,
                "row_count_total": t.row_count_total,
                "progress": t.progress_json,
                "result": t.result_json,
                "error_report_ref": t.error_report_ref,
                "creator": t.creator,
                "cost_ms": t.cost_ms,
                "create_time": str(t.create_time),
            }
            for t in tasks
        ]
    )


@router.get("/tasks/{task_id}", summary="导入任务详情")
async def get_task(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await svc.ImportService(session, await get_redis()).get_task(task_id)
    return ok(
        {
            "id": task.id,
            "task_bn": task.task_bn,
            "template_code": task.template_code,
            "status": task.status,
            "row_count_total": task.row_count_total,
            "progress": task.progress_json,
            "result": task.result_json,
            "error_report_ref": task.error_report_ref,
            "fail_reason": task.fail_reason,
            "retry_count": task.retry_count,
            "creator": task.creator,
            "start_time": str(task.start_time),
            "end_time": str(task.end_time),
            "cost_ms": task.cost_ms,
        }
    )


@router.get("/tasks/{task_id}/errors", summary="导入错误明细（错误阶段/错误码/人读消息）")
async def list_task_errors(task_id: int, session: AsyncSession = Depends(get_session)):
    errors = await svc.ImportService(session, await get_redis()).list_errors(task_id)
    return ok(
        [
            {
                "id": e.id,
                "row_no": e.row_no,
                "error_stage": e.error_stage,
                "error_code": e.error_code,
                "error_message": e.error_message,
                "row_snapshot": e.row_snapshot,
            }
            for e in errors
        ]
    )
