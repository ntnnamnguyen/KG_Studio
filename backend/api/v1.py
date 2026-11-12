"""Xử lý các endpoint REST API /api/v1 cho KG Studio."""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from backend.facade import KGStudioFacade, get_facade


def _verify_project_scope(project_name_url: str, proj: dict, payload: dict) -> str:
    req_pid = str(payload.get("project_id") or "").strip()
    if not req_pid:
        return ""
    valid_ids = {
        str(proj.get("project_id") or "").strip(),
        str(proj.get("name") or "").strip(),
        project_name_url.strip(),
    }
    valid_ids.discard("")
    if req_pid not in valid_ids:
        return f"project_id '{req_pid}' trong request không khớp với dự án trên URL ('{project_name_url}')"
    return ""


def handle_api_request(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    facade: KGStudioFacade | None = None,
) -> tuple[int, dict[str, Any]]:
    svc = facade or get_facade()
    clean_path = path.rstrip("/") or "/"
    payload = body or {}

    if method == "GET" and clean_path == "/api/v1/health":
        return 200, {
            "status": "ok",
            "service": "KG Studio Pro API v1",
            "modes": svc.available_extraction_modes(),
        }

    if method == "GET" and clean_path == "/api/v1/models":
        return 200, {"models": svc.list_embedding_models()}

    if method == "GET" and clean_path == "/api/v1/projects":
        return 200, {"projects": svc.projects_service.list_project_summaries()}

    if clean_path.startswith("/api/v1/projects/"):
        parts = clean_path.split("/")
        if len(parts) >= 5:
            project_name = unquote(parts[4])
            sub_action = parts[5] if len(parts) >= 6 else ""
            sub_sub_action = parts[6] if len(parts) >= 7 else ""

            if method == "GET" and not sub_action:
                return 200, {"project": svc.projects_service.get_project_summary(project_name)}

            if method == "POST" and sub_action == "retrieve-schema":
                proj = svc.load_project(project_name)
                chunk_text = str(payload.get("chunk_text", ""))
                retrieved = svc.retrieve_schema_for_chunk(proj, chunk_text)
                return 200, {"retrieved": retrieved}

            if method == "POST" and sub_action == "align-target":
                proj = svc.load_project(project_name)
                kind = str(payload.get("kind", "relations"))
                open_name = str(payload.get("name", ""))
                open_def = str(payload.get("definition", ""))
                cands = svc.rank_alignment_candidates(proj, kind, open_name, open_def)
                return 200, {"candidates": cands}

            if method == "POST" and sub_action == "export-training-data":
                proj = svc.load_project(project_name)
                report = svc.export_training_datasets(proj)
                return 200, {"export_report": report}

            if method == "POST" and sub_action == "edc-review":
                proj = svc.load_project(project_name)
                scope_err = _verify_project_scope(project_name, proj, payload)
                if scope_err:
                    return 400, {"error": scope_err}

                req_payload = dict(payload)
                req_payload.setdefault("project_id", str(proj.get("project_id") or project_name))

                if sub_sub_action == "preview":
                    preview = svc.preview_proposal_decisions(proj, req_payload)
                    return 200, {"preview": preview.to_dict()}

                if sub_sub_action == "apply":
                    try:
                        preview_arg = req_payload.pop("preview", None)
                        result = svc.apply_proposal_decisions(proj, req_payload, preview=preview_arg)
                        return 200, {"result": result.to_dict()}
                    except ValueError as exc:
                        return 400, {"error": str(exc)}
                    except Exception as exc:
                        return 500, {"error": str(exc)}

                if sub_sub_action == "refresh-candidates":
                    proposal_ids = list(req_payload.get("proposal_ids") or [])
                    kind = req_payload.get("kind")
                    summary = svc.refresh_proposal_candidates(
                        proj,
                        proposal_ids,
                        kind=str(kind) if kind else None,
                        save=True,
                    )
                    return 200, {"refresh_summary": summary}

                if sub_sub_action == "resync":
                    try:
                        sync_res = svc.resync_sqlite(proj)
                        return 200, sync_res
                    except Exception as exc:
                        return 500, {"error": str(exc)}

            if method == "POST" and sub_action == "curation":
                proj = svc.load_project(project_name)
                scope_err = _verify_project_scope(project_name, proj, payload)
                if scope_err:
                    return 400, {"error": scope_err}

                req_payload = dict(payload)
                req_payload.setdefault("project_id", str(proj.get("project_id") or project_name))

                if sub_sub_action == "preview-edges":
                    preview = svc.preview_curation_decisions(proj, req_payload)
                    return 200, {"preview": preview.to_dict()}

                if sub_sub_action == "apply-edges":
                    try:
                        preview_arg = req_payload.pop("preview", None)
                        result = svc.apply_curation_decisions(proj, req_payload, preview=preview_arg)
                        return 200, {"result": result.to_dict()}
                    except ValueError as exc:
                        return 400, {"error": str(exc)}
                    except Exception as exc:
                        return 500, {"error": str(exc)}

                if sub_sub_action == "edit-edge":
                    try:
                        result = svc.edit_edge_fact(proj, req_payload)
                        return 200, {"result": result.to_dict()}
                    except ValueError as exc:
                        return 400, {"error": str(exc)}
                    except Exception as exc:
                        return 500, {"error": str(exc)}

                if sub_sub_action == "edit-entity":
                    try:
                        result = svc.edit_entity_profile(proj, req_payload)
                        return 200, {"result": result.to_dict()}
                    except ValueError as exc:
                        return 400, {"error": str(exc)}
                    except Exception as exc:
                        return 500, {"error": str(exc)}

                if sub_sub_action == "select-span":
                    try:
                        ctx = svc.select_evidence_span(
                            proj,
                            str(req_payload.get("edge_id") or ""),
                            int(req_payload.get("start_char", 0)),
                            int(req_payload.get("end_char", 0)),
                            actor=str(req_payload.get("actor") or "human_reviewer"),
                            save=True,
                        )
                        return 200, {"evidence_context": ctx}
                    except ValueError as exc:
                        return 400, {"error": str(exc)}
                    except Exception as exc:
                        return 500, {"error": str(exc)}

                if sub_sub_action == "not-duplicate":
                    try:
                        pair_res = svc.mark_pair_not_duplicate(
                            proj,
                            str(req_payload.get("node_a_id") or ""),
                            str(req_payload.get("node_b_id") or ""),
                            note=str(req_payload.get("note") or ""),
                            actor=str(req_payload.get("actor") or "human_reviewer"),
                            save=True,
                        )
                        return 200, {"not_duplicate": pair_res}
                    except ValueError as exc:
                        return 400, {"error": str(exc)}
                    except Exception as exc:
                        return 500, {"error": str(exc)}

                if sub_sub_action == "preview-merge":
                    preview = svc.preview_entity_merge(proj, req_payload)
                    return 200, {"preview": preview.to_dict()}

                if sub_sub_action == "apply-merge":
                    try:
                        preview_arg = req_payload.pop("preview", None)
                        result = svc.apply_entity_merge(proj, req_payload, preview=preview_arg)
                        return 200, {"result": result.to_dict()}
                    except ValueError as exc:
                        return 400, {"error": str(exc)}
                    except Exception as exc:
                        return 500, {"error": str(exc)}

    return 404, {"error": f"Không tìm thấy endpoint: {method} {clean_path}"}
