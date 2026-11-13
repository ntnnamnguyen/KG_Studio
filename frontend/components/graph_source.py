"""Select a graph source through application APIs; no project mutation."""
from __future__ import annotations

from zipfile import BadZipFile
import streamlit as st

from shared.constants import MODE_FREE_TRIPLES
from shared.schemas.graph_input import GRAPH_FORMAT, GraphSnapshotDTO


def select_graph_snapshot(project: dict, service) -> tuple[GraphSnapshotDTO, str] | None:
    pid = str(project.get("project_id") or project.get("name") or "default")
    previous_external = st.session_state.get(f"_p06_external_graph_{pid}")
    options = {"approved": "Đồ thị đã duyệt", "baseline": "Baseline B — KG thô", "external": "Graph từ file"}
    source = st.radio("Nguồn đồ thị", list(options), format_func=options.get, horizontal=True,
                      index=2 if previous_external else (1 if project.get("extraction_mode") == MODE_FREE_TRIPLES else 0),
                      key=f"p05_graph_source_{pid}")
    try:
        if source == "approved":
            return service.graph_snapshot(project, source="approved"), source
        if source == "baseline":
            runs = service.baseline_run_options(project)
            sorted_runs = sorted(
                runs,
                key=lambda r: (str(r.get("doc_name") or ""), int(r.get("chunk_number") or 0), str(r.get("run_id") or "")),
            )
            labels = {
                run["run_id"]: (
                    f"{run.get('doc_name')} · Đoạn {run.get('chunk_number')} · "
                    f"[{run.get('status')}] · Attempt: {run['run_id']}"
                )
                for run in sorted_runs
            }
            key = f"p05_baseline_runs_{pid}"
            if key in st.session_state:
                st.session_state[key] = [rid for rid in st.session_state[key] if rid in labels]

            def _set_baseline_runs(target_key: str, rids: list[str]) -> None:
                st.session_state[target_key] = rids

            latest_per_chunk: dict[tuple, str] = {}
            for r in sorted_runs:
                c_key = (r.get("doc_id"), r.get("chunk_number"))
                latest_per_chunk[c_key] = r["run_id"]
            all_latest_rids = list(latest_per_chunk.values())

            # Đặt các nút điều khiển trước và dùng on_click callback để an toàn tuyệt đối với vòng đời widget Streamlit
            col_b1, col_b2 = st.columns(2)
            col_b1.button(
                "⚡ Chọn toàn bộ chunks (Dựng KG thô tổng)",
                key=f"btn_all_{pid}",
                on_click=_set_baseline_runs,
                args=(key, all_latest_rids),
                width="stretch",
            )
            col_b2.button(
                "🧹 Xóa chọn",
                key=f"btn_clear_{pid}",
                on_click=_set_baseline_runs,
                args=(key, []),
                width="stretch",
            )

            selected = st.multiselect("Chọn baseline runs (mỗi chunk một attempt)", list(labels),
                                      format_func=labels.get, key=key)

            st.caption("Chọn runs tường minh; giữ cả lượt lỗi trong manifest khi chúng thuộc thí nghiệm. Không tự chọn lượt tốt nhất.")
            if not selected:
                st.info("Chọn các lượt baseline để dựng KG thô, xem và chạy cùng các thuật toán truy xuất ở trang này.")
                return None
            return service.build_baseline_graph(project, {"project_id": pid, "run_ids": selected}), source
        upload = st.file_uploader("Nạp graph JSON/ZIP", type=["json", "zip"], key=f"p05_graph_file_{pid}")
        if upload is None:
            if not isinstance(previous_external, dict):
                st.info("Nạp graph đã xuất để chạy cùng bộ thuật toán. File raw runs cần được dựng thành KG trước.")
                return None
            data = previous_external
        else:
            data = service.load_project_from_export_bytes(upload.getvalue(), upload.name)
        snapshot = GraphSnapshotDTO.from_graph_input(data) if data.get("graph_format") == GRAPH_FORMAT else service.graph_snapshot(data, source="all")
        return snapshot, source
    except (ValueError, RuntimeError, KeyError, BadZipFile) as exc:
        st.error(str(exc))
        return None
