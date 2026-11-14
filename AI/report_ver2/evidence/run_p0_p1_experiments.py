"""Bộ thực nghiệm kiểm chứng P0 + P1 và phiên bản CIDOC CRM song ngữ (môi trường cô lập hoàn toàn).

Chạy:
  .\\.venv-win\\Scripts\\python.exe AI\\report_ver2\\evidence\\run_p0_p1_experiments.py

Nguyên tắc an toàn:
  - Mọi thư mục JSON/SQLite/Vector chỉ tạo trong tempfile.TemporaryDirectory().
  - Tuyệt đối KHÔNG ghi đè data/projects/* hoặc config/catalogs/*.
  - Đọc data/projects/kg_hanoi_edc_r_a/project.json ở chế độ chỉ đọc rồi copy vào bộ nhớ/thư mục tạm.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.bootstrap import AppContainer  # noqa: E402
from backend.domain.catalogs.core import compute_project_revision  # noqa: E402
from backend.domain.curation.entities import duplicate_suggestions, mark_pair_not_duplicate  # noqa: E402
from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput  # noqa: E402
from backend.domain.extraction.registry import EngineRegistry  # noqa: E402
from backend.domain.graph.g_retriever import (  # noqa: E402
    answer_question_with_graph,
    evaluate_retrieval_methods,
    get_or_build_graph_index,
    retrieve_subgraph,
)
from backend.domain.graph.qa_generator import generate_training_qa_dataset  # noqa: E402
from backend.domain.graph.service import approved_graph  # noqa: E402
from backend.domain.schema_intelligence.aligner import TargetAligner  # noqa: E402
from backend.domain.schema_intelligence.retriever import SchemaRetriever  # noqa: E402
from backend.integrations.embedder_gateway import EmbedderGateway  # noqa: E402
from backend.integrations.llm.gateway import LLMGateway  # noqa: E402
from backend.integrations.llm.parsing import pick_choice_letter  # noqa: E402
from backend.integrations.neo4j_gateway import Neo4jGateway  # noqa: E402
from backend.modules.graph_qa.application.service import GraphQAApplicationService  # noqa: E402
from backend.repositories.json_repo import JsonProjectRepository, empty_project  # noqa: E402
from backend.repositories.sqlite_repo import SQLiteProjectRepository  # noqa: E402
from backend.repositories.vector_repo import VectorIndexRepository  # noqa: E402
from shared.catalog_utils import (  # noqa: E402
    apply_relations,
    catalog_bytes,
    catalog_csv_bytes,
    parse_catalog,
    relation_catalog,
    validate_catalog,
)


def apply_entity_types(project: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    project["entity_types"] = validate_catalog(rows, "entity_types")


def entity_type_catalog(project: dict[str, Any]) -> list[dict[str, Any]]:
    return validate_catalog(project.get("entity_types", []), "entity_types")
from shared.constants import (  # noqa: E402
    MODE_EDC_PLUS_R,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from shared.prompt_templates import (  # noqa: E402
    PASSAGE_TEMPLATE_VERSION,
    format_catalog_passage,
    format_sr_query,
    should_use_e5_instruct,
)
from shared.schemas.project import EDCPlusRSettingsDTO  # noqa: E402

EVIDENCE_DIR = Path(__file__).resolve().parent
STARTER_DIR = EVIDENCE_DIR / "cidoc_starter"
OUT_JSON = EVIDENCE_DIR / "p0_p1_experiments_results.json"

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_PROVIDER = "Ollama (Local)"
OLLAMA_CHAT_MODEL = "qwen3.5:4b"
OLLAMA_EMBED_MODEL = "ollama:bge-m3"


def build_bilingual_cidoc_catalog() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bộ danh mục CIDOC CRM v7.1.3 song ngữ chuẩn hóa cho miền Di sản Văn hóa Việt Nam."""
    entity_types = [
        {"name": "E1_CRM_Entity", "description": "Thực thể tổng quát trong miền CIDOC CRM.", "definition": "Lớp gốc bao trùm mọi thực thể có thể nhận diện và mô tả trong hồ sơ di sản."},
        {"name": "E2_Temporal_Entity", "description": "Thực thể thời gian (thời kỳ, sự kiện, trạng thái).", "definition": "Các hiện tượng xảy ra trong một khoảng thời gian xác định."},
        {"name": "E4_Period", "description": "Thời kỳ lịch sử, triều đại hoặc giai đoạn văn hóa.", "definition": "Tập hợp các hiện tượng gắn với triều đại, kỷ nguyên hoặc thời kỳ văn hóa - lịch sử."},
        {"name": "E5_Event", "description": "Sự kiện lịch sử, nghi lễ hoặc biến cố tự nhiên.", "definition": "Biến cố làm thay đổi trạng thái của sự vật, con người hoặc địa điểm tại một thời điểm."},
        {"name": "E7_Activity", "description": "Hoạt động có chủ đích của con người hoặc tổ chức.", "definition": "Hành động được thực hiện có mục đích bởi một hay nhiều tác nhân (E39_Actor)."},
        {"name": "E12_Production", "description": "Quá trình xây dựng, đúc, tạc hoặc chế tác vật thể.", "definition": "Hoạt động tạo mới hoặc thi công công trình kiến trúc, hiện vật, bia đá."},
        {"name": "E18_Physical_Thing", "description": "Vật thể vật chất hữu hình.", "definition": "Các vật thể hoặc tổ hợp vật chất tồn tại trong không gian vật lý."},
        {"name": "E21_Person", "description": "Cá nhân con người (vua, danh nhân, nghệ nhân, kiến trúc sư).", "definition": "Nhân vật lịch sử hoặc cá nhân cụ thể được nhắc tên trong tài liệu."},
        {"name": "E22_Human-Made_Object", "description": "Công trình hoặc hiện vật do con người tạo tác (chùa, đền, bia, chuông).", "definition": "Đơn vị kiến trúc hoặc đồ vật độc lập có ranh giới vật chất rõ ràng do con người chế tạo."},
        {"name": "E24_Physical_Human-Made_Thing", "description": "Thực thể vật chất nhân tạo tổng quát.", "definition": "Bao gồm mọi công trình, hiện vật, quần thể di tích do con người xây dựng hoặc cải biến."},
        {"name": "E25_Human-Made_Feature", "description": "Bộ phận gắn liền công trình hoặc dấu tích kiến trúc (bia, cổng, ban thờ).", "definition": "Đặc trưng kiến trúc nhân tạo không tách rời hoặc gắn cố định trên thực thể lớn hơn."},
        {"name": "E28_Conceptual_Object", "description": "Đối tượng khái niệm, tư liệu tinh thần hoặc giá trị phi vật thể.", "definition": "Sản phẩm trí tuệ phi vật chất như bài văn bia, truyền thuyết, lễ hội, quy chế."},
        {"name": "E31_Document", "description": "Tài liệu, sắc phong, thần tích, văn bản lưu trữ.", "definition": "Tư liệu chứa thông tin ghi chép hoặc minh chứng về thực thể di sản khác."},
        {"name": "E33_Linguistic_Object", "description": "Văn bản, câu đối, minh văn hoặc tác phẩm ngôn ngữ.", "definition": "Nội dung ngôn ngữ xác định bằng chữ Hán, Nôm, Việt, Pháp..."},
        {"name": "E35_Title", "description": "Tiêu đề tác phẩm, mỹ hiệu hoặc sắc phong.", "definition": "Tên gọi mang tính nhan đề hoặc danh hiệu chính thức được ban cho thực thể."},
        {"name": "E39_Actor", "description": "Tác nhân (cá nhân hoặc tổ chức/triều đình có năng lực hành động).", "definition": "Chủ thể có khả năng thực hiện hoạt động hoặc nắm quyền sở hữu, quản lý."},
        {"name": "E41_Appellation", "description": "Tên gọi, tên húy, tên tự, tên hiệu hoặc tên dân gian.", "definition": "Chuỗi ký hiệu dùng để gọi hoặc định danh một thực thể cụ thể."},
        {"name": "E52_Time-Span", "description": "Mốc thời gian, năm, niên hiệu hoặc giai đoạn lịch sử.", "definition": "Khoảng thời gian trừu tượng được xác định bởi năm bắt đầu/kết thúc hoặc niên đại."},
        {"name": "E53_Place", "description": "Địa điểm địa lý, địa danh hành chính hoặc vị trí không gian.", "definition": "Vùng hoặc tọa độ không gian vật lý (làng, xã, quận, kinh đô, núi, sông)."},
        {"name": "E54_Dimension", "description": "Kích thước, chiều cao, diện tích hoặc số lượng đo đạc.", "definition": "Đại lượng đo lường định lượng (mét, ha, tấn) của một vật thể hoặc khu vực."},
        {"name": "E55_Type", "description": "Phân loại khái niệm, phong cách kiến trúc hoặc hạng xếp di tích.", "definition": "Thuật ngữ phân loại (ví dụ: di tích quốc gia đặc biệt, kiến trúc thời Lê)."},
        {"name": "E57_Material", "description": "Chất liệu cấu thành (đá xanh, gỗ lim, đồng, gốm sứ).", "definition": "Vật liệu dùng để xây dựng công trình hoặc chế tác hiện vật."},
        {"name": "E65_Creation", "description": "Hoạt động sáng tác văn học, bài minh, thiết kế tinh thần.", "definition": "Quá trình tạo ra đối tượng khái niệm như văn bia, thơ văn, chiếu chỉ."},
        {"name": "E67_Birth", "description": "Sự kiện ra đời của nhân vật lịch sử.", "definition": "Biến cố đánh dấu sự sinh thành của một cá nhân (E21_Person)."},
        {"name": "E69_Death", "description": "Sự kiện qua đời/mất của nhân vật lịch sử.", "definition": "Biến cố đánh dấu thời điểm và địa điểm mất của một cá nhân."},
        {"name": "E73_Information_Object", "description": "Nội dung thông tin mang tính tái bản hoặc bản đồ, hồ sơ số.", "definition": "Đối tượng thông tin độc lập với vật mang vật lý."},
        {"name": "E74_Group", "description": "Tổ chức, triều đại, hội đồng, ban quản lý hoặc cộng đồng cư dân.", "definition": "Tập hợp hai hay nhiều cá nhân cùng hoạt động hoặc quản lý di tích."},
        {"name": "E78_Curated_Holding", "description": "Bộ sưu tập hiện vật hoặc kho lưu trữ bảo tàng.", "definition": "Tập hợp các hiện vật được thu thập, bảo quản và quản lý có hệ thống."},
        {"name": "E89_Propositional_Object", "description": "Mệnh đề, tín ngưỡng, nhân vật được phụng thờ hoặc tư tưởng.", "definition": "Nội dung tinh thần có thể đúng/sai hoặc đối tượng của sự thờ phụng, ghi nhớ."},
        {"name": "E92_Spacetime_Volume", "description": "Vùng không-thời gian gắn với lịch sử tồn tại của di tích.", "definition": "Phạm vi kết hợp giữa không gian tồn tại và quãng thời gian tương ứng."},
    ]

    relations = [
        {"name": "P1_is_identified_by", "description": "Được định danh bằng tên gọi.", "definition": "Thực thể được gọi hoặc biết đến qua tên gọi/tên chữ (E41_Appellation).", "domain": "E1_CRM_Entity", "range": "E41_Appellation", "aliases": ["có tên gọi là", "được gọi là", "tên chữ là"]},
        {"name": "P2_has_type", "description": "Có phân loại / hạng di tích.", "definition": "Xếp loại thực thể theo cấp di tích, loại hình kiến trúc hoặc phong cách.", "domain": "E1_CRM_Entity", "range": "E55_Type", "aliases": ["thuộc loại", "được xếp hạng", "có cấp di tích"]},
        {"name": "P3_has_note", "description": "Có ghi chú mô tả.", "definition": "Ghi chú ngắn gọn mô tả đặc điểm của thực thể.", "domain": "E1_CRM_Entity", "range": "E33_Linguistic_Object", "aliases": ["có ghi chú"]},
        {"name": "P4_has_time-span", "description": "Có mốc thời gian hoặc niên đại.", "definition": "Sự kiện, quá trình xây dựng hoặc thời kỳ diễn ra trong mốc thời gian cụ thể.", "domain": "E2_Temporal_Entity", "range": "E52_Time-Span", "aliases": ["vào năm", "xây dựng vào thời gian", "có niên đại", "diễn ra vào"]},
        {"name": "P5_consists_of", "description": "Bao gồm giai đoạn con.", "definition": "Thời kỳ lịch sử lớn bao gồm các giai đoạn ngắn hơn.", "domain": "E4_Period", "range": "E4_Period", "aliases": ["gồm thời kỳ"]},
        {"name": "P7_took_place_at", "description": "Sự kiện hoặc hoạt động diễn ra tại địa điểm.", "definition": "Liên kết một sự kiện, lễ hội, khởi nghĩa hoặc quá trình xây dựng với nơi diễn ra.", "domain": "E4_Period", "range": "E53_Place", "aliases": ["diễn ra tại", "tổ chức tại", "xảy ra ở"]},
        {"name": "P8_took_place_on_or_within", "description": "Diễn ra ngay trên hoặc bên trong công trình vật chất.", "definition": "Sự kiện diễn ra bên trong một tòa điện, sân, di tích cụ thể.", "domain": "E4_Period", "range": "E18_Physical_Thing", "aliases": ["diễn ra trong công trình"]},
        {"name": "P9_consists_of", "description": "Thời kỳ hoặc sự kiện gồm sự kiện thành phần.", "definition": "Tách sự kiện tổng thể thành các hoạt động nhỏ hơn.", "domain": "E4_Period", "range": "E4_Period", "aliases": ["bao gồm sự kiện"]},
        {"name": "P10_falls_within", "description": "Nằm trong thời kỳ hoặc triều đại.", "definition": "Sự kiện hoặc hoạt động xảy ra trong bối cảnh một thời kỳ lịch sử rộng hơn.", "domain": "E4_Period", "range": "E4_Period", "aliases": ["thuộc triều đại", "nằm trong giai đoạn", "dưới triều"]},
        {"name": "P11_had_participant", "description": "Có cá nhân hoặc tổ chức tham gia.", "definition": "Ghi nhận tác nhân tham gia một sự kiện lịch sử hoặc lễ hội.", "domain": "E5_Event", "range": "E39_Actor", "aliases": ["có người tham gia", "tham dự"]},
        {"name": "P12_occurred_in_the_presence_of", "description": "Sự kiện gắn với hiện diện của vật thể hoặc con người.", "definition": "Sự kiện diễn ra trước chứng kiến hoặc sự hiện diện của nhân vật/hiện vật.", "domain": "E5_Event", "range": "E18_Physical_Thing", "aliases": ["gắn với sự hiện diện của"]},
        {"name": "P14_carried_out_by", "description": "Hoạt động do cá nhân hoặc tổ chức thực hiện.", "definition": "Xác định chủ thể (vua, nghệ nhân, ban quản lý) thực hiện hoạt động xây dựng, trùng tu, sáng lập.", "domain": "E7_Activity", "range": "E39_Actor", "aliases": ["do ai thực hiện", "do ai chủ trì", "được thực hiện bởi", "do vua cho xây"]},
        {"name": "P15_was_influenced_by", "description": "Hoạt động chịu ảnh hưởng bởi tư tưởng hoặc công trình.", "definition": "Chịu ảnh hưởng nghệ thuật, phong thủy hoặc truyền thống văn hóa.", "domain": "E7_Activity", "range": "E1_CRM_Entity", "aliases": ["chịu ảnh hưởng bởi"]},
        {"name": "P16_used_specific_object", "description": "Sử dụng vật thể hoặc tư liệu cụ thể.", "definition": "Hoạt động sử dụng hiện vật, bản vẽ hoặc vật liệu xác định.", "domain": "E7_Activity", "range": "E18_Physical_Thing", "aliases": ["sử dụng vật thể"]},
        {"name": "P17_was_motivated_by", "description": "Được thúc đẩy hoặc nhân dịp sự kiện.", "definition": "Hoạt động được thực hiện vì mục đích tưởng niệm hoặc nhân biến cố lịch sử.", "domain": "E7_Activity", "range": "E1_CRM_Entity", "aliases": ["bắt nguồn từ", "nhân dịp"]},
        {"name": "P19_was_intended_use_of", "description": "Mục đích sử dụng dự kiến.", "definition": "Công năng ban đầu (thờ phụng, học tập, phòng thủ) của công trình.", "domain": "E7_Activity", "range": "E55_Type", "aliases": ["dùng để", "mục đích là"]},
        {"name": "P20_had_specific_purpose", "description": "Có mục đích hướng tới sự kiện.", "definition": "Hoạt động nhằm chuẩn bị cho sự kiện hoặc nghi lễ xác định.", "domain": "E7_Activity", "range": "E5_Event", "aliases": ["nhằm mục đích"]},
        {"name": "P43_has_dimension", "description": "Có kích thước hoặc diện tích đo đạc.", "definition": "Liên kết công trình, khu đất hoặc hiện vật với số đo diện tích/chiều cao.", "domain": "E18_Physical_Thing", "range": "E54_Dimension", "aliases": ["có kích thước", "có diện tích", "cao"]},
        {"name": "P44_has_condition", "description": "Có tình trạng bảo tồn.", "definition": "Tình trạng hư hại, nguyên vẹn hoặc đã được bảo tồn của di tích.", "domain": "E18_Physical_Thing", "range": "E55_Type", "aliases": ["tình trạng hiện nay"]},
        {"name": "P45_consists_of", "description": "Được làm từ chất liệu.", "definition": "Xác định vật liệu cấu tạo nên công trình hay hiện vật (đá xanh, gỗ lim, đồng).", "domain": "E18_Physical_Thing", "range": "E57_Material", "aliases": ["được làm bằng", "có chất liệu", "làm từ"]},
        {"name": "P46_is_composed_of", "description": "Cấu thành từ các hạng mục kiến trúc con.", "definition": "Di tích lớn bao gồm các hạng mục như tam quan, điện thờ, gác chuông, vườn bia.", "domain": "E18_Physical_Thing", "range": "E18_Physical_Thing", "aliases": ["bao gồm hạng mục", "gồm có bộ phận", "có thành phần"]},
        {"name": "P48_has_preferred_identifier", "description": "Có mã định danh hoặc số hiệu ưu tiên.", "definition": "Mã hiệu kiểm kê, số lưu trữ chính thức của di sản.", "domain": "E1_CRM_Entity", "range": "E41_Appellation", "aliases": ["có mã định danh"]},
        {"name": "P49_has_former_or_current_keeper", "description": "Từng hoặc đang có đơn vị bảo quản, trông coi.", "definition": "Đơn vị bảo tàng, ban quản lý hoặc cộng đồng trông nom di tích.", "domain": "E18_Physical_Thing", "range": "E39_Actor", "aliases": ["được trông coi bởi", "đơn vị lưu giữ"]},
        {"name": "P50_has_current_keeper", "description": "Hiện do đơn vị nào quản lý trực tiếp.", "definition": "Cơ quan hoặc cộng đồng đang quản lý hiện vật/di tích hiện nay.", "domain": "E18_Physical_Thing", "range": "E39_Actor", "aliases": ["hiện do quản lý", "ban quản lý hiện tại"]},
        {"name": "P51_has_former_or_current_owner", "description": "Từng hoặc đang thuộc quyền sở hữu của.", "definition": "Triều đại, gia tộc hoặc cơ quan sở hữu công trình/tư sản.", "domain": "E18_Physical_Thing", "range": "E39_Actor", "aliases": ["thuộc quyền sở hữu của"]},
        {"name": "P52_has_current_owner", "description": "Chủ sở hữu hiện tại.", "definition": "Cơ quan hoặc chủ thể sở hữu hợp pháp hiện nay.", "domain": "E18_Physical_Thing", "range": "E39_Actor", "aliases": ["chủ sở hữu hiện tại"]},
        {"name": "P53_has_former_or_current_location", "description": "Tọa lạc tại địa điểm hoặc vùng đất.", "definition": "Vị trí không gian cố định hoặc lịch sử của công trình, di tích và hiện vật vật chất.", "domain": "E18_Physical_Thing", "range": "E53_Place", "aliases": ["tọa lạc tại", "nằm tại", "đặt tại", "ở địa điểm"]},
        {"name": "P54_has_current_permanent_location", "description": "Vị trí đặt cố định hiện nay.", "definition": "Nơi lưu giữ thường xuyên hiện tại của hiện vật.", "domain": "E18_Physical_Thing", "range": "E53_Place", "aliases": ["hiện đặt tại"]},
        {"name": "P55_has_current_location", "description": "Vị trí hiện tại của hiện vật.", "definition": "Địa điểm hiện vật đang có mặt tại thời điểm ghi nhận.", "domain": "E18_Physical_Thing", "range": "E53_Place", "aliases": ["hiện đang ở"]},
        {"name": "P56_bears_feature", "description": "Mang bộ phận hoặc dấu tích gắn liền.", "definition": "Công trình mang trên mình bia đá, phù điêu, cổng tam quan.", "domain": "E18_Physical_Thing", "range": "E25_Human-Made_Feature", "aliases": ["mang dấu tích", "có gắn bộ phận"]},
        {"name": "P62_depicts", "description": "Mô tả, khắc họa hoặc tôn vinh hình tượng.", "definition": "Hiện vật/phù điêu khắc họa nhân vật, điển tích hoặc linh vật.", "domain": "E24_Physical_Human-Made_Thing", "range": "E1_CRM_Entity", "aliases": ["khắc họa", "miêu tả hình tượng"]},
        {"name": "P65_shows_visual_item", "description": "Hiển thị hoa văn hoặc biểu tượng thị giác.", "definition": "Bề mặt vật thể mang họa tiết, hoành phi, câu đối.", "domain": "E24_Physical_Human-Made_Thing", "range": "E28_Conceptual_Object", "aliases": ["có hoa văn", "mang biểu tượng"]},
        {"name": "P67_refers_to", "description": "Tài liệu hoặc sắc phong nhắc tới thực thể.", "definition": "Văn bản, bia ký, sử liệu đề cập đến nhân vật, di tích hoặc sự kiện.", "domain": "E89_Propositional_Object", "range": "E1_CRM_Entity", "aliases": ["đề cập tới", "ghi chép về", "nhắc đến"]},
        {"name": "P70_documents", "description": "Tư liệu ghi nhận bằng chứng về thực thể hoặc sự kiện.", "definition": "Văn kiện, sắc phong, bản vẽ ghi nhận chi tiết về lịch sử di tích.", "domain": "E31_Document", "range": "E1_CRM_Entity", "aliases": ["ghi chép tư liệu về", "minh chứng cho"]},
        {"name": "P72_has_language", "description": "Văn bản được viết bằng ngôn ngữ.", "definition": "Ngôn ngữ của minh văn hoặc tư liệu (chữ Hán, chữ Nôm, tiếng Việt).", "domain": "E33_Linguistic_Object", "range": "E55_Type", "aliases": ["viết bằng ngôn ngữ", "sử dụng chữ"]},
        {"name": "P74_has_current_or_former_residence", "description": "Nhân vật từng cư trú hoặc gắn bó tại địa điểm.", "definition": "Quê quán, nơi ở hoặc nơi làm việc gắn với nhân vật lịch sử.", "domain": "E39_Actor", "range": "E53_Place", "aliases": ["quê ở", "cư trú tại", "sinh sống ở"]},
        {"name": "P81_ongoing_throughout", "description": "Tồn tại liên tục trong suốt giai đoạn.", "definition": "Khoảng thời gian tối thiểu được xác nhận tồn tại xuyên suốt.", "domain": "E52_Time-Span", "range": "E52_Time-Span", "aliases": ["tồn tại suốt giai đoạn"]},
        {"name": "P82_at_some_time_within", "description": "Nằm trong khoảng thời gian xác định.", "definition": "Giới hạn trên/dưới của niên đại.", "domain": "E52_Time-Span", "range": "E52_Time-Span", "aliases": ["trong khoảng thời gian"]},
        {"name": "P89_falls_within", "description": "Địa điểm hành chính trực thuộc địa bàn rộng hơn.", "definition": "Phường/làng thuộc quận/huyện/tỉnh hoặc khu vực địa lý bao chứa.", "domain": "E53_Place", "range": "E53_Place", "aliases": ["trực thuộc địa bàn", "thuộc tỉnh", "thuộc quận", "nằm trong vùng"]},
        {"name": "P90_has_value", "description": "Có giá trị đo lường.", "definition": "Số đo định lượng cụ thể của kích thước.", "domain": "E54_Dimension", "range": "E54_Dimension", "aliases": ["có số đo", "có giá trị"]},
        {"name": "P91_has_unit", "description": "Có đơn vị đo.", "definition": "Đơn vị đo lường (mét, mẫu, héc-ta).", "domain": "E54_Dimension", "range": "E55_Type", "aliases": ["có đơn vị đo"]},
        {"name": "P94_has_created", "description": "Hoạt động sáng tác tạo ra tác phẩm/văn bia.", "definition": "Liên kết quá trình sáng tác (E65_Creation) với văn bản hoặc giá trị tinh thần được tạo thành.", "domain": "E65_Creation", "range": "E28_Conceptual_Object", "aliases": ["đã sáng tác ra", "soạn nên"]},
        {"name": "P98_brought_into_life", "description": "Sự kiện sinh ra nhân vật.", "definition": "Liên kết biến cố ra đời (E67_Birth) với nhân vật E21_Person.", "domain": "E67_Birth", "range": "E21_Person", "aliases": ["sinh ra"]},
        {"name": "P100_was_death_of", "description": "Sự kiện qua đời của nhân vật.", "definition": "Liên kết sự kiện mất (E69_Death) với nhân vật E21_Person.", "domain": "E69_Death", "range": "E21_Person", "aliases": ["là sự kiện mất của"]},
        {"name": "P102_has_title", "description": "Mang danh hiệu, sắc phong hoặc tiêu đề chính thức.", "definition": "Văn bản, tác phẩm hoặc di tích được ban mỹ hiệu/tiêu đề cụ thể.", "domain": "E73_Information_Object", "range": "E35_Title", "aliases": ["mang tiêu đề", "có mỹ hiệu"]},
        {"name": "P104_is_subject_to", "description": "Chịu quyền bảo hộ hoặc quy chế pháp lý.", "definition": "Công trình thuộc diện bảo vệ theo luật di sản hay sắc lệnh.", "domain": "E18_Physical_Thing", "range": "E28_Conceptual_Object", "aliases": ["thuộc quy chế"]},
        {"name": "P107_has_current_or_former_member", "description": "Nhóm hoặc triều đại có thành viên.", "definition": "Triều đại, tổ chức hoặc ban trị sự bao gồm các nhân vật thành viên.", "domain": "E74_Group", "range": "E39_Actor", "aliases": ["có thành viên là"]},
        {"name": "P107i_is_current_or_former_member_of", "description": "Nhân vật thuộc triều đại hoặc tổ chức.", "definition": "Cá nhân là thành viên của triều đại, hội đồng hoặc dòng họ.", "domain": "E39_Actor", "range": "E74_Group", "aliases": ["thuộc triều đại", "là thành viên của"]},
        {"name": "P108_has_produced", "description": "Quá trình tạo tác sản sinh ra công trình hoặc hiện vật.", "definition": "Liên kết sự kiện xây dựng/đúc tạo (E12_Production) với công trình hoặc hiện vật (E24).", "domain": "E12_Production", "range": "E24_Physical_Human-Made_Thing", "aliases": ["tạo tác ra", "xây dựng nên", "đúc nên"]},
        {"name": "P109_has_current_or_former_curator", "description": "Bộ sưu tập do tổ chức/người phụ trách quản lý.", "definition": "Chủ thể phụ trách giám tuyển và quản lý kho bảo tàng.", "domain": "E78_Curated_Holding", "range": "E39_Actor", "aliases": ["được phụ trách bởi"]},
        {"name": "P128_carries", "description": "Bề mặt vật thể mang nội dung văn bản hoặc chữ khắc.", "definition": "Bia đá, sắc phong vật lý mang bài văn bia hoặc thông tin ghi chép.", "domain": "E18_Physical_Thing", "range": "E73_Information_Object", "aliases": ["mang nội dung", "khắc bài văn", "lưu giữ văn bản"]},
        {"name": "P129_is_about", "description": "Nội dung hướng về chủ đề hoặc nhân vật được thờ.", "definition": "Tư liệu, lễ hội hoặc niềm tin hướng tới tôn vinh đối tượng cụ thể.", "domain": "E89_Propositional_Object", "range": "E1_CRM_Entity", "aliases": ["thờ phụng", "tôn vinh", "nói về"]},
        {"name": "P130_shows_features_of", "description": "Thể hiện đặc trưng giống với nguyên mẫu.", "definition": "Công trình phục dựng hoặc hiện vật mô phỏng theo phong cách gốc.", "domain": "E18_Physical_Thing", "range": "E18_Physical_Thing", "aliases": ["mô phỏng theo", "mang đặc điểm của"]},
        {"name": "P134_continued", "description": "Hoạt động tiếp nối hoạt động trước.", "definition": "Đợt trùng tu hoặc giai đoạn xây dựng tiếp theo nối tiếp đợt trước.", "domain": "E7_Activity", "range": "E7_Activity", "aliases": ["tiếp nối", "trùng tu tiếp"]},
        {"name": "P138_represents", "description": "Biểu trưng hoặc đại diện cho nhân vật/khái niệm.", "definition": "Pho tượng hoặc đồ thờ đại diện cho vị thần, danh nhân được thờ.", "domain": "E73_Information_Object", "range": "E1_CRM_Entity", "aliases": ["đại diện cho", "biểu trưng cho"]},
    ]
    return entity_types, relations


def run_exp1_catalog_roundtrip(entity_types: list[dict], relations: list[dict]) -> dict[str, Any]:
    """Exp 1: Round-trip CSV/JSON CIDOC CRM song ngữ giữ nguyên domain, range, aliases."""
    STARTER_DIR.mkdir(parents=True, exist_ok=True)
    et_csv = catalog_csv_bytes(entity_types, "entity_types")
    et_json = catalog_bytes(entity_types, "entity_types")
    rel_csv = catalog_csv_bytes(relations, "relations")
    rel_json = catalog_bytes(relations, "relations")

    # Lưu sẵn bộ mẫu song ngữ vào AI/report_ver2/evidence/cidoc_starter/ để tái sử dụng
    (STARTER_DIR / "cidoc_entity_types.csv").write_bytes(et_csv)
    (STARTER_DIR / "cidoc_entity_types.json").write_bytes(et_json)
    (STARTER_DIR / "cidoc_relations.csv").write_bytes(rel_csv)
    (STARTER_DIR / "cidoc_relations.json").write_bytes(rel_json)

    parsed_et_csv = parse_catalog(et_csv, "entity_types", filename="cidoc_entity_types.csv")
    parsed_rel_csv = parse_catalog(rel_csv, "relations", filename="cidoc_relations.csv")
    parsed_rel_json = parse_catalog(rel_json, "relations", filename="cidoc_relations.json")

    proj = empty_project("CIDOC_Roundtrip_Check")
    apply_entity_types(proj, parsed_et_csv)
    apply_relations(proj, parsed_rel_csv)

    et_loaded = entity_type_catalog(proj)
    rel_loaded = relation_catalog(proj)

    orig_rel_by_name = {r["name"]: r for r in relations}
    domain_matches = sum(1 for r in rel_loaded if r.get("domain") == orig_rel_by_name[r["name"]]["domain"])
    range_matches = sum(1 for r in rel_loaded if r.get("range") == orig_rel_by_name[r["name"]]["range"])
    alias_matches = sum(1 for r in rel_loaded if r.get("aliases") == orig_rel_by_name[r["name"]]["aliases"])
    sample_passage = format_catalog_passage(
        rel_loaded[26]["name"],  # P53_has_former_or_current_location
        rel_loaded[26]["description"],
        rel_loaded[26]["definition"],
        aliases=rel_loaded[26].get("aliases"),
        domain=rel_loaded[26].get("domain", ""),
        range=rel_loaded[26].get("range", ""),
    )

    return {
        "entity_types_count": len(et_loaded),
        "relations_count": len(rel_loaded),
        "json_relations_count": len(parsed_rel_json),
        "domain_preserved": f"{domain_matches}/{len(relations)}",
        "range_preserved": f"{range_matches}/{len(relations)}",
        "aliases_preserved": f"{alias_matches}/{len(relations)}",
        "passage_template_version": PASSAGE_TEMPLATE_VERSION,
        "sample_passage": sample_passage,
        "starter_dir": str(STARTER_DIR.relative_to(REPO_ROOT)).replace("\\", "/"),
    }


def _eval_sr_config(
    project: dict[str, Any],
    queries: list[tuple[str, str]],
    embedder: EmbedderGateway,
    vec_repo: VectorIndexRepository,
) -> dict[str, Any]:
    retriever = SchemaRetriever(vector_repo=vec_repo, embedder=embedder)
    t0 = time.perf_counter()
    # Warm index build
    retriever.retrieve_for_chunk(project, queries[0][0], top_k_relations=30, top_k_entity_types=10, embedder=embedder)
    index_and_first_ms = (time.perf_counter() - t0) * 1000.0

    r5 = r15 = r30 = 0
    mrr_sum = 0.0
    q_latencies: list[float] = []
    for q_text, gold_rel in queries:
        qt0 = time.perf_counter()
        res = retriever.retrieve_for_chunk(project, q_text, top_k_relations=30, top_k_entity_types=10, embedder=embedder)
        q_latencies.append((time.perf_counter() - qt0) * 1000.0)
        names = [it["name"] for it in res["relations"]]
        if gold_rel in names:
            rank = names.index(gold_rel) + 1
            mrr_sum += 1.0 / rank
            if rank <= 5:
                r5 += 1
            if rank <= 15:
                r15 += 1
            if rank <= 30:
                r30 += 1

    n = len(queries)
    return {
        "model_id": embedder.model_id,
        "dim": embedder.dim,
        "uses_e5_instruct": should_use_e5_instruct(embedder.model_id),
        "num_queries": n,
        "recall_at_5": round(r5 / n, 4),
        "recall_at_15": round(r15 / n, 4),
        "recall_at_30": round(r30 / n, 4),
        "mrr": round(mrr_sum / n, 4),
        "index_build_ms": round(index_and_first_ms, 1),
        "avg_query_ms": round(sum(q_latencies) / max(1, len(q_latencies)), 2),
    }


def run_exp2_schema_retrieval_bge_m3(entity_types: list[dict], relations: list[dict]) -> dict[str, Any]:
    """Exp 2: Đối sánh Schema Retriever (+R) trên danh mục CIDOC song ngữ: hybrid_vn vs bge-m3 (bare vs v2-domain-range)."""
    queries = [
        ("Văn Miếu Quốc Tử Giám tọa lạc tại phố Quốc Tử Giám, quận Đống Đa, Hà Nội.", "P53_has_former_or_current_location"),
        ("Chùa Một Cột được khởi công xây dựng vào năm 1049 dưới thời vua Lý Thái Tông.", "P4_has_time-span"),
        ("Lễ hội Gióng diễn ra tại đền Phù Đổng thuộc huyện Gia Lâm.", "P7_took_place_at"),
        ("Hoạt động trùng tu điện Thái Hòa do vua Minh Mạng trực tiếp chủ trì.", "P14_carried_out_by"),
        ("Tám mươi hai tấm bia Tiến sĩ được chế tác từ chất liệu đá xanh nguyên khối.", "P45_consists_of"),
        ("Khu di tích Hoàng thành Thăng Long bao gồm Đoan Môn, Điện Kính Thiên và Hậu Lâu.", "P46_is_composed_of"),
        ("Bia Vĩnh Lăng có chiều cao 2,79 mét và chiều rộng 1,94 mét.", "P43_has_dimension"),
        ("Hoàng thành Thăng Long từng có tên gọi chính thức là Đông Kinh trong thời Lê.", "P1_is_identified_by"),
        ("Đền Ngọc Sơn được Bộ Văn hóa xếp hạng là Di tích Quốc gia đặc biệt.", "P2_has_type"),
        ("Sắc phong triều Nguyễn ghi chép tư liệu về công lao của thần bản thổ.", "P70_documents"),
        ("Văn bia Văn Miếu khắc bằng chữ Hán cổ thời Lê sơ.", "P72_has_language"),
        ("Bia đá tại khu di tích mang trên mình nội dung bài ký ghi danh các tiến sĩ.", "P128_carries"),
        ("Lễ hội đền Cổ Loa tôn vinh đức vua An Dương Vương và truyền thuyết nỏ thần.", "P129_is_about"),
        ("Chùa Thầy nằm gắn liền với địa bàn huyện Quốc Oai, phía tây Hà Nội.", "P89_falls_within"),
        ("Bức phù điêu trên cổng Tam quan khắc họa hình tượng rồng chầu mặt nguyệt.", "P62_depicts"),
        ("Danh nhân Nguyễn Trãi từng có thời gian cư trú tại Côn Sơn và Thăng Long.", "P74_has_current_or_former_residence"),
        ("Hiện nay Bảo tàng Lịch sử Quốc gia là cơ quan đang quản lý trực tiếp chiếc trống đồng.", "P50_has_current_keeper"),
        ("Vua Lý Công Uẩn là thành viên sáng lập của Triều đại nhà Lý.", "P107i_is_current_or_former_member_of"),
        ("Tháp Rùa có gắn thêm bộ phận quả chuông đồng nhỏ và ô cửa vòm trên thân tháp.", "P56_bears_feature"),
        ("Quá trình đúc chuông Quy Điền đã tạo tác nên một trong An Nam tứ đại khí.", "P108_has_produced"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        proj_rich = empty_project("CIDOC_SR_Rich")
        proj_rich["project_id"] = "cidoc_sr_rich"
        apply_entity_types(proj_rich, entity_types)
        apply_relations(proj_rich, relations)

        # Bản bare không có domain, range, aliases để đo giá trị của v2-domain-range + aliases
        bare_rels = [{"name": r["name"], "description": r["description"], "definition": r["definition"]} for r in relations]
        proj_bare = empty_project("CIDOC_SR_Bare")
        proj_bare["project_id"] = "cidoc_sr_bare"
        apply_entity_types(proj_bare, entity_types)
        apply_relations(proj_bare, bare_rels)

        out: dict[str, Any] = {
            "prompt_e5_check": {
                "bge_m3_use_instruct": should_use_e5_instruct("ollama:bge-m3"),
                "bge_m3_sample_query": format_sr_query("vị trí xây dựng", use_instruct=should_use_e5_instruct("ollama:bge-m3")),
                "e5_large_use_instruct": should_use_e5_instruct("intfloat/multilingual-e5-large"),
            }
        }

        hybrid_emb = EmbedderGateway("hybrid_vn:default")
        out["hybrid_vn_rich"] = _eval_sr_config(proj_rich, queries, hybrid_emb, VectorIndexRepository(root / "vec_hyb"))

        try:
            bge_emb = EmbedderGateway(OLLAMA_EMBED_MODEL, base_url=OLLAMA_BASE_URL)
            # Quick smoke check
            _ = bge_emb.encode(format_sr_query("kiểm tra kết nối", use_instruct=should_use_e5_instruct(OLLAMA_EMBED_MODEL)))
            out["bge_m3_bare"] = _eval_sr_config(proj_bare, queries, bge_emb, VectorIndexRepository(root / "vec_bge_bare"))
            out["bge_m3_rich"] = _eval_sr_config(proj_rich, queries, bge_emb, VectorIndexRepository(root / "vec_bge_rich"))
            out["live_bge_m3_status"] = "ok"
        except Exception as exc:
            out["live_bge_m3_status"] = f"error: {exc}"

    return out


def run_exp3_live_verifier_and_fail_closed(entity_types: list[dict], relations: list[dict]) -> dict[str, Any]:
    """Exp 3: Target Alignment + Verifier sống (qwen3.5:4b) với ngữ cảnh [Domain -> Range] + Fail-Closed check."""
    base_proj = empty_project("CIDOC_Verifier_Test")
    base_proj["project_id"] = "cidoc_verifier"
    apply_entity_types(base_proj, entity_types)
    apply_relations(base_proj, relations)

    base_proj["nodes"] = [
        {"id": "n_chua", "name": "Chùa Một Cột", "kind": "Ngôi chùa cổ", "schema_proposal_ids": ["p_et_pagoda"]},
        {"id": "n_hl", "name": "Hà Nội", "kind": "Địa điểm hành chính", "schema_proposal_ids": ["p_et_place"]},
        {"id": "n_lehoi", "name": "Lễ hội Gióng", "kind": "Sự kiện văn hóa truyền thống", "schema_proposal_ids": ["p_et_event"]},
        {"id": "n_vua", "name": "Vua Lý Thái Tông", "kind": "Nhân vật lịch sử", "schema_proposal_ids": ["p_et_person"]},
        {"id": "n_da", "name": "đá xanh", "kind": "Vật liệu xây dựng", "schema_proposal_ids": ["p_et_material"]},
    ]
    base_proj["edges"] = [
        {
            "id": "e_loc",
            "source": "n_chua",
            "relation": "đóng tại địa bàn",
            "target": "n_hl",
            "evidence": "Chùa Một Cột đóng tại địa bàn Hà Nội.",
            "schema_proposal_ids": ["p_rel_loc"],
        },
        {
            "id": "e_evt",
            "source": "n_lehoi",
            "relation": "tổ chức ở nơi",
            "target": "n_hl",
            "evidence": "Lễ hội Gióng được tổ chức ở nơi địa bàn Hà Nội.",
            "schema_proposal_ids": ["p_rel_evt"],
        },
        {
            "id": "e_mat",
            "source": "n_chua",
            "relation": "chế tác bằng vật liệu",
            "target": "n_da",
            "evidence": "Bệ cột chùa được chế tác bằng vật liệu đá xanh.",
            "schema_proposal_ids": ["p_rel_mat"],
        },
        {
            "id": "e_worship",
            "source": "n_chua",
            "relation": "ghi nhớ tôn vinh",
            "target": "n_vua",
            "evidence": "Ngôi chùa ghi nhớ tôn vinh công đức vua Lý Thái Tông.",
            "schema_proposal_ids": ["p_rel_about"],
        },
    ]
    proposals = [
        {
            "id": "p_et_pagoda",
            "kind": "entity_types",
            "name": "Ngôi chùa cổ",
            "definition": "Công trình kiến trúc tôn giáo cổ do con người xây dựng để thờ Phật.",
            "status": "pending",
            "observations": [{"evidence": "Chùa Một Cột là công trình kiến trúc cổ bằng gỗ."}],
        },
        {
            "id": "p_et_place",
            "kind": "entity_types",
            "name": "Địa điểm hành chính",
            "definition": "Vị trí địa lý hoặc đơn vị hành chính nơi di tích tồn tại.",
            "status": "pending",
            "observations": [{"evidence": "Hà Nội là vùng đất kinh kỳ."}],
        },
        {
            "id": "p_et_event",
            "kind": "entity_types",
            "name": "Sự kiện văn hóa truyền thống",
            "definition": "Lễ hội hoặc biến cố văn hóa lịch sử diễn ra theo thời gian.",
            "status": "pending",
            "observations": [{"evidence": "Lễ hội Gióng diễn ra hằng năm."}],
        },
        {
            "id": "p_et_person",
            "kind": "entity_types",
            "name": "Nhân vật lịch sử",
            "definition": "Cá nhân con người có thật trong lịch sử Việt Nam.",
            "status": "pending",
            "observations": [{"evidence": "Vua Lý Thái Tông trị vì triều Lý."}],
        },
        {
            "id": "p_et_material",
            "kind": "entity_types",
            "name": "Vật liệu xây dựng",
            "definition": "Chất liệu tự nhiên hoặc nhân tạo dùng để chế tác hiện vật.",
            "status": "pending",
            "observations": [{"evidence": "Đá xanh dùng tạc bia."}],
        },
        {
            "id": "p_rel_loc",
            "kind": "relations",
            "name": "đóng tại địa bàn",
            "definition": "Vị trí không gian của một công trình kiến trúc vật chất.",
            "status": "pending",
            "observations": [{"evidence": "Chùa Một Cột đóng tại địa bàn Hà Nội."}],
        },
        {
            "id": "p_rel_evt",
            "kind": "relations",
            "name": "tổ chức ở nơi",
            "definition": "Địa điểm nơi một sự kiện lịch sử hoặc lễ hội truyền thống diễn ra.",
            "status": "pending",
            "observations": [{"evidence": "Lễ hội Gióng tổ chức ở nơi địa bàn Hà Nội."}],
        },
        {
            "id": "p_rel_mat",
            "kind": "relations",
            "name": "chế tác bằng vật liệu",
            "definition": "Vật thể hoặc bộ phận được làm từ chất liệu cụ thể.",
            "status": "pending",
            "observations": [{"evidence": "Bệ cột được chế tác bằng vật liệu đá xanh."}],
        },
        {
            "id": "p_rel_about",
            "kind": "relations",
            "name": "ghi nhớ tôn vinh",
            "definition": "Nội dung tín ngưỡng hoặc di tích hướng tới tôn vinh nhân vật.",
            "status": "pending",
            "observations": [{"evidence": "Ngôi chùa ghi nhớ tôn vinh công đức vua Lý Thái Tông."}],
        },
    ]

    result: dict[str, Any] = {
        "parsing_ambiguous_ab": pick_choice_letter("Có thể là A hoặc B đều đúng", ["A", "B"]),
        "parsing_think_tag_b": pick_choice_letter("<think>xem xét...</think>\nLựa chọn: B", ["A", "B", "C"]),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # 3A: Fail-closed test với Broken client
        proj_broken = copy.deepcopy(base_proj)
        proj_broken["schema_proposals"] = copy.deepcopy(proposals[:3])

        class _BrokenCompletions:
            def create(self, **kwargs: Any) -> Any:
                raise RuntimeError("Simulated Ollama Timeout")

        broken_client = SimpleNamespace(chat=SimpleNamespace(completions=_BrokenCompletions()))
        aligner_fc = TargetAligner(vector_repo=VectorIndexRepository(root / "vec_fc"))
        fc_res = aligner_fc.align_project_proposals(
            proj_broken,
            auto_align_threshold=0.99,
            candidate_threshold=0.05,
            enable_llm_verifier=True,
            llm_params={"provider": "DeepSeek", "api_key": "sk-dummy", "model": "deepseek-chat", "client": broken_client},
        )
        result["fail_closed_check"] = {
            "auto_aligned": fc_res["auto_aligned"],
            "error_count": fc_res["error_count"],
            "all_still_pending": all(p["status"] == "pending" for p in proj_broken["schema_proposals"]),
        }

        # 3B: Live Ollama bge-m3 + qwen3.5:4b Verifier (Ngưỡng cao 0.86 vs Ngưỡng song ngữ 0.72)
        try:
            bge_emb = EmbedderGateway(OLLAMA_EMBED_MODEL, base_url=OLLAMA_BASE_URL)

            # 3B-1: Ngưỡng mặc định 0.86 -> Kiểm chứng CR-08 không tự merge vượt ngưỡng dù LLM đã verify candidate
            proj_strict = copy.deepcopy(base_proj)
            proj_strict["schema_proposals"] = copy.deepcopy(proposals)
            aligner_strict = TargetAligner(vector_repo=VectorIndexRepository(root / "vec_live_strict"), embedder=bge_emb)
            t0 = time.perf_counter()
            res_strict = aligner_strict.align_project_proposals(
                proj_strict,
                auto_align_threshold=0.86,
                candidate_threshold=0.40,
                enable_llm_verifier=True,
                llm_params={
                    "provider": OLLAMA_PROVIDER,
                    "api_key": "",
                    "model": OLLAMA_CHAT_MODEL,
                    "base_url": OLLAMA_BASE_URL,
                },
                embedder=bge_emb,
            )
            strict_s = time.perf_counter() - t0
            decisions_strict = [
                {
                    "id": p["id"],
                    "kind": p["kind"],
                    "name": p["name"],
                    "status": p["status"],
                    "score": round(float(p.get("alignment_score", 0.0)), 4),
                    "llm_verified_candidates": [c["name"] for c in p.get("alignment_candidates", []) if c.get("verified_by_llm")],
                    "top_candidate": p.get("alignment_candidates", [{}])[0].get("name", "") if p.get("alignment_candidates") else "",
                }
                for p in proj_strict["schema_proposals"]
            ]

            # 3B-2: Ngưỡng hiệu chuẩn song ngữ bge-m3 (0.72) -> Kiểm chứng auto_aligned + lan truyền [Domain -> Range]
            proj_cal = copy.deepcopy(base_proj)
            proj_cal["schema_proposals"] = copy.deepcopy(proposals)
            aligner_cal = TargetAligner(vector_repo=VectorIndexRepository(root / "vec_live_cal"), embedder=bge_emb)
            t1 = time.perf_counter()
            res_cal = aligner_cal.align_project_proposals(
                proj_cal,
                auto_align_threshold=0.72,
                candidate_threshold=0.40,
                enable_llm_verifier=True,
                llm_params={
                    "provider": OLLAMA_PROVIDER,
                    "api_key": "",
                    "model": OLLAMA_CHAT_MODEL,
                    "base_url": OLLAMA_BASE_URL,
                },
                embedder=bge_emb,
            )
            cal_s = time.perf_counter() - t1
            decisions_cal = [
                {
                    "id": p["id"],
                    "kind": p["kind"],
                    "name": p["name"],
                    "status": p["status"],
                    "aligned_to": p.get("canonical_name", ""),
                    "decision_origin": p.get("decision_origin", ""),
                    "score": round(float(p.get("alignment_score", 0.0)), 4),
                    "candidate_verified_by_llm": any(c.get("verified_by_llm") for c in p.get("alignment_candidates", [])),
                    "llm_verified_candidates": [c["name"] for c in p.get("alignment_candidates", []) if c.get("verified_by_llm")],
                    "error": p.get("last_refresh_error", ""),
                }
                for p in proj_cal["schema_proposals"]
            ]

            result["live_qwen_verifier"] = {
                "status": "ok",
                "strict_threshold_086": {
                    "elapsed_s": round(strict_s, 2),
                    "summary": res_strict,
                    "decisions": decisions_strict,
                },
                "bilingual_threshold_072": {
                    "elapsed_s": round(cal_s, 2),
                    "summary": res_cal,
                    "decisions": decisions_cal,
                },
            }
        except Exception as exc:
            result["live_qwen_verifier"] = {"status": f"error: {exc}"}

    return result


def run_exp4_parallel_edcr_stress(entity_types: list[dict], relations: list[dict]) -> dict[str, Any]:
    """Exp 4: Stress test trích xuất song song EDC+R 4 luồng + cô lập lỗi + che khóa bí mật + SQLite sync."""

    class _MockEDCREngine(BaseExtractionEngine):
        mode_id = MODE_EDC_PLUS_R
        label = "Mock EDC+R Concurrent Stress"

        def process_chunk(self, ctx: ChunkContext) -> EngineOutput:
            time.sleep(0.03)
            cnum = int(ctx.chunk_record.get("chunk_number", 0))
            if cnum == 2 and ctx.document.get("id") == "doc_2":
                exc = RuntimeError(f"429 Rate limit with token={ctx.api_key}")
                exc.input_tokens = 210  # type: ignore[attr-defined]
                exc.output_tokens = 14  # type: ignore[attr-defined]
                raise exc
            nid_s = f"n_src_{ctx.document['id']}_{cnum}"
            nid_t = f"n_tgt_{ctx.document['id']}_{cnum}"
            eid = f"e_{ctx.document['id']}_{cnum}"
            v_id, v_hash, _ = self.resolve_prompt_version_info(ctx.project)
            # Mô phỏng engine trả về dữ kiện cần sáp nhập dưới khóa RLock trên project
            def _append_chunk_items() -> None:
                ctx.project.setdefault("nodes", []).extend(
                    [
                        {"id": nid_s, "name": f"Di tích {ctx.document['id']}_{cnum}", "kind": "E22_Human-Made_Object"},
                        {"id": nid_t, "name": f"Địa danh {ctx.document['id']}_{cnum}", "kind": "E53_Place"},
                    ]
                )
                ctx.project.setdefault("edges", []).append(
                    {
                        "id": eid,
                        "source": nid_s,
                        "relation": "P53_has_former_or_current_location",
                        "target": nid_t,
                        "status": STATUS_APPROVED,
                        "evidence": ctx.chunk_record.get("text", ""),
                        "evidence_found": True,
                        "doc_id": ctx.document["id"],
                        "chunk_number": cnum,
                    }
                )

            if ctx.lock:
                with ctx.lock:
                    _append_chunk_items()
            else:
                _append_chunk_items()
            return EngineOutput(
                payload={"thuc_the": [], "quan_he": []},
                ingest_stats={"added_nodes": 2, "added_edges": 1},
                input_tokens=300,
                output_tokens=80,
                prompt_version_id=v_id,
                prompt_content_hash=v_hash,
                prepared_request_hash=f"hash_{ctx.document['id']}_{cnum}",
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        container = AppContainer(
            json_repo=JsonProjectRepository(root / "projects"),
            sqlite_repo=SQLiteProjectRepository(root / "kg_stress.sqlite3"),
            vector_repo=VectorIndexRepository(root / "vectors"),
        )
        # Đăng ký mock EDC+R engine trên instance service cô lập
        reg = EngineRegistry()
        reg.register(_MockEDCREngine())
        container.extraction_service.engine_registry = reg

        proj = empty_project("EDC_R_Parallel_Stress")
        proj["project_id"] = "proj_edcr_stress"
        proj["extraction_mode"] = MODE_EDC_PLUS_R
        proj["edc_plus_r_settings"] = EDCPlusRSettingsDTO().to_dict()
        apply_entity_types(proj, entity_types)
        apply_relations(proj, relations)

        docs = [
            {
                "id": f"doc_{i}",
                "name": f"tai_lieu_{i}.txt",
                "text": "\n".join(f"Đoạn {j} tại tài liệu {i} mô tả di tích lịch sử." for j in range(1, 5)),
            }
            for i in range(1, 4)
        ]
        proj["documents"] = docs
        container.json_repo.save_project(proj)

        tasks: list[tuple[dict, dict]] = []
        for d in docs:
            for j in range(1, 5):
                tasks.append((d, {"chunk_number": j, "text": f"Đoạn {j} của {d['name']}", "chunk_hash": f"ch_{d['id']}_{j}"}))

        secret = "sk-test-secret-do-not-leak-999"
        t0 = time.perf_counter()
        summary = container.extraction_service.extract_chunks_parallel(
            proj,
            tasks,
            provider="DeepSeek",
            api_key=secret,
            model="deepseek-chat",
            max_workers=4,
            save_after_chunk=True,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        loaded = container.json_repo.load_project(proj["name"])
        page = container.projects_service.query_edges_page(loaded, page_size=50)

        err_runs = [r for r in loaded.get("runs", []) if r.get("status") == "error"]
        ok_runs = [r for r in loaded.get("runs", []) if r.get("status") == "ok"]
        secret_leaked = secret in json.dumps(loaded, ensure_ascii=False)

        return {
            "total_tasks": summary["total"],
            "success_count": summary["success_count"],
            "failed_count": summary["failed_count"],
            "workers": 4,
            "elapsed_ms": round(elapsed_ms, 1),
            "saved_nodes": len(loaded.get("nodes", [])),
            "saved_edges": len(loaded.get("edges", [])),
            "ok_runs_persisted": len(ok_runs),
            "error_runs_persisted": len(err_runs),
            "processed_chunks_count": len(loaded.get("processed_chunks", {})),
            "sqlite_synced_edges": page["total_count"],
            "sync_pending": page["sync_pending"],
            "secret_leaked_in_saved_json": secret_leaked,
            "error_run_token_accounting": {
                "input_tokens": err_runs[0]["input_tokens"] if err_runs else 0,
                "output_tokens": err_runs[0]["output_tokens"] if err_runs else 0,
            },
        }


def run_exp5_graphrag_cidoc_and_qa_split(entity_types: list[dict], relations: list[dict]) -> dict[str, Any]:
    """Exp 5: GraphRAG PCST/PPR + tách token CIDOC '_' + empty-approved fail-closed + QA disjoint split."""
    proj = empty_project("CIDOC_GraphRAG_Test")
    proj["project_id"] = "cidoc_graphrag_test"
    apply_entity_types(proj, entity_types)
    apply_relations(proj, relations)
    proj["nodes"] = [
        {"id": "n_vm", "name": "Văn Miếu Quốc Tử Giám", "kind": "E22_Human-Made_Object"},
        {"id": "n_hanoi", "name": "Thăng Long - Hà Nội", "kind": "E53_Place"},
        {"id": "n_1070", "name": "năm 1070", "kind": "E52_Time-Span"},
        {"id": "n_ltt", "name": "Vua Lý Thánh Tông", "kind": "E21_Person"},
        {"id": "n_nhaly", "name": "Triều đại nhà Lý", "kind": "E74_Group"},
        {"id": "n_bia", "name": "82 bia Tiến sĩ", "kind": "E22_Human-Made_Object"},
        {"id": "n_da", "name": "đá xanh", "kind": "E57_Material"},
        {"id": "n_cl", "name": "Thành Cổ Loa", "kind": "E22_Human-Made_Object"},
        {"id": "n_da2", "name": "Đông Anh", "kind": "E53_Place"},
        {"id": "n_adv", "name": "An Dương Vương", "kind": "E21_Person"},
        {"id": "n_tk3", "name": "thế kỷ III TCN", "kind": "E52_Time-Span"},
        {"id": "n_cm", "name": "Chùa Một Cột", "kind": "E22_Human-Made_Object"},
        {"id": "n_1049", "name": "năm 1049", "kind": "E52_Time-Span"},
        {"id": "n_ltong", "name": "Vua Lý Thái Tông", "kind": "E21_Person"},
        {"id": "n_hd", "name": "Hồ Gươm", "kind": "E53_Place"},
        {"id": "n_dns", "name": "Đền Ngọc Sơn", "kind": "E22_Human-Made_Object"},
        {"id": "n_1865", "name": "năm 1865", "kind": "E52_Time-Span"},
        {"id": "n_nvs", "name": "Nguyễn Văn Siêu", "kind": "E21_Person"},
    ]
    approved_edges_spec = [
        ("e1", "n_vm", "P53_has_former_or_current_location", "n_hanoi", "Văn Miếu Quốc Tử Giám tọa lạc tại Thăng Long - Hà Nội."),
        ("e2", "n_vm", "P4_has_time-span", "n_1070", "Văn Miếu được xây dựng vào năm 1070."),
        ("e3", "n_vm", "P14_carried_out_by", "n_ltt", "Công trình do vua Lý Thánh Tông cho xây dựng."),
        ("e4", "n_ltt", "P107i_is_current_or_former_member_of", "n_nhaly", "Vua Lý Thánh Tông thuộc triều đại nhà Lý."),
        ("e5", "n_vm", "P46_is_composed_of", "n_bia", "Khu di tích bao gồm 82 bia Tiến sĩ."),
        ("e6", "n_bia", "P45_consists_of", "n_da", "82 bia Tiến sĩ được chế tác từ đá xanh."),
        ("e7", "n_bia", "P4_has_time-span", "n_1070", "Bia ghi chép truyền thống từ năm 1070."),
        ("e8", "n_cl", "P53_has_former_or_current_location", "n_da2", "Thành Cổ Loa nằm tại huyện Đông Anh."),
        ("e9", "n_da2", "P89_falls_within", "n_hanoi", "Huyện Đông Anh trực thuộc địa bàn Thăng Long - Hà Nội."),
        ("e10", "n_cl", "P14_carried_out_by", "n_adv", "Thành Cổ Loa do An Dương Vương cho đắp."),
        ("e11", "n_cl", "P4_has_time-span", "n_tk3", "Thành được xây từ thế kỷ III TCN."),
        ("e12", "n_cm", "P53_has_former_or_current_location", "n_hanoi", "Chùa Một Cột tọa lạc tại Thăng Long - Hà Nội."),
        ("e13", "n_cm", "P4_has_time-span", "n_1049", "Chùa Một Cột khởi dựng năm 1049."),
        ("e14", "n_cm", "P14_carried_out_by", "n_ltong", "Chùa do vua Lý Thái Tông cho xây dựng."),
        ("e15", "n_ltong", "P107i_is_current_or_former_member_of", "n_nhaly", "Vua Lý Thái Tông thuộc triều đại nhà Lý."),
        ("e16", "n_dns", "P53_has_former_or_current_location", "n_hd", "Đền Ngọc Sơn nằm trên đảo Ngọc Hồ Gươm."),
        ("e17", "n_hd", "P89_falls_within", "n_hanoi", "Hồ Gươm nằm trong khu vực Thăng Long - Hà Nội."),
        ("e18", "n_dns", "P4_has_time-span", "n_1865", "Đền Ngọc Sơn được tu bổ lớn vào năm 1865."),
        ("e19", "n_dns", "P14_carried_out_by", "n_nvs", "Đền do danh sĩ Nguyễn Văn Siêu chủ trì tu bổ."),
    ]
    proj["documents"] = [
        {
            "id": "d1",
            "name": "thang_long.txt",
            "text": "\n".join(ev for *_, ev in approved_edges_spec),
        }
    ]
    proj["edges"] = [
        {
            "id": eid,
            "source": s,
            "relation": rel,
            "target": t,
            "status": STATUS_APPROVED,
            "evidence": ev,
            "evidence_found": True,
            "doc_id": "d1",
            "doc_name": "thang_long.txt",
        }
        for eid, s, rel, t, ev in approved_edges_spec
    ]
    # Thêm 1 cạnh PENDING, 1 cạnh REJECTED, 1 cạnh bad-evidence
    proj["edges"].extend([
        {"id": "e_pend", "source": "n_cm", "relation": "P2_has_type", "target": "n_da", "status": STATUS_PENDING, "evidence": "pending", "evidence_found": True},
        {"id": "e_rej", "source": "n_cm", "relation": "P45_consists_of", "target": "n_da", "status": STATUS_REJECTED, "evidence": "rejected", "evidence_found": True},
        {"id": "e_badev", "source": "n_vm", "relation": "P45_consists_of", "target": "n_da", "status": STATUS_APPROVED, "evidence": "hallucinated", "evidence_found": False},
    ])

    # 5A: Empty approved fail-closed & REJECTED exclusion
    unapp = copy.deepcopy(proj)
    for e in unapp["edges"]:
        if e["status"] == STATUS_APPROVED:
            e["status"] = STATUS_PENDING
    idx_empty = get_or_build_graph_index(unapp, approved_only=True)
    idx_all_non_rej = get_or_build_graph_index(proj, approved_only=False)

    # 5B: Benchmark PCST vs PPR vs Naive Top-K trên quan hệ CIDOC chứa '_'
    bench_items = [
        {"id": "q1", "type": "1-Hop Attribute", "question": "82 bia Tiến sĩ gồm chất liệu P45 consists of gì?", "gold_answer": "đá xanh", "gold_edge_ids": ["e6"], "target_entity_id": "n_da"},
        {"id": "q2", "type": "1-Hop Multi", "question": "Văn Miếu Quốc Tử Giám xây vào P4 time span năm nào và do ai?", "gold_answer": "năm 1070", "gold_edge_ids": ["e2", "e3"], "target_entity_id": "n_1070"},
        {"id": "q3", "type": "2-Hop Bridge", "question": "Chùa Một Cột do ai xây dựng và vị vua đó thuộc triều đại nào?", "gold_answer": "Triều đại nhà Lý", "gold_edge_ids": ["e14", "e15"], "target_entity_id": "n_nhaly"},
        {"id": "q4", "type": "2-Hop Bridge", "question": "Thành Cổ Loa nằm tại Đông Anh và thuộc địa bàn nào?", "gold_answer": "Thăng Long - Hà Nội", "gold_edge_ids": ["e8", "e9"], "target_entity_id": "n_hanoi"},
        {"id": "q5", "type": "2-Hop Bridge", "question": "Đền Ngọc Sơn nằm trên Hồ Gươm thuộc địa bàn nào?", "gold_answer": "Thăng Long - Hà Nội", "gold_edge_ids": ["e16", "e17"], "target_entity_id": "n_hanoi"},
    ]
    eval_res = evaluate_retrieval_methods(proj, benchmark_items=bench_items, max_edges=8, approved_only=True)

    # 5C: QA Generator Disjoint Split vs Non-Disjoint Split
    ds_disjoint = generate_training_qa_dataset(proj, max_samples=60, approved_only=True, disjoint_split=True)
    ds_leaky = generate_training_qa_dataset(proj, max_samples=60, approved_only=True, disjoint_split=False)

    # 5D: Neo4j pre-filtered export count (phải lọc bỏ e_badev)
    _, clean_export_edges = approved_graph(proj)

    # 5E: Live Ollama qwen3.5:4b GraphRAG QA + domain_topic
    live_rag: dict[str, Any] = {}
    try:
        sub = retrieve_subgraph(proj, "82 bia Tiến sĩ tại Văn Miếu làm từ chất liệu gì và từ năm nào?", method="pcst", max_edges=8, approved_only=True)
        ans = answer_question_with_graph(
            sub,
            provider=OLLAMA_PROVIDER,
            api_key="",
            model=OLLAMA_CHAT_MODEL,
            base_url=OLLAMA_BASE_URL,
            max_input_tokens=4000,
            max_output_tokens=512,
            domain_topic="Di sản Văn hóa Thăng Long - Hà Nội theo chuẩn CIDOC CRM",
        )
        live_rag = {
            "status": "ok" if ans.get("used_llm") else f"fallback: {ans.get('llm_error', '')}",
            "used_llm": bool(ans.get("used_llm")),
            "retrieved_edges": len(sub.edges),
            "answer_preview": str(ans.get("answer", ""))[:350],
            "has_hanoi_hardcode_in_prompt": "chuyên sâu về Hà Nội" in str(ans.get("system_prompt", "")),
            "input_tokens": ans.get("input_tokens", 0),
            "output_tokens": ans.get("output_tokens", 0),
            "llm_latency_ms": ans.get("llm_latency_ms", 0.0),
        }
    except Exception as exc:
        live_rag = {"status": f"error: {exc}"}

    return {
        "empty_approved_edges_count": len(idx_empty.edges),
        "approved_only_false_excludes_rejected": "e_rej" not in idx_all_non_rej.edges_by_id,
        "neo4j_exportable_edges_with_evidence_filter": len(clean_export_edges),
        "total_approved_raw_edges": sum(1 for e in proj["edges"] if e["status"] == STATUS_APPROVED),
        "retrieval_benchmark_summary": eval_res["summary_table"],
        "qa_disjoint_metrics": {
            "total": ds_disjoint["total_samples"],
            "train_val_test": [ds_disjoint["train_count"], ds_disjoint["val_count"], ds_disjoint["test_count"]],
            "split_metrics": ds_disjoint["split_metrics"],
        },
        "qa_non_disjoint_metrics": {
            "total": ds_leaky["total_samples"],
            "train_val_test": [ds_leaky["train_count"], ds_leaky["val_count"], ds_leaky["test_count"]],
            "split_metrics": ds_leaky["split_metrics"],
        },
        "live_graphrag_qwen": live_rag,
    }


def run_exp6_real_project_readonly() -> dict[str, Any]:
    """Exp 6: Đọc chỉ đọc bản sao data/projects/kg_hanoi_edc_r_a/project.json trong thư mục tạm."""
    src_path = REPO_ROOT / "data" / "projects" / "kg_hanoi_edc_r_a" / "project.json"
    if not src_path.exists():
        return {"status": f"missing: {src_path}"}

    real_data = json.loads(src_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        container = AppContainer(
            json_repo=JsonProjectRepository(root / "projects"),
            sqlite_repo=SQLiteProjectRepository(root / "kg_real_ro.sqlite3"),
            vector_repo=VectorIndexRepository(root / "vectors"),
        )
        proj_copy = copy.deepcopy(real_data)
        container.json_repo.save_project(proj_copy)

        # 6A: Query edges trước khi sync thủ công -> kiểm chứng SQLite auto-resync + độ trễ
        t0 = time.perf_counter()
        edge_page = container.projects_service.query_edges_page(proj_copy, page_size=25)
        resync_and_query_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        node_page = container.projects_service.query_nodes_page(proj_copy, page_size=25)
        warm_query_ms = (time.perf_counter() - t1) * 1000.0

        # 6B: Đối sánh GraphRAG trên 1655 cạnh đã duyệt thật (10 câu hỏi benchmark)
        eval_real = evaluate_retrieval_methods(proj_copy, max_edges=12, approved_only=True)

        # 6C: QA Dataset Split: Disjoint vs Non-Disjoint trên dữ liệu thật
        ds_real_disjoint = generate_training_qa_dataset(proj_copy, max_samples=400, approved_only=True, disjoint_split=True)
        ds_real_leaky = generate_training_qa_dataset(proj_copy, max_samples=400, approved_only=True, disjoint_split=False)

        # 6D: Duplicate suggestions + mark_pair_not_duplicate cache consistency
        pairs_before = duplicate_suggestions(proj_copy, fuzzy_threshold=0.82)
        dismissed_filtered = True
        if pairs_before:
            mark_pair_not_duplicate(proj_copy, pairs_before[0]["keep_id"], pairs_before[0]["drop_id"])
            pairs_after = duplicate_suggestions(proj_copy, fuzzy_threshold=0.82)
            key0 = tuple(sorted((pairs_before[0]["keep_id"], pairs_before[0]["drop_id"])))
            dismissed_filtered = all(tuple(sorted((p["keep_id"], p["drop_id"]))) != key0 for p in pairs_after)
            pairs_after_cnt = len(pairs_after)
        else:
            pairs_after_cnt = 0

        # 6E: Neo4j exportable edges filter + mock sync_neo4j trên bản sao dữ liệu thật
        _, exportable_edges = approved_graph(proj_copy)

        class _FakeTx:
            def run(self, cypher: str, **kwargs: Any):
                return SimpleNamespace(consume=lambda: None)

        class _FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def run(self, cypher: str, **kwargs: Any):
                return SimpleNamespace(consume=lambda: None)

            def execute_read(self, fn):
                return []

            def execute_write(self, fn):
                return fn(_FakeTx())

        class _FakeDriver:
            def verify_connectivity(self):
                return None

            def session(self, database: str = "neo4j"):
                return _FakeSession()

        ga_svc = GraphQAApplicationService(neo4j_gateway=Neo4jGateway())
        neo_res = ga_svc.sync_neo4j(proj_copy, "bolt://localhost:7687", "neo4j", "pw", driver=_FakeDriver())

        return {
            "status": "ok",
            "project_name": real_data.get("name"),
            "nodes_count": len(real_data.get("nodes", [])),
            "edges_total": len(real_data.get("edges", [])),
            "edges_approved_raw": sum(1 for e in real_data.get("edges", []) if e.get("status") == STATUS_APPROVED),
            "edges_exportable_with_evidence": len(exportable_edges),
            "neo4j_sync_nodes_written": neo_res["nodes_written"],
            "neo4j_sync_edges_written": neo_res["edges_written"],
            "proposals_total": len(real_data.get("schema_proposals", [])),
            "sqlite_auto_resync": {
                "cold_resync_and_query_ms": round(resync_and_query_ms, 1),
                "warm_node_query_ms": round(warm_query_ms, 2),
                "sqlite_edges_total": edge_page["total_count"],
                "sqlite_nodes_total": node_page["total_count"],
                "sync_pending": edge_page["sync_pending"],
            },
            "graphrag_real_benchmark": eval_real["summary_table"],
            "qa_disjoint_split": {
                "total": ds_real_disjoint["total_samples"],
                "train_val_test": [ds_real_disjoint["train_count"], ds_real_disjoint["val_count"], ds_real_disjoint["test_count"]],
                "split_metrics": ds_real_disjoint["split_metrics"],
            },
            "qa_leaky_split": {
                "total": ds_real_leaky["total_samples"],
                "train_val_test": [ds_real_leaky["train_count"], ds_real_leaky["val_count"], ds_real_leaky["test_count"]],
                "split_metrics": ds_real_leaky["split_metrics"],
            },
            "duplicate_pairs_before": len(pairs_before),
            "duplicate_pairs_after_dismiss_1": pairs_after_cnt,
            "dismissed_pair_immediately_filtered": dismissed_filtered,
        }


def main() -> None:
    t_start = time.perf_counter()
    entity_types, relations = build_bilingual_cidoc_catalog()

    results: dict[str, Any] = {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "exp1_catalog_roundtrip": run_exp1_catalog_roundtrip(entity_types, relations),
        "exp2_schema_retrieval_sr": run_exp2_schema_retrieval_bge_m3(entity_types, relations),
        "exp3_target_alignment_verifier": run_exp3_live_verifier_and_fail_closed(entity_types, relations),
        "exp4_parallel_edcr_stress": run_exp4_parallel_edcr_stress(entity_types, relations),
        "exp5_graphrag_cidoc_and_qa": run_exp5_graphrag_cidoc_and_qa_split(entity_types, relations),
        "exp6_real_project_readonly": run_exp6_real_project_readonly(),
    }
    results["total_elapsed_s"] = round(time.perf_counter() - t_start, 2)

    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
