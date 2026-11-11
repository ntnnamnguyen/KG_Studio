"""FastAPI Dependencies dùng chung cho các API Routers."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Path, status

from backend.facade import KGStudioFacade, get_facade


def get_facade_instance() -> KGStudioFacade:
    """Trả về singleton instance của KGStudioFacade."""
    return get_facade()


FacadeDep = Annotated[KGStudioFacade, Depends(get_facade_instance)]


def get_project_by_name(
    project_name: Annotated[str, Path(description="Tên của dự án Knowledge Graph")],
    facade: FacadeDep,
) -> dict[str, Any]:
    """Tải dự án từ repository theo tên; ném lỗi 404 nếu không tìm thấy."""
    names = facade.list_projects()
    if project_name not in names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dự án '{project_name}' không tồn tại trong hệ thống.",
        )
    return facade.load_project(project_name)


ProjectDep = Annotated[dict[str, Any], Depends(get_project_by_name)]
