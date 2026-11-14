"""Kiểm thử hồi quy AppTest cho đồng bộ trạng thái Streamlit UI (không bounce-back, không warning)."""
from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from backend.bootstrap import AppContainer, reset_container
from backend.facade import KGStudioFacade, reset_facade
from backend.repositories.json_repo import JsonProjectRepository, empty_project
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
import frontend.client as frontend_client
import frontend.composition as frontend_composition
from frontend.composition import FrontendComposition
from shared.catalog_utils import apply_relations
from shared.constants import MODE_EDC_PLUS_R, MODE_FIXED, STATUS_APPROVED, STATUS_PENDING


class _StreamlitPolicyRecorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


@contextmanager
def capture_streamlit_state_warnings():
    """Bật mức WARNING tạm thời cho logger Streamlit (kể cả trong runner cô lập) và ghi nhận cảnh báo."""
    recorder = _StreamlitPolicyRecorder()
    logger_names = ("streamlit", "streamlit.elements.lib.policies")
    saved_levels: dict[str, int] = {}
    for name in logger_names:
        lg = logging.getLogger(name)
        saved_levels[name] = lg.level
        lg.setLevel(logging.WARNING)
    root_st = logging.getLogger("streamlit")
    root_st.addHandler(recorder)
    try:
        yield recorder.messages
    finally:
        root_st.removeHandler(recorder)
        for name, level in saved_levels.items():
            logging.getLogger(name).setLevel(level)


def _assert_no_session_state_warnings(testcase: unittest.TestCase, messages: list[str]) -> None:
    offending = [
        m for m in messages
        if "created with a default value" in m
        or "Session State API" in m
        or "cannot be modified after the widget" in m
    ]
    testcase.assertEqual(offending, [], f"Phát hiện cảnh báo widget Session State: {offending}")


def _build_rich_project(name: str, proj_id: str, *, mode: str = MODE_EDC_PLUS_R, edge_count: int = 12, prop_count: int = 12) -> dict:
    proj = empty_project(name)
    proj["extraction_mode"] = mode
    proj["project_id"] = proj_id
    doc1_text = "Chùa Một Cột tọa lạc tại Hà Nội. Văn Miếu cũng nằm tại Hà Nội từ thời Lý. Độc bản Một Cột."
    proj["documents"] = [
        {
            "id": f"doc_{proj_id}_1",
            "name": f"{name.lower()}_doc_1.txt",
            "text": doc1_text,
            "chars": len(doc1_text),
            "source_label": "Nguồn A",
            "place_scope": "Hà Nội",
        },
        {
            "id": f"doc_{proj_id}_2",
            "name": f"{name.lower()}_doc_2.txt",
            "text": "Hồ Hoàn Kiếm gắn với truyền thuyết trả gươm của vua Lê Lợi.",
            "chars": 61,
            "source_label": "Nguồn B",
            "place_scope": "Hà Nội",
        },
    ]
    proj["entity_types"] = [
        {"name": "Di tích", "description": "Công trình lịch sử", "definition": "Di tích văn hóa"},
        {"name": "Địa danh", "description": "Địa điểm địa lý", "definition": "Khu vực địa lý"},
    ]
    apply_relations(
        proj,
        [
            {"name": "tọa lạc tại", "description": "Vị trí", "definition": "Vị trí địa lý", "aliases": ["nằm tại"]},
            {"name": "nằm ở", "description": "Vị trí biến thể", "definition": "Biến thể", "aliases": []},
            {"name": "gắn với", "description": "Liên hệ", "definition": "Sự kiện gắn liền", "aliases": []},
        ],
    )
    proj["nodes"] = [
        {"id": f"n_{proj_id}_1", "name": "Chùa Một Cột", "kind": "Di tích", "aliases": ["Diên Hựu Tự"], "documents": [f"doc_{proj_id}_1"]},
        {"id": f"n_{proj_id}_2", "name": "Hà Nội", "kind": "Địa danh", "aliases": ["Thăng Long"], "documents": [f"doc_{proj_id}_1"]},
        {"id": f"n_{proj_id}_3", "name": "Văn Miếu", "kind": "Di tích", "aliases": [], "documents": [f"doc_{proj_id}_2"]},
        {"id": f"n_{proj_id}_4", "name": "Chùa Diên Hựu", "kind": "Di tích", "aliases": ["Diên Hựu Tự"], "documents": [f"doc_{proj_id}_2"]},
    ]
    edges = []
    for i in range(edge_count):
        rel = "tọa lạc tại" if i % 2 == 0 else ("nằm ở" if i == 1 else "gắn với")
        src = f"n_{proj_id}_1" if i == 0 else (f"n_{proj_id}_3" if i % 3 == 0 or i == 4 else f"n_{proj_id}_1")
        tgt = f"n_{proj_id}_2"
        if i == 2:
            ev = "Độc bản Một Cột."
        elif i % 2 == 0:
            ev = "Chùa Một Cột tọa lạc tại Hà Nội."
        else:
            ev = "Văn Miếu cũng nằm tại Hà Nội từ thời Lý."
        edges.append(
            {
                "id": f"e_{proj_id}_{i}",
                "source": src,
                "relation": rel,
                "target": tgt,
                "evidence": ev,
                "doc_id": f"doc_{proj_id}_1",
                "doc_name": f"{name.lower()}_doc_1.txt",
                "chunk_number": 1,
                "status": STATUS_APPROVED if i % 4 == 0 else STATUS_PENDING,
            }
        )
    proj["edges"] = edges

    proposals = []
    for i in range(prop_count):
        proposals.append(
            {
                "id": f"prop_{proj_id}_{i}",
                "kind": "entity_types",
                "name": "Đặc_biệt_loại_0" if i == 0 else f"Loại đề xuất {i}",
                "canonical_name": "Đặc_biệt_loại_0" if i == 0 else f"Loại đề xuất {i}",
                "status": "pending",
                "definition": f"Định nghĩa mẫu {i}",
                "doc_ids": [f"doc_{proj_id}_1"],
                "candidate_target": "Di tích",
                "score": 0.85,
            }
        )
    proj["schema_proposals"] = proposals
    return proj


class TestFrontendStateSync(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tmp.name)
        self.json_repo = JsonProjectRepository(self.temp_path / "projects")
        self.sqlite_repo = SQLiteProjectRepository(self.temp_path / "test.db")
        self.vector_repo = VectorIndexRepository(index_root=self.temp_path / "vectors")
        self.container = AppContainer(
            json_repo=self.json_repo,
            sqlite_repo=self.sqlite_repo,
            vector_repo=self.vector_repo,
        )
        self.facade = KGStudioFacade(
            json_repo=self.json_repo,
            sqlite_repo=self.sqlite_repo,
            vector_repo=self.vector_repo,
        )
        self.comp = FrontendComposition(container=self.container, facade=self.facade)
        self._prev_container = reset_container(self.container)
        self._prev_facade = reset_facade(self.facade)
        self._prev_comp = frontend_composition._COMPOSITION
        frontend_composition._COMPOSITION = self.comp
        self._prev_client = frontend_client.reset_client(None)
        self._env_patcher = patch.dict(
            os.environ,
            {
                "KG_STUDIO_PROJECTS_DIR": str(self.temp_path / "projects"),
                "KG_STUDIO_SECRETS_FILE": str(self.temp_path / ".secrets.toml"),
            },
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()
        frontend_client.reset_client(self._prev_client)
        frontend_composition._COMPOSITION = self._prev_comp
        reset_facade(self._prev_facade)
        reset_container(self._prev_container)
        self.tmp.cleanup()

    def test_app_sidebar_nav_project_switch_and_create(self) -> None:
        proj_a = _build_rich_project("AlphaProj", "proj_alpha", mode=MODE_FIXED, edge_count=4, prop_count=2)
        proj_b = _build_rich_project("BetaProj", "proj_beta", mode=MODE_EDC_PLUS_R, edge_count=4, prop_count=2)
        self.json_repo.save_project(proj_a)
        self.json_repo.save_project(proj_b)

        with capture_streamlit_state_warnings() as warnings:
            app_path = str(Path(__file__).resolve().parent.parent / "frontend" / "app.py")
            at = AppTest.from_file(app_path, default_timeout=15)
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(at.selectbox(key="sb_select_project").value, "AlphaProj")
            self.assertEqual(at.radio(key="sb_nav_steps_radio").value, 0)

            # 1. Nút nhảy sang Bước 2 ở Sidebar
            at.button(key="sb_btn_goto_llm_setup").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.radio(key="sb_nav_steps_radio").value, 1)
            at.run()
            self.assertEqual(at.radio(key="sb_nav_steps_radio").value, 1)

            # 2. Chọn trực tiếp radio sidebar sang Bước 4 (Rà soát & Chuẩn hóa, index 3)
            at.radio(key="sb_nav_steps_radio").set_value(3).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.radio(key="sb_nav_steps_radio").value, 3)

            # 3. Đổi dự án trên sidebar
            at.selectbox(key="sb_select_project").set_value("BetaProj").run()
            self.assertFalse(at.exception)
            self.assertEqual(at.selectbox(key="sb_select_project").value, "BetaProj")

            # 4. Tạo dự án mới từ sidebar -> chọn ngay dự án mới và xóa trắng ô nhập tên
            at.text_input(key="sb_new_project_name").set_value("GammaProj").run()
            at.button(key="sb_btn_create_project").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.selectbox(key="sb_select_project").value, "GammaProj")
            self.assertEqual(at.text_input(key="sb_new_project_name").value, "")

        _assert_no_session_state_warnings(self, warnings)

    def test_curation_hub_subtabs_action_cards_and_entity_submodes(self) -> None:
        proj = _build_rich_project("HubProj", "proj_hub", mode=MODE_EDC_PLUS_R, edge_count=6, prop_count=4)
        self.json_repo.save_project(proj)

        script = """
import streamlit as st
from backend.facade import get_facade
from frontend.pages.p04_curation_hub import render_curation_hub_page
from frontend.state.session import (
    get_active_curation_section,
    get_curation_section_state,
    navigate_to_edc_proposal_from_curation,
    return_to_curation_from_edc,
)

proj = get_facade().load_project("HubProj")
if st.session_state.pop("_test_jump_edc", False):
    navigate_to_edc_proposal_from_curation(proj, proposal_id="prop_proj_hub_0", node_id="n_proj_hub_1", section="entities")
if st.session_state.pop("_test_return_cur", False):
    return_to_curation_from_edc(proj)

render_curation_hub_page(proj)
st.session_state["_cap_sec"] = get_active_curation_section(proj)
st.session_state["_cap_ent_mode"] = get_curation_section_state(proj, "entities").get("submode")
"""
        with capture_streamlit_state_warnings() as warnings:
            at = AppTest.from_string(script)
            at.run()
            self.assertFalse(at.exception)

            # Action card -> Quan hệ & Bằng chứng
            at.button(key="btn_act_goto_edges").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["_cap_sec"], "edges")
            self.assertEqual(at.radio(key="curation_hub_radio_subtab").value, "edges")
            at.run()
            self.assertEqual(at.radio(key="curation_hub_radio_subtab").value, "edges")

            # Action card -> Hồ sơ thực thể -> đổi submode sang Gộp thực thể -> quay lại Danh sách -> Lọc quan hệ theo thực thể
            at.button(key="btn_act_goto_entities_list").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["_cap_sec"], "entities")
            self.assertEqual(at.radio(key="curation_hub_radio_subtab").value, "entities")
            sub_opts = list(at.radio(key="hub_entity_submode_radio").options)
            self.assertEqual(len(sub_opts), 2)
            list_label, merge_label = sub_opts[0], sub_opts[1]
            self.assertEqual(at.radio(key="hub_entity_submode_radio").value, list_label)

            at.radio(key="hub_entity_submode_radio").set_value(merge_label).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["_cap_sec"], "merge")
            self.assertEqual(at.radio(key="hub_entity_submode_radio").value, merge_label)

            # Đổi radio con sang Danh sách thực thể -> Lọc quan hệ theo thực thể tập trung
            at.radio(key="hub_entity_submode_radio").set_value(list_label).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["_cap_sec"], "entities")
            self.assertEqual(at.radio(key="hub_entity_submode_radio").value, list_label)
            at.button(key="btn_ent_view_edges").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.radio(key="curation_hub_radio_subtab").value, "edges")

            # Nhảy sang Đề xuất EDC rồi Quay lại từ context
            at.session_state["_test_jump_edc"] = True
            at.run()
            self.assertEqual(at.radio(key="curation_hub_radio_subtab").value, "schema")
            at.button(key="btn_hub_return_curation").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.radio(key="curation_hub_radio_subtab").value, "entities")

        _assert_no_session_state_warnings(self, warnings)

    def test_curation_and_edc_tables_filters_pagination_shrink_and_single_save(self) -> None:
        proj = _build_rich_project("TableProj", "proj_tbl", mode=MODE_EDC_PLUS_R, edge_count=30, prop_count=60)
        self.json_repo.save_project(proj)

        script = """
from backend.facade import get_facade
from frontend.pages.p04_curation_hub import render_curation_hub_page

proj = get_facade().load_project("TableProj")
render_curation_hub_page(proj, default_tab="edges")
"""
        with capture_streamlit_state_warnings() as warnings:
            at = AppTest.from_string(script, default_timeout=10)
            at.run()
            self.assertFalse(at.exception)

            # Trang 2 của bảng quan hệ (30 cạnh, page_size mặc định 25 -> 2 trang)
            at.number_input(key="cur_edge_page_num").set_value(2).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.number_input(key="cur_edge_page_num").value, 2)

            # Đổi page_size xuống 10 -> reset về trang 1 cleanly
            at.selectbox(key="cur_edge_page_size").set_value(10).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.number_input(key="cur_edge_page_num").value, 1)
            at.number_input(key="cur_edge_page_num").set_value(3).run()
            self.assertEqual(at.number_input(key="cur_edge_page_num").value, 3)

            # Lọc hẹp chỉ còn 1 dòng -> trang tự clamp về 1, không StreamlitValueAboveMaxError
            at.text_input(key="cur_edge_f_search").set_value("Độc bản Một Cột").run()
            self.assertFalse(at.exception)
            self.assertEqual(at.number_input(key="cur_edge_page_num").value, 1)

            # Reset bộ lọc trong 1 lần bấm
            at.button(key="cur_edge_btn_reset_filters").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.text_input(key="cur_edge_f_search").value, "")

            # Chọn trang hiện tại và bỏ chọn
            at.button(key="cur_edge_btn_sel_page").click().run()
            self.assertFalse(at.exception)
            at.button(key="cur_edge_btn_clear_sel").click().run()
            self.assertFalse(at.exception)

            # Lưu chỉnh sửa 1 cạnh ở inspector phải cập nhật dữ liệu và đồng bộ lại widget
            save_btns = [b for b in at.button if b.key and b.key.startswith("btn_save_single_edge_")]
            self.assertTrue(save_btns)
            edge_id = save_btns[0].key.removeprefix("btn_save_single_edge_")
            at.selectbox(key=f"single_edge_status_{edge_id}").set_value(STATUS_APPROVED)
            at.text_input(key=f"single_edge_note_{edge_id}").set_value("Đã kiểm chứng AppTest")
            at.button(key=f"btn_save_single_edge_{edge_id}").click().run()
            self.assertFalse(at.exception)
            reloaded = self.json_repo.load_project("TableProj")
            saved_edge = next(e for e in reloaded["edges"] if e["id"] == edge_id)
            self.assertEqual(saved_edge["status"], STATUS_APPROVED)
            self.assertEqual(saved_edge["review_note"], "Đã kiểm chứng AppTest")

            # Chuyển sang Đề xuất EDC: test pagination shrink & reset filter (60 đề xuất -> >=2 trang)
            at.radio(key="curation_hub_radio_subtab").set_value("schema").run()
            self.assertFalse(at.exception)
            at.selectbox(key="flt_psize_entity_types").set_value(20).run()
            at.number_input(key="edc_entity_types_page_num").set_value(2).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.number_input(key="edc_entity_types_page_num").value, 2)

            at.text_input(key="flt_search_entity_types").set_value("Đặc_biệt_loại_0").run()
            self.assertFalse(at.exception)
            self.assertFalse(any(ni.key == "edc_entity_types_page_num" for ni in at.number_input))

            at.button(key="flt_btn_reset_entity_types").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.text_input(key="flt_search_entity_types").value, "")
            self.assertEqual(at.number_input(key="edc_entity_types_page_num").value, 1)

        _assert_no_session_state_warnings(self, warnings)

    def test_p02_catalogs_gazetteer_and_prompt_editor_state_sync(self) -> None:
        proj = _build_rich_project("SetupProj", "proj_setup", mode=MODE_EDC_PLUS_R, edge_count=2, prop_count=1)
        self.json_repo.save_project(proj)

        script = """
from backend.facade import get_facade
from frontend.pages.p02_catalogs_prompts import render_catalogs_prompts_page

proj = get_facade().load_project("SetupProj")
render_catalogs_prompts_page(proj)
"""
        with capture_streamlit_state_warnings() as warnings:
            at = AppTest.from_string(script)
            at.run()
            self.assertFalse(at.exception)

            # Kiểm tra nhãn st.tabs tĩnh, không chứa bộ đếm động
            tab_labels = [t.label for t in at.tabs]
            self.assertTrue(tab_labels)
            self.assertTrue(all("Loại thực thể" not in lbl or "(" not in lbl for lbl in tab_labels))

            # Kiểm tra prompt editor: sửa -> hủy nháp -> lưu 2 phiên bản -> chọn lịch sử -> khôi phục
            mode = MODE_EDC_PLUS_R
            txt_key = f"txt_prompt_editor_proj_setup_{mode}"
            note_key = f"txt_note_proj_setup_{mode}"
            orig_prompt = at.text_area(key=txt_key).value

            at.text_area(key=txt_key).set_value(orig_prompt + "\n# NHAP TAM THOI").run()
            at.button(key=f"btn_discard_draft_proj_setup_{mode}").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.text_area(key=txt_key).value, orig_prompt)

            at.text_area(key=txt_key).set_value("Prompt phiên bản 1 cho kiểm thử {text}").run()
            at.text_input(key=note_key).set_value("v1 test")
            at.button(key=f"btn_save_ver_proj_setup_{mode}").click().run()
            self.assertFalse(at.exception)

            at.text_area(key=txt_key).set_value("Prompt phiên bản 2 cho kiểm thử {text}").run()
            at.text_input(key=note_key).set_value("v2 test")
            at.button(key=f"btn_save_ver_proj_setup_{mode}").click().run()
            self.assertFalse(at.exception)

            hist_sel = at.selectbox(key=f"sb_hist_ver_proj_setup_{mode}")
            self.assertGreaterEqual(len(hist_sel.options), 2)
            # Chọn lại bản v1 (phần tử thứ 2 trong danh sách mới-đến-cũ)
            older_idx = hist_sel.options[1]
            at.selectbox(key=f"sb_hist_ver_proj_setup_{mode}").set_value(older_idx).run()
            self.assertFalse(at.exception)
            hist_text_areas = [ta for ta in at.text_area if ta.key and ta.key.startswith(f"txt_hist_content_proj_setup_{mode}_")]
            self.assertTrue(hist_text_areas)
            self.assertIn("Prompt phiên bản 1", hist_text_areas[0].value)

            # Bật/tắt xem diff
            at.button(key=f"btn_diff_ver_proj_setup_{mode}").click().run()
            self.assertFalse(at.exception)

            # Khôi phục bản v1 thành bản đang hoạt động -> editor chính cập nhật ngay
            at.button(key=f"btn_restore_ver_proj_setup_{mode}").click().run()
            self.assertFalse(at.exception)
            self.assertIn("Prompt phiên bản 1", at.text_area(key=txt_key).value)

            # Bấm lưu danh mục không phát sinh warning
            at.button(key="btn_save_catalogs").click().run()
            self.assertFalse(at.exception)

        _assert_no_session_state_warnings(self, warnings)

    def test_p03_p05_and_merge_tabs_controls_clean_sync(self) -> None:
        proj = _build_rich_project("OpsProj", "proj_ops", mode=MODE_EDC_PLUS_R, edge_count=6, prop_count=1)
        self.json_repo.save_project(proj)

        script = """
import streamlit as st
from backend.facade import get_facade
from frontend.client import get_client
from frontend.components.merge.relation_tab import render_relation_merge_tab
from frontend.pages.p03_extraction import render_extraction_page
from frontend.pages.p05_graph_export import render_graph_export_page
from frontend.state.session import get_curation_section_state

proj = get_facade().load_project("OpsProj")
render_extraction_page(proj)
render_graph_export_page(proj)
render_relation_merge_tab(proj, get_client(), get_curation_section_state(proj, "merge"))
"""
        with capture_streamlit_state_warnings() as warnings:
            at = AppTest.from_string(script)
            at.run()
            self.assertFalse(at.exception)

            # P03: bỏ chọn hết -> chọn tất cả -> bỏ tích Trích xuất tất cả -> slider số luồng
            at.button(key="btn_clear_all_docs").click().run()
            self.assertFalse(at.button(key="btn_dry_run_one_chunk").disabled is False)
            at.button(key="btn_sel_all_docs").click().run()
            self.assertFalse(at.button(key="btn_dry_run_one_chunk").disabled)
            at.checkbox(key="p03_chk_extract_all").set_value(False).run()
            self.assertFalse(at.exception)
            self.assertTrue(any(ni.key == "p03_num_max_chunks_proj_ops" for ni in at.number_input))
            at.slider(key="p03_slider_workers").set_value(5).run()
            self.assertEqual(at.slider(key="p03_slider_workers").value, 5)

            # P05: chuyển radio nguồn đồ thị + nút Tối đa cạnh đồ thị
            at.radio(key="p05_graph_source_proj_ops").set_value("approved").run()
            self.assertFalse(at.exception)
            self.assertEqual(at.radio(key="p05_graph_source_proj_ops").value, "approved")
            at.button(key="p06_btn_max_edges_proj_ops").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.slider(key="p06_graph_max_edges_proj_ops").value, 2)

            # Merge relation tab: gộp thủ công xong phải dọn sạch nguồn & ô đích tùy chỉnh
            at.multiselect(key="manual_rel_merge_sources").set_value(["nằm ở"]).run()
            at.text_input(key="manual_rel_merge_target_input").set_value("tọa lạc tại").run()
            at.button(key="btn_apply_manual_rel_merge").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.multiselect(key="manual_rel_merge_sources").value, [])
            self.assertEqual(at.text_input(key="manual_rel_merge_target_input").value, "")

        _assert_no_session_state_warnings(self, warnings)


if __name__ == "__main__":
    unittest.main()
