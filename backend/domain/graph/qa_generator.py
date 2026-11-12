"""Mô-đun Chuyên biệt Sinh & Tinh chỉnh Bộ Dữ liệu Hỏi - Đáp (QA & Training Dataset Generator) cho G-Retriever.

Độc lập 100% với thuật toán truy xuất đồ thị con.
Chịu trách nhiệm:
1. Phân loại ngữ nghĩa vị từ quan hệ tiếng Việt (LOCATION, TEMPORAL, AGENT, DYNASTY, WORSHIP, MEASURE, CONNECTION, GENERAL).
2. Tổng hợp câu hỏi tiếng Việt tự nhiên chuẩn văn phong con người (Human-like Natural Language QA Synthesis) thay vì các template máy móc.
3. Sinh tập dữ liệu huấn luyện quy mô lớn (200 - 5.000+ mẫu) phủ 6 cấu trúc suy luận đồ thị:
   - 2-Hop Bridge (Suy luận bắc cầu A -> B -> C)
   - 2-Hop Intersection (Giao điểm 2 thực thể A -> C <- B)
   - Multi-Attribute Star (Tổng hợp đa thuộc tính A -> {B1, B2})
   - Explainable Path (Giải thích & kiểm chứng liên kết A ~ C)
   - 1-Hop Factoid (Tra cứu xuôi tự nhiên A -> B)
   - 1-Hop Inverse (Tra cứu ngược tìm chủ thể ? -> B)
4. Tinh chỉnh / Diễn đạt lại (Paraphrase) câu hỏi tự nhiên qua LLM (DeepSeek / OpenAI).
5. Xuất các định dạng chuẩn: PyTorch Geometric (pyg_nodes.csv, pyg_edges.csv), train.jsonl, val.jsonl, test.jsonl.
"""
from __future__ import annotations

import collections
import json
import math
import re
import time
from typing import Any

from backend.integrations.llm import LLMGateway, make_adapter, providers
from shared.text_utils import normal, tokenize_vn


# Tập từ dừng thực thể quá chung chung cần lọc bỏ khỏi hạt giống câu hỏi
GENERIC_ENTITY_NAMES: set[str] = {
    "hà nội",
    "việt nam",
    "thăng long",
    "thành phố",
    "nhà nước",
    "trung ương",
    "thành phố hà nội",
    "thủ đô hà nội",
    "nước việt nam",
    "quận",
    "huyện",
    "phường",
    "xã",
}


def clean_rel_name(rel: str) -> str:
    """Loại bỏ dấu gạch dưới và khoảng trắng thừa trong tên quan hệ."""
    raw = str(rel or "").replace("_", " ").strip()
    return re.sub(r"\s+", " ", raw)


RELATION_SEMANTIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("TEMPORAL", (
        "xay dung vao", "xây dựng vào", "khoi dung", "khởi dựng", "khanh thanh", "khánh thành",
        "thanh lap vao", "thành lập vào", "ra doi", "ra đời", "khoi cong", "khởi công", "dien ra", "diễn ra",
        "sinh nam", "sinh năm", "mat nam", "mất năm", "nien dai", "niên đại", "thoi gian", "thời gian",
        "vao ngay", "vào ngày", "vao nam", "vào năm", "nam bat dau", "năm bắt đầu", "nam ket thuc", "năm kết thúc",
        "la ngay", "là ngày",
    )),
    ("DYNASTY_ORG", (
        "vuong trieu", "vương triều", "trieu dai", "triều đại",
        "nha ly", "nhà lý", "nha tran", "nhà trần", "nha le", "nhà lê", "nha nguyen", "nhà nguyễn",
        "to chuc", "tổ chức",
    )),
    ("AGENT_CREATOR", (
        "trieu vua", "triều vua", "sang lap", "sáng lập", "thiet ke", "thiết kế",
        "chi huy", "chỉ huy", "khoi xuong", "khởi xướng", "lanh dao", "lãnh đạo",
        "tru tri", "trụ trì", "tac gia", "tác giả", "chi dao", "chỉ đạo", "xay dung boi", "xây dựng bởi",
        "kien truc su", "kiến trúc sư", "do ai", "được thiết kế bởi", "thiet ke boi",
    )),
    ("WORSHIP", (
        "tho phung", "thờ phụng", "tho tu", "thờ tự", "tho cung", "thờ cúng",
        "ton vinh", "tôn vinh", "tuong niem", "tưởng niệm", " tho ", " thờ ",
    )),
    ("MEASUREMENT", (
        "dien tich", "diện tích", "chieu dai", "chiều dài", "chieu cao", "chiều cao",
        "chieu rong", "chiều rộng", "quy mo", "quy mô", "so do", "số đo", "kich thuoc", "kích thước",
        " dai ", " dài ", " cao ", " rong ", " rộng ", "so luong", "số lượng", "suc chua", "sức chứa",
        "so ho", "số hộ", "so khan gia", "số khán giả",
    )),
    ("CONNECTION", (
        "bac qua", "bắc qua", "chay qua", "chảy qua", " tiep giap ", " tiếp giáp ",
        "dan den", "dẫn đến", "thong qua", "thông qua", "chuyen bay", "chuyến bay", "duong bay", "đường bay",
        " noi ", " nối ", "phu luu", "phụ lưu",
    )),
    ("NAMING_IDENTITY", (
        "con goi", "còn gọi", "con duoc goi", "còn được gọi", "mang ten", "mang tên",
        "ten goi khac", "tên gọi khác", "ten khac", "tên khác", "ten cu", "tên cũ",
        "doi ten thanh", "đổi tên thành", "dat ten la", "đặt tên là", "bi danh", "bí danh",
        "hieu la", "hiệu là", "ten chu", "tên chữ",
    )),
    ("ORGANIZATION", (
        "hop nhat", "hợp nhất", "sap nhap", "sáp nhập", "thanh lap", "thành lập",
        "truc thuoc", "trực thuộc", "quan ly", "quản lý", "giam doc", "giám đốc",
        "pho chu tich", "phó chủ tịch", "chu tich", "chủ tịch", "chuc vu", "chức vụ",
        "phu trach", "phụ trách", "bo nhiem", "bổ nhiệm",
    )),
    ("AWARD_RECOGNITION", (
        "cong nhan", "công nhận", "xep hang", "xếp hạng", "tang thuong", "tặng thưởng",
        "trao tang", "trao tặng", "khen thuong", "khen thưởng", "giai thuong", "giải thưởng",
        "bang khen", "bằng khen", "danh hieu", "danh hiệu",
    )),
    ("LOCATION", (
        "toa lac", "tọa lạc", "nam tai", "nằm tại", "nam o", "nằm ở",
        "thuoc dia phan", "thuộc địa phận", "dat tai", "đặt tại",
        "thuoc quan", "thuộc quận", "thuoc huyen", "thuộc huyện", "thuoc tinh", "thuộc tỉnh",
        " tai ", " tại ", " o ", " ở ", " thuoc ", " thuộc ", "dia ban", "địa bàn",
        "gan ", "gần ", "cach ", "cách ", "giap ", "giáp ", "doi dien", "đối diện",
    )),
    ("CONTENT_CONTAINER", (
        "trung bay", "trưng bày", "luu giu", "lưu giữ", "bao gom", "bao gồm",
        "chua", "chứa", "su dung", "sử dụng", "so huu", "sở hữu", "co cong trinh", "có công trình",
        "co cua", "có cửa", "co bo suu tap", "có bộ sưu tập",
    )),
)


def classify_relation_semantic(rel: str) -> str:
    """Phân loại vị từ quan hệ vào nhóm ngữ nghĩa tiếng Việt chuẩn (dùng word-boundary padding)."""
    r_padded = f" {normal(rel)} "
    for category, keys in RELATION_SEMANTIC_RULES:
        if any(k in r_padded for k in keys):
            return category
    return "GENERAL"


def _clean_natural_question_text(q: str) -> str:
    """Loại bỏ từ lặp ngữ pháp (ví dụ: 'năm năm', 'vào vào', 'tại tại') và chuẩn hóa dấu câu."""
    q = re.sub(r"\b(vào|năm|tại|ở|là|của)\s+\1\b", r"\1", q, flags=re.IGNORECASE)
    q = re.sub(r"\s+", " ", q).strip()
    if not q.endswith("?"):
        q += "?"
    if len(q) > 1:
        q = q[0].upper() + q[1:]
    return q


_FIXED_1HOP_TEMPLATES: dict[str, list[str]] = {
    "DYNASTY_ORG": [
        "{u} thuộc triều đại hoặc vương triều nào trong lịch sử?",
        "{u} trực thuộc cơ quan hay đơn vị nào?",
        "{u} gắn liền với triều đại nào?",
    ],
    "WORSHIP": [
        "{u} thờ phụng vị anh hùng hay danh nhân nào?",
        "Ai là người được thờ phụng tại {u}?",
        "{u} là nơi thờ tự của ai?",
        "{u} thờ vị thần hay nhân vật nào?",
    ],
    "AWARD_RECOGNITION": [
        "{u} được trao tặng giải thưởng hay nhận danh hiệu gì?",
        "{u} được công nhận hoặc xếp hạng di tích như thế nào?",
    ],
    "CONTENT_CONTAINER": [
        "{u} bao gồm những hạng mục hoặc công trình nào?",
        "{u} trưng bày hoặc lưu giữ những hiện vật nào?",
        "Bên trong {u} có những công trình hay hiện vật nào tiêu biểu?",
    ],
}


def _get_1hop_variants(sem: str, rel_c: str, r_norm: str, u_name: str, vk: str) -> list[str]:
    if sem in _FIXED_1HOP_TEMPLATES:
        return [t.format(u=u_name) for t in _FIXED_1HOP_TEMPLATES[sem]]

    if sem == "LOCATION":
        if "thuộc" in rel_c:
            return [
                f"{u_name} thuộc quận, huyện hay khu vực nào của Hà Nội?",
                f"{u_name} trực thuộc địa bàn nào?",
                f"Khu vực nào là nơi {u_name} tọa lạc?",
            ]
        if any(k in rel_c for k in ("giáp", "gần", "cách")):
            return [f"{u_name} {rel_c} địa danh nào?", f"Khu vực nào nằm {rel_c} {u_name}?"]
        return [
            f"{u_name} tọa lạc ở đâu?",
            f"{u_name} nằm tại khu vực hoặc quận nào của Hà Nội?",
            f"Vị trí của {u_name} nằm ở đâu?",
            f"{u_name} nằm trên địa bàn nào của Hà Nội?",
        ]

    if sem == "TEMPORAL" or any(x in vk for x in ("thời gian", "năm")):
        if "sinh" in r_norm:
            return [f"{u_name} sinh vào năm nào?", f"Năm sinh của {u_name} là năm bao nhiêu?"]
        if "mất" in r_norm:
            return [f"{u_name} mất vào năm nào?", f"Năm mất của {u_name} là khi nào?"]
        if any(k in r_norm for k in ("khởi dựng", "xây dựng", "thành lập")):
            return [
                f"{u_name} được xây dựng vào năm nào?",
                f"{u_name} được khởi dựng khi nào?",
                f"Công trình {u_name} được xây dựng vào thời gian nào?",
            ]
        if "diễn ra" in r_norm:
            return [f"Sự kiện {u_name} diễn ra vào thời điểm nào?", f"{u_name} diễn ra vào năm nào?"]
        if "niên đại" in r_norm:
            return [f"{u_name} có niên đại từ khi nào?", f"Niên đại lịch sử của {u_name} là vào thời kỳ nào?"]
        if rel_c.endswith(" vào"):
            return [f"{u_name} {rel_c} năm nào?", f"{u_name} {rel_c} thời gian nào?"]
        return [f"{u_name} {rel_c} vào năm nào?", f"{u_name} {rel_c} vào thời gian nào?"]

    if sem == "AGENT_CREATOR":
        if "triều vua" in r_norm:
            return [
                f"{u_name} được xây dựng dưới triều vua nào?",
                f"Vị vua nào đã cho xây dựng {u_name}?",
                f"{u_name} gắn liền với triều đại của vị vua nào?",
            ]
        if "thiết kế" in r_norm:
            return [f"{u_name} do ai thiết kế?", f"Kiến trúc sư nào đã thiết kế {u_name}?", f"Công trình {u_name} được thiết kế bởi ai?"]
        if "trụ trì" in r_norm:
            return [f"Ai là người trụ trì {u_name}?", f"Sư trụ trì của {u_name} là ai?"]
        if "tác giả" in r_norm:
            return [f"Ai là tác giả của {u_name}?", f"Tác giả sáng tác {u_name} là ai?"]
        return [f"Ai là người {rel_c} {u_name}?", f"{u_name} do ai {rel_c}?", f"Nhân vật nào gắn liền với việc {rel_c} {u_name}?"]

    if sem == "NAMING_IDENTITY":
        if "đổi tên" in r_norm:
            return [f"{u_name} được đổi tên thành gì?", f"Tên mới sau khi đổi của {u_name} là gì?"]
        if "tên cũ" in r_norm:
            return [f"{u_name} từng mang tên cũ là gì?", f"Tên gọi trước đây của {u_name} là gì?"]
        return [f"{u_name} còn được gọi bằng tên nào khác?", f"{u_name} có tên gọi khác là gì?", f"Tên gọi khác của {u_name} trong lịch sử là gì?"]

    if sem == "ORGANIZATION":
        if any(k in r_norm for k in ("hợp nhất", "sáp nhập")):
            return [f"{u_name} hợp nhất hoặc sáp nhập với đơn vị nào?", f"{u_name} được sáp nhập thành tổ chức nào?"]
        if any(k in r_norm for k in ("giám đốc", "chủ tịch", "chức vụ")):
            return [f"{u_name} đảm nhiệm chức vụ hoặc vai trò gì?", f"Ai là người lãnh đạo tại {u_name}?"]
        return [f"{u_name} trực thuộc cơ quan hay tổ chức nào?", f"{u_name} có quan hệ hợp tác với đơn vị nào?"]

    if sem == "MEASUREMENT":
        if "diện tích" in r_norm:
            return [f"Diện tích của {u_name} là bao nhiêu?", f"{u_name} có diện tích rộng bao nhiêu?"]
        if "chiều dài" in r_norm or "dài" in r_norm:
            return [f"{u_name} có chiều dài bao nhiêu mét?", f"Chiều dài của {u_name} là bao nhiêu?"]
        if "chiều cao" in r_norm or "cao" in r_norm:
            return [f"{u_name} cao bao nhiêu mét?", f"Chiều cao của công trình {u_name} là bao nhiêu?"]
        return [f"Quy mô số đo của {u_name} là bao nhiêu?", f"{u_name} có quy mô như thế nào?"]

    if sem == "CONNECTION":
        if "bắc qua" in r_norm:
            return [f"{u_name} bắc qua con sông nào?", f"Cây cầu {u_name} bắc qua sông nào ở Hà Nội?"]
        if "chảy qua" in r_norm:
            return [f"{u_name} chảy qua những địa phận nào?", f"Dòng sông {u_name} đi qua những khu vực nào?"]
        if "nối" in r_norm:
            return [f"{u_name} nối liền những khu vực nào?", f"Tuyến đường {u_name} kết nối những địa điểm nào?"]
        if any(k in r_norm for k in ("chuyến bay", "đường bay")):
            return [f"{u_name} khai thác các chuyến bay kết nối tới địa điểm nào?", f"{u_name} có đường bay đến thành phố hay quốc gia nào?"]
        return [f"{u_name} kết nối với những địa điểm nào?"]

    return [
        f"Cho biết thông tin về việc {u_name} {rel_c}?",
        f"{u_name} {rel_c} ai hoặc địa danh nào?",
        f"{u_name} {rel_c} như thế nào?",
    ]


def synthesize_1hop_natural_question(
    u_name: str,
    rel: str,
    v_name: str,
    v_kind: str = "",
    idx_seed: int = 0,
) -> str:
    """Sinh câu hỏi 1-hop tự nhiên như con người gõ tìm kiếm, không dùng từ ngữ máy tính."""
    sem = classify_relation_semantic(rel)
    rel_c = clean_rel_name(rel)
    r_norm = normal(rel_c)
    vk = normal(v_kind)
    variants = _get_1hop_variants(sem, rel_c, r_norm, u_name, vk)
    return _clean_natural_question_text(variants[idx_seed % len(variants)])

    return _clean_natural_question_text(variants[idx_seed % len(variants)])


_INVERSE_SEM_TEMPLATES: dict[str, list[str]] = {
    "LOCATION": [
        "Ở {v} có những công trình hay địa danh nào nổi tiếng?",
        "Những di tích lịch sử nào nằm tại {v}?",
        "Địa danh nào tọa lạc trên địa bàn {v}?",
    ],
    "WORSHIP": [
        "Những ngôi đền, ngôi chùa nào tại Hà Nội thờ phụng {v}?",
        "{v} được thờ phụng tại di tích nào?",
        "Nơi nào là địa điểm thờ cúng {v}?",
    ],
    "AGENT_CREATOR": [
        "{v} đã cho xây dựng hoặc sáng lập những công trình nào?",
        "Dưới thời kỳ của {v}, công trình tiêu biểu nào được khởi dựng?",
        "Những tác phẩm hoặc công trình nào do {v} thiết kế/chỉ đạo?",
    ],
    "DYNASTY_ORG": [
        "Trong triều đại {v}, những nhân vật hoặc công trình nào nổi bật?",
        "Những di tích lịch sử nào thuộc về {v}?",
    ],
    "CONNECTION": [
        "Cây cầu nào bắc qua {v}?",
        "Những tuyến đường hoặc công trình nào nối liền với {v}?",
    ],
    "NAMING_IDENTITY": [
        "Công trình hay di tích nào từng mang tên gọi là {v}?",
        "Địa danh nào còn được gọi là {v}?",
    ],
    "ORGANIZATION": [
        "Đơn vị nào đã hợp nhất hoặc sáp nhập thành {v}?",
        "Tổ chức nào trực thuộc hoặc liên kết với {v}?",
    ],
    "CONTENT_CONTAINER": [
        "Bảo tàng hoặc di tích nào lưu giữ, trưng bày {v}?",
        "Công trình nào bao gồm hạng mục {v}?",
    ],
}


def synthesize_1hop_inverse_question(
    u_name: str,
    rel: str,
    v_name: str,
    u_kind: str = "",
    idx_seed: int = 0,
) -> str:
    """Sinh câu hỏi 1-hop ngược (tìm chủ thể) tự nhiên không có từ ngữ máy tính."""
    sem = classify_relation_semantic(rel)
    rel_c = clean_rel_name(rel)
    uk_lbl = _infer_entity_natural_label(u_name, u_kind)

    if sem in _INVERSE_SEM_TEMPLATES:
        variants = [t.format(v=v_name) for t in _INVERSE_SEM_TEMPLATES[sem]]
    else:
        if uk_lbl and uk_lbl != "thông tin":
            variants = [
                f"{uk_lbl.capitalize()} nào {rel_c} {v_name}?",
                f"Có những {uk_lbl} nào {rel_c} {v_name}?",
            ]
        else:
            variants = [
                f"Công trình, địa danh hay nhân vật nào {rel_c} {v_name}?",
                f"Nơi nào hoặc đơn vị nào {rel_c} {v_name}?",
            ]

    return _clean_natural_question_text(variants[idx_seed % len(variants)])


_NAME_PREFIX_LABELS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("chùa ", "đền ", "đình ", "miếu ", "lăng ", "tháp ", "phủ "), "di tích"),
    (("bảo tàng", "viện bảo tàng"), "bảo tàng"),
    (("cầu ", "đường ", "phố ", "ngõ ", "quận ", "huyện ", "phường ", "xã "), "địa danh"),
    (("nhà máy", "bệnh viện", "trường", "viện ", "hội đồng", "ủy ban", "bộ ", "ngân hàng"), "đơn vị"),
)

_KIND_KEYWORD_LABELS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("chùa", "đền", "đình", "miếu", "phủ", "di tích", "công trình"), "di tích"),
    (("bảo tàng",), "bảo tàng"),
    (("địa danh", "địa điểm", "vị trí", "phố", "đường", "quận", "huyện", "thành phố"), "địa danh"),
    (("vua", "hoàng đế"), "vị vua"),
    (("nhân vật", "danh nhân", "người", "tác giả", "kiến trúc sư"), "nhân vật"),
    (("triều đại", "vương triều", "nhà lý", "nhà trần", "nhà lê"), "triều đại"),
    (("tổ chức", "cơ quan", "trường", "bệnh viện", "viện"), "đơn vị"),
    (("thời gian", "năm", "mốc thời gian"), "mốc thời gian"),
    (("hiện vật", "bảo vật", "tác phẩm", "sách", "gốm"), "hiện vật"),
    (("sự kiện", "trận đánh", "chiến dịch"), "sự kiện"),
)

_SEM_IN_LABELS: dict[str, str] = {
    "LOCATION": "địa danh",
    "WORSHIP": "danh nhân",
    "AGENT_CREATOR": "nhân vật",
    "TEMPORAL": "mốc thời gian",
    "CONTENT_CONTAINER": "hiện vật",
    "ORGANIZATION": "đơn vị",
}


def _infer_entity_natural_label(name: str, kind: str, incoming_rel: str = "", outgoing_rel: str = "") -> str:
    """Suy luận danh từ chỉ loại tự nhiên (địa danh, ngôi chùa, vị vua, hiện vật...) thay cho chữ 'thực thể'/'đối tượng'."""
    n_lower = name.lower()
    for prefixes, lbl in _NAME_PREFIX_LABELS:
        if any(n_lower.startswith(p) for p in prefixes):
            return lbl
    if any(n_lower.startswith(x) for x in ("vua ", "hoàng đế ", "lý ", "trần ", "lê ", "nguyễn ")) and len(name.split()) <= 4:
        return "nhân vật"

    k_norm = normal(kind)
    for keywords, lbl in _KIND_KEYWORD_LABELS:
        if any(k in k_norm for k in keywords):
            return lbl

    if incoming_rel:
        sem_in = classify_relation_semantic(incoming_rel)
        if sem_in in _SEM_IN_LABELS:
            return _SEM_IN_LABELS[sem_in]

    return "thông tin"


_ATTRIBUTE_DESCRIPTORS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("LOCATION", ("tọa lạc", "nằm"), "vị trí tọa lạc"),
    ("TEMPORAL", ("năm", "thời gian"), "thời gian xây dựng hoặc niên đại"),
    ("WORSHIP", (), "nhân vật được thờ phụng"),
    ("AGENT_CREATOR", ("thiết kế", "xây dựng"), "người khởi dựng hoặc thiết kế"),
    ("MEASUREMENT", (), "quy mô kích thước"),
    ("CONTENT_CONTAINER", ("trưng bày", "lưu giữ"), "các hiện vật trưng bày"),
    ("CONNECTION", (), "địa điểm kết nối"),
    ("NAMING_IDENTITY", ("tên", "gọi"), "tên gọi lịch sử"),
    ("ORGANIZATION", ("hợp nhất", "sáp nhập"), "quá trình hợp nhất sáp nhập"),
)


def _format_attribute_descriptor(rel: str) -> str:
    """Tạo cụm danh từ mô tả thuộc tính tự nhiên cho câu hỏi đa nhánh (Star)."""
    sem = classify_relation_semantic(rel)
    rel_c = clean_rel_name(rel)
    r_norm = normal(rel_c)
    for cat, keys, desc in _ATTRIBUTE_DESCRIPTORS:
        if sem == cat or any(k in r_norm for k in keys):
            return desc
    return rel_c


_EXACT_PREDICATE_PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("thờ",), "thờ phụng vị anh hùng hay danh nhân nào?"),
    (("thiết kế",), "do ai thiết kế?"),
    (("tác giả",), "do ai là tác giả?"),
    (("trụ trì",), "do vị sư nào trụ trì?"),
    (("dời đô",), "dời kinh đô từ đâu?"),
    (("triều",), "thuộc triều đại nào?"),
    (("bắc qua",), "bắc qua con sông nào?"),
    (("chảy qua",), "chảy qua những khu vực nào?"),
    (("chức vụ", "chủ tịch", "giám đốc"), "đảm nhiệm chức vụ hay vai trò gì?"),
    (("công nhận", "xếp hạng"), "được xếp hạng hay công nhận danh hiệu gì?"),
    (("bao gồm", "chứa"), "bao gồm những công trình hay hiện vật nào?"),
    (("trưng bày", "lưu giữ"), "trưng bày hay lưu giữ những hiện vật nào?"),
    (("chuyến bay", "đường bay"), "kết nối đường bay tới đâu?"),
)


def _format_predicate_question(rel: str, c_kind: str = "") -> str:
    """Tạo cụm hỏi tự nhiên theo quan hệ đích mà không bị lặp từ hay máy móc."""
    sem = classify_relation_semantic(rel)
    rel_c = clean_rel_name(rel)
    ck = normal(c_kind)
    r_norm = normal(rel_c)

    if "thuộc" in r_norm:
        if any(x in ck for x in ("quận", "huyện", "phường", "tỉnh", "địa danh", "địa bàn")):
            return "thuộc quận hay khu vực nào của Hà Nội?"
        return "thuộc sự kiện lịch sử nào?" if "sự kiện" in ck else "thuộc quận, khu vực hay tổ chức nào?"

    if any(x in r_norm for x in ("tọa lạc", "nằm ở", "nằm tại", "đặt tại")):
        return "ở đâu?"

    if any(x in r_norm for x in ("giáp", "tiếp giáp", "gần", "cách", "đối diện")):
        return f"{rel_c} địa danh hay khu vực nào?"

    if sem == "TEMPORAL" or any(x in ck for x in ("thời gian", "năm")) or any(x in r_norm for x in ("năm", "thời gian", "ngày", "khi", "niên đại")):
        if rel_c.endswith(" vào"):
            return f"{rel_c} năm nào?"
        if "vào" in r_norm:
            return f"{rel_c} khi nào?"
        if "niên đại" in r_norm:
            return "có niên đại từ khi nào?"
        if "sinh" in r_norm:
            return "sinh vào năm nào?"
        if "mất" in r_norm:
            return "mất vào năm nào?"
        return f"{rel_c} vào năm nào?"

    for keys, phrase in _EXACT_PREDICATE_PHRASES:
        if any(k in r_norm for k in keys):
            return phrase

    if any(x in r_norm for x in ("hợp nhất", "sáp nhập")):
        return f"{rel_c} đơn vị hay bảo tàng nào?"

    if "tên" in r_norm or "gọi" in r_norm:
        if "đổi tên" in r_norm:
            return "được đổi tên thành gì?"
        if "tên cũ" in r_norm:
            return "từng mang tên cũ là gì?"
        if "mang tên" in r_norm:
            return "mang tên là gì?"
        return "còn được gọi là gì?"

    if any(x in r_norm for x in ("nơi sống", "làm việc")):
        return f"{rel_c} của danh nhân nào?"

    if any(x in r_norm for x in ("tặng", "khen thưởng", "bằng khen", "giải thưởng")):
        return f"{rel_c} phần thưởng hay danh hiệu gì?"

    if sem == "MEASUREMENT" or any(x in r_norm for x in ("diện tích", "chiều dài", "chiều cao", "quy mô", "kích thước")):
        return f"có {rel_c} là bao nhiêu?"

    # Fallback dựa theo kiểu đích c_kind
    if any(x in ck for x in ("nhân vật", "người", "danh nhân", "vị vua")):
        return f"{rel_c} nhân vật nào?"
    if any(x in ck for x in ("địa danh", "địa bàn", "vị trí")):
        return f"{rel_c} ở địa danh nào?"
    if any(x in ck for x in ("đơn vị", "tổ chức", "bảo tàng", "trường")):
        return f"{rel_c} đơn vị nào?"

    return f"{rel_c} nội dung hay nhân vật nào?"


_2HOP_SEM_PATTERNS: tuple[tuple[str, str, list[str]], ...] = (
    ("AGENT_CREATOR", "DYNASTY_ORG", [
        "Vị vua cho xây dựng {u} thuộc triều đại nào trong lịch sử?",
        "{u} được khởi dựng dưới thời vị vua nào và ông thuộc vương triều gì?",
        "Người sáng lập {u} thuộc triều đại phong kiến nào?",
    ]),
    ("WORSHIP", "TEMPORAL", [
        "Nhân vật được thờ phụng tại {u} sinh vào năm nào?",
        "Vị anh hùng được thờ tại {u} gắn liền với mốc thời gian nào trong lịch sử?",
    ]),
    ("WORSHIP", "LOCATION", [
        "Vị danh nhân được thờ phụng tại {u} có quê quán ở đâu?",
        "Người được thờ tại {u} sinh ra tại địa phương nào?",
    ]),
    ("CONTENT_CONTAINER", "LOCATION", [
        "{u} lưu giữ hiện vật tiêu biểu nào và hiện vật đó có nguồn gốc từ đâu?",
        "Hiện vật quý được trưng bày tại {u} xuất xứ từ địa phương nào?",
    ]),
    ("CONTENT_CONTAINER", "TEMPORAL", [
        "{u} lưu giữ bộ sưu tập nào và bộ sưu tập đó có niên đại từ khi nào?",
        "Hiện vật lịch sử tại {u} gắn liền với thời kỳ nào?",
    ]),
)


def synthesize_2hop_bridge_question(
    u_name: str,
    r1: str,
    b_name: str,
    b_kind: str,
    r2: str,
    c_name: str,
    c_kind: str,
    idx_seed: int = 0,
) -> str:
    """Sinh câu hỏi 2-hop bắc cầu siêu tự nhiên như con người hỏi lịch sử/địa lý."""
    sem1 = classify_relation_semantic(r1)
    sem2 = classify_relation_semantic(r2)
    r1_c = clean_rel_name(r1)
    r2_c = clean_rel_name(r2)
    ck = normal(c_kind)

    if sem1 == "LOCATION" and (sem2 == "LOCATION" or any(x in ck for x in ("quận", "huyện", "tỉnh"))):
        variants = [
            f"{u_name} tọa lạc tại địa danh nào và nơi đó thuộc quận nào của Hà Nội?",
            f"Địa bàn nơi {u_name} tọa lạc thuộc quận hay khu vực nào?",
            f"{u_name} nằm ở đâu và khu vực đó trực thuộc địa bàn nào?",
        ]
        return _clean_natural_question_text(variants[idx_seed % len(variants)])

    if "bắc qua" in normal(r1_c) and sem2 == "CONNECTION":
        variants = [
            f"{u_name} bắc qua con sông nào và dòng sông này chảy qua những khu vực nào?",
            f"Cây cầu {u_name} bắc qua sông nào và sông đó tiếp giáp với đâu?",
        ]
        return _clean_natural_question_text(variants[idx_seed % len(variants)])

    for s1, s2, templates in _2HOP_SEM_PATTERNS:
        if sem1 == s1 and sem2 == s2:
            variants = [t.format(u=u_name) for t in templates]
            return _clean_natural_question_text(variants[idx_seed % len(variants)])

    # TRƯỜNG HỢP TỔNG QUÁT TỰ NHIÊN: Suy luận từ chỉ loại danh từ thay vì dùng chữ "thực thể" / "đối tượng"
    b_lbl = _infer_entity_natural_label(b_name, b_kind, incoming_rel=r1, outgoing_rel=r2)
    q_tail = _format_predicate_question(r2, c_kind)

    _GEN_BRIDGE_MAP = {
        ("địa danh", "địa bàn"): [
            f"{u_name} tọa lạc tại địa danh nào và nơi này {q_tail}",
            f"Khu vực nơi {u_name} tọa lạc {q_tail}",
            f"Địa bàn nơi {u_name} đặt vị trí {q_tail}",
        ],
        ("nhân vật", "vị vua", "danh nhân"): [
            f"{u_name} gắn liền với nhân vật lịch sử nào và người đó {q_tail}",
            f"Nhân vật gắn liền với {u_name} {q_tail}",
        ],
        ("hiện vật", "bảo vật"): [
            f"{u_name} lưu giữ hoặc trưng bày hiện vật nào và hiện vật này {q_tail}",
            f"Hiện vật quý gắn với {u_name} {q_tail}",
        ],
        ("đơn vị", "tổ chức", "bảo tàng"): [
            f"{u_name} liên kết hoặc sáp nhập với đơn vị nào và tổ chức này {q_tail}",
            f"Đơn vị liên kết với {u_name} {q_tail}",
        ],
    }
    for keys, var_list in _GEN_BRIDGE_MAP.items():
        if b_lbl in keys:
            variants = var_list
            break
    else:
        variants = [
            f"{u_name} {r1_c} {b_lbl} nào và {b_lbl} này {q_tail}",
            f"Cho biết {b_lbl} gắn liền với việc {r1_c} của {u_name} và {b_lbl} này {q_tail}",
        ]

    return _clean_natural_question_text(variants[idx_seed % len(variants)])

    return _clean_natural_question_text(variants[idx_seed % len(variants)])


def synthesize_intersection_question(
    a_name: str,
    r1: str,
    b_name: str,
    r2: str,
    c_name: str,
    c_kind: str = "",
    idx_seed: int = 0,
) -> str:
    """Sinh câu hỏi giao điểm (2 thực thể cùng hướng về 1 điểm chung)."""
    sem1 = classify_relation_semantic(r1)
    sem2 = classify_relation_semantic(r2)
    ck = normal(c_kind)

    if sem1 == "LOCATION" and sem2 == "LOCATION":
        variants = [
            f"Cả hai công trình {a_name} và {b_name} cùng tọa lạc tại quận hay khu vực nào của Hà Nội?",
            f"{a_name} và {b_name} có chung điểm tương đồng gì về địa bàn tọa lạc?",
            f"Khu vực nào là nơi tọa lạc của cả hai di tích {a_name} lẫn {b_name}?",
        ]
        return _clean_natural_question_text(variants[idx_seed % len(variants)])

    if sem1 == "WORSHIP" and sem2 == "WORSHIP":
        variants = [
            f"Hai ngôi đền/chùa {a_name} và {b_name} cùng thờ phụng vị anh hùng hay danh nhân nào?",
            f"Vị thần hay danh nhân nào được thờ tự ở cả hai di tích {a_name} và {b_name}?",
        ]
        return _clean_natural_question_text(variants[idx_seed % len(variants)])

    if sem1 == "AGENT_CREATOR" and sem2 == "AGENT_CREATOR":
        variants = [
            f"Ai là người đã cho khởi dựng hoặc sáng lập cả hai công trình {a_name} và {b_name}?",
            f"Vị vua hay nhân vật lịch sử nào gắn với sự ra đời của cả {a_name} và {b_name}?",
        ]
        return _clean_natural_question_text(variants[idx_seed % len(variants)])

    ck_lbl = _infer_entity_natural_label(c_name, c_kind)
    if not ck_lbl or ck_lbl == "thông tin":
        ck_lbl = "nội dung"

    variants = [
        f"Cả hai công trình/đơn vị {a_name} và {b_name} cùng liên kết tới {ck_lbl} chung nào?",
        f"Điểm chung kết nối giữa {a_name} và {b_name} là {ck_lbl} nào?",
        f"{ck_lbl.capitalize()} nào là điểm giao kết nối giữa cả {a_name} lẫn {b_name}?",
    ]
    return _clean_natural_question_text(variants[idx_seed % len(variants)])


def synthesize_star_question(
    u_name: str,
    r1: str,
    t1_name: str,
    r2: str,
    t2_name: str,
    idx_seed: int = 0,
) -> str:
    """Sinh câu hỏi tổng hợp đa thuộc tính quanh 1 thực thể."""
    attr1 = _format_attribute_descriptor(r1)
    attr2 = _format_attribute_descriptor(r2)

    variants = [
        f"Hãy cho biết thông tin về {attr1} cũng như {attr2} của {u_name}?",
        f"Tại {u_name}, {attr1} và {attr2} được ghi nhận cụ thể như thế nào?",
        f"Cho biết thông tin chi tiết về {attr1} và {attr2} liên quan đến {u_name}?",
        f"{u_name} có những đặc điểm gì về {attr1} và {attr2}?",
    ]
    return _clean_natural_question_text(variants[idx_seed % len(variants)])


def synthesize_explain_question(
    u_name: str,
    c_name: str,
    b_name: str = "",
    idx_seed: int = 0,
) -> str:
    """Sinh câu hỏi giải thích mối liên kết bắc cầu (Explainable Path)."""
    variants = [
        f"{u_name} có mối liên hệ như thế nào với {c_name} trong lịch sử văn hóa Hà Nội?",
        f"Mối liên kết giữa {u_name} và {c_name} được ghi nhận qua những mắt xích lịch sử nào?",
        f"Qua những yếu tố hoặc địa danh trung gian nào mà {u_name} có sự kết nối với {c_name}?",
        f"Hãy giải thích mối liên hệ lịch sử giữa {u_name} và {c_name}?",
    ]
    return _clean_natural_question_text(variants[idx_seed % len(variants)])


def _build_mini_textualized_subgraph(
    nodes_by_id: dict[str, dict[str, Any]],
    sub_node_ids: list[str],
    sub_edges: list[dict[str, Any]],
    seed_ids: set[str],
) -> str:
    """Tạo bảng Textualized Subgraph chuẩn G-Retriever cho từng mẫu huấn luyện."""
    lines = [
        "=== BẢNG THỰC THỂ TRONG ĐỒ THỊ CON (NODES) ===",
        "node_id | ten_thuc_the | loai_thuc_the | vai_tro | mo_ta",
    ]
    for nid in dict.fromkeys(sub_node_ids):
        n = nodes_by_id.get(nid, {})
        role = "Hạt giống (Seed)" if nid in seed_ids else "Ngữ cảnh / Đích (Target)"
        desc = str(n.get("description") or "").replace("\n", " ").strip()
        lines.append(f"{nid} | {n.get('name', nid)} | {n.get('kind', '')} | {role} | {desc}")

    lines.append("")
    lines.append("=== BẢNG QUAN HỆ & BẰNG CHỨNG NGUYÊN VĂN (EDGES) ===")
    lines.append("edge_id | thuc_the_nguon | quan_he | thuc_the_dich | bang_chung_nguyen_van | tai_lieu_nguon")
    for e in sub_edges:
        u_name = nodes_by_id.get(str(e.get("source", "")), {}).get("name", e.get("source", ""))
        v_name = nodes_by_id.get(str(e.get("target", "")), {}).get("name", e.get("target", ""))
        ev = str(e.get("evidence") or "").replace("\n", " ").strip()
        lines.append(
            f"{e.get('id', '')} | {u_name} | {e.get('relation', '')} | {v_name} | \"{ev}\" | {e.get('doc_name', '')}"
        )
    return "\n".join(lines)


def generate_qa_benchmark(
    project: dict[str, Any],
    *,
    num_questions: int = 18,
    approved_only: bool = True,
) -> list[dict[str, Any]]:
    """Tự động sinh bộ câu hỏi kiểm thử chuẩn (Benchmark Suite) cho 3 phương pháp với câu hỏi tự nhiên như người gõ."""
    from backend.domain.graph.g_retriever import get_or_build_graph_index

    index = get_or_build_graph_index(project, approved_only=approved_only)
    benchmark: list[dict[str, Any]] = []
    seen_queries: set[str] = set()
    used_source_nodes: set[str] = set()

    # 1. 2-Hop Bridge (55% số câu)
    target_2hop = max(6, int(num_questions * 0.55))
    step_idx = 0
    for u, e1_list in index.out_edges.items():
        if len(benchmark) >= target_2hop:
            break
        if u in used_source_nodes:
            continue
        u_node = index.nodes_by_id.get(u, {})
        u_name = str(u_node.get("name", "")).strip()
        if not u_name or len(u_name.split()) < 2 or normal(u_name) in GENERIC_ENTITY_NAMES:
            continue
        if not (1 <= index.degree.get(u, 0) <= 25):
            continue

        added = False
        for e1 in e1_list:
            b = str(e1.get("target", ""))
            if b == u or not (2 <= index.degree.get(b, 0) <= 25):
                continue
            b_node = index.nodes_by_id.get(b, {})
            b_name = str(b_node.get("name", "")).strip()
            b_kind = str(b_node.get("kind") or "đối tượng").strip()
            if not b_name or normal(b_name) in GENERIC_ENTITY_NAMES or normal(b_kind) in ("mốc thời gian", "số đo"):
                continue

            r1 = str(e1.get("relation", "")).strip()
            for e2 in index.out_edges.get(b, ()):
                c = str(e2.get("target", ""))
                if c in (u, b):
                    continue
                c_node = index.nodes_by_id.get(c, {})
                c_name = str(c_node.get("name", "")).strip()
                c_kind = str(c_node.get("kind") or "thực thể").strip()
                r2 = str(e2.get("relation", "")).strip()
                if not c_name or not r1 or not r2 or r1 == r2 or normal(c_name) in GENERIC_ENTITY_NAMES:
                    continue

                step_idx += 1
                q_text = synthesize_2hop_bridge_question(
                    u_name, r1, b_name, b_kind, r2, c_name, c_kind, idx_seed=step_idx
                )
                if q_text in seen_queries:
                    continue
                seen_queries.add(q_text)
                used_source_nodes.add(u)
                benchmark.append(
                    {
                        "id": f"qa_2hop_{len(benchmark) + 1:02d}",
                        "category": "2-Hop Bridge (Suy luận bắc cầu)",
                        "type": "2-Hop Bridge (Suy luận bắc cầu)",
                        "question": q_text,
                        "gold_answer": f"{u_name} ──[{r1}]──► {b_name} ──[{r2}]──► {c_name}",
                        "short_answer": c_name,
                        "gold_node_ids": [u, b, c],
                        "gold_edge_ids": [str(e1["id"]), str(e2["id"])],
                        "target_entity_id": c,
                        "target_node_id": c,
                        "target_entity_name": c_name,
                        "expected_answer_name": c_name,
                        "bridge_entity_id": b,
                        "bridge_node_id": b,
                        "bridge_entity_name": b_name,
                        "bridge_node_name": b_name,
                    }
                )
                added = True
                break
            if added:
                break

    # 2. Multi-Attribute Star (25% số câu)
    target_star = len(benchmark) + max(4, int(num_questions * 0.25))
    star_idx = 0
    for u, e_list in index.out_edges.items():
        if len(benchmark) >= target_star:
            break
        if u in used_source_nodes or len(e_list) < 2:
            continue
        u_node = index.nodes_by_id.get(u, {})
        u_name = str(u_node.get("name", "")).strip()
        if not u_name or len(u_name.split()) < 2 or normal(u_name) in GENERIC_ENTITY_NAMES:
            continue

        distinct_edges: list[dict[str, Any]] = []
        seen_rels: set[str] = set()
        for e in e_list:
            rn = normal(str(e.get("relation", "")))
            if rn and rn not in seen_rels and str(e.get("target", "")) != u:
                seen_rels.add(rn)
                distinct_edges.append(e)
            if len(distinct_edges) == 2:
                break
        if len(distinct_edges) < 2:
            continue

        e_a, e_b = distinct_edges[0], distinct_edges[1]
        t_a = index.nodes_by_id.get(str(e_a["target"]), {})
        t_b = index.nodes_by_id.get(str(e_b["target"]), {})
        ta_name = str(t_a.get("name", "")).strip()
        tb_name = str(t_b.get("name", "")).strip()
        if not ta_name or not tb_name:
            continue

        star_idx += 1
        q_text = synthesize_star_question(
            u_name, e_a.get("relation", ""), ta_name, e_b.get("relation", ""), tb_name, idx_seed=star_idx
        )
        if q_text in seen_queries:
            continue
        seen_queries.add(q_text)
        used_source_nodes.add(u)
        benchmark.append(
            {
                "id": f"qa_star_{len(benchmark) + 1:02d}",
                "category": "Multi-Attribute (Tổng hợp đa nhánh)",
                "type": "Multi-Attribute (Tổng hợp đa nhánh)",
                "question": q_text,
                "gold_answer": (
                    f"{u_name}: [{e_a.get('relation', '')}] -> {ta_name}; [{e_b.get('relation', '')}] -> {tb_name}"
                ),
                "short_answer": f"{ta_name}; {tb_name}",
                "gold_node_ids": [u, str(e_a["target"]), str(e_b["target"])],
                "gold_edge_ids": [str(e_a["id"]), str(e_b["id"])],
                "target_entity_id": str(e_b["target"]),
                "target_node_id": str(e_b["target"]),
                "target_entity_name": f"{ta_name}, {tb_name}",
                "expected_answer_name": f"{ta_name}, {tb_name}",
                "bridge_entity_id": "",
                "bridge_node_id": "",
                "bridge_entity_name": "",
                "bridge_node_name": "",
            }
        )

    # 3. 1-Hop Factoid (Còn lại)
    fact_idx = 0
    for e in index.edges:
        if len(benchmark) >= num_questions:
            break
        eid = str(e.get("id", ""))
        u = str(e.get("source", ""))
        v = str(e.get("target", ""))
        if u == v or u in used_source_nodes or eid not in index.edges_by_id:
            continue
        u_node = index.nodes_by_id.get(u, {})
        v_node = index.nodes_by_id.get(v, {})
        u_name = str(u_node.get("name", "")).strip()
        v_name = str(v_node.get("name", "")).strip()
        v_kind = str(v_node.get("kind") or "").strip()
        rel = str(e.get("relation", "")).strip()
        if not u_name or not v_name or len(u_name.split()) < 2 or normal(u_name) in GENERIC_ENTITY_NAMES:
            continue
        if index.degree.get(u, 0) > 30:
            continue

        fact_idx += 1
        q_text = synthesize_1hop_natural_question(u_name, rel, v_name, v_kind, idx_seed=fact_idx)
        if q_text in seen_queries:
            continue
        seen_queries.add(q_text)
        used_source_nodes.add(u)
        benchmark.append(
            {
                "id": f"qa_1hop_{len(benchmark) + 1:02d}",
                "category": "1-Hop Factoid (Tra cứu trực tiếp)",
                "type": "1-Hop Factoid (Tra cứu trực tiếp)",
                "question": q_text,
                "gold_answer": f"{u_name} ──[{rel}]──► {v_name}",
                "short_answer": v_name,
                "gold_node_ids": [u, v],
                "gold_edge_ids": [eid],
                "target_entity_id": v,
                "target_node_id": v,
                "target_entity_name": v_name,
                "expected_answer_name": v_name,
                "bridge_entity_id": "",
                "bridge_node_id": "",
                "bridge_entity_name": "",
                "bridge_node_name": "",
            }
        )

    return benchmark


def generate_training_qa_dataset(
    project: dict[str, Any],
    *,
    max_samples: int = 2000,
    train_ratio: float = 0.80,
    val_ratio: float = 0.10,
    approved_only: bool = True,
) -> dict[str, Any]:
    """Sinh bộ dữ liệu Huấn luyện & Đánh giá G-Retriever quy mô lớn đa cấu trúc bằng ngôn ngữ tự nhiên."""
    from backend.domain.graph.g_retriever import get_or_build_graph_index

    index = get_or_build_graph_index(project, approved_only=approved_only)
    node_pyg_map: dict[str, int] = {str(n["id"]): idx for idx, n in enumerate(index.nodes)}
    edge_pyg_map: dict[str, int] = {str(e["id"]): idx for idx, e in enumerate(index.edges)}

    seen_questions: set[str] = set()
    buckets: dict[str, list[dict[str, Any]]] = {
        "2hop_bridge": [],
        "2hop_intersection": [],
        "multi_attr_star": [],
        "explain_path": [],
        "1hop_forward": [],
        "1hop_inverse": [],
    }

    q_2hop_cap = max(40, int(max_samples * 0.25))
    q_inter_cap = max(30, int(max_samples * 0.15))
    q_star_cap = max(30, int(max_samples * 0.18))
    q_expl_cap = max(30, int(max_samples * 0.12))
    q_1hop_f_cap = max(40, int(max_samples * 0.20))
    q_1hop_i_cap = max(25, max_samples - (q_2hop_cap + q_inter_cap + q_star_cap + q_expl_cap + q_1hop_f_cap))

    def _make_sample(
        cat_key: str,
        cat_label: str,
        question: str,
        short_ans: str,
        full_ans: str,
        gold_chain: str,
        seed_ids: list[str],
        gold_nids: list[str],
        gold_edges: list[dict[str, Any]],
        target_id: str,
        bridge_id: str = "",
        bridge_name: str = "",
    ) -> None:
        if question in seen_questions:
            return
        seen_questions.add(question)
        gold_eids = [str(e["id"]) for e in gold_edges]
        sub_txt = _build_mini_textualized_subgraph(index.nodes_by_id, gold_nids, gold_edges, set(seed_ids))
        buckets[cat_key].append(
            {
                "category": cat_label,
                "type": cat_label,
                "question": question,
                "short_answer": short_ans,
                "answer": full_ans,
                "gold_answer": gold_chain,
                "seed_node_ids": seed_ids,
                "gold_node_ids": gold_nids,
                "gold_edge_ids": gold_eids,
                "seed_pyg_ids": [node_pyg_map[nid] for nid in seed_ids if nid in node_pyg_map],
                "gold_pyg_node_ids": [node_pyg_map[nid] for nid in gold_nids if nid in node_pyg_map],
                "gold_pyg_edge_ids": [edge_pyg_map[eid] for eid in gold_eids if eid in edge_pyg_map],
                "target_entity_id": target_id,
                "target_node_id": target_id,
                "target_entity_name": short_ans,
                "expected_answer_name": short_ans,
                "bridge_entity_id": bridge_id,
                "bridge_node_id": bridge_id,
                "bridge_entity_name": bridge_name,
                "bridge_node_name": bridge_name,
                "textualized_subgraph": sub_txt,
            }
        )

    # 1. 2-Hop Bridge & Explainable Path
    step_counter = 0
    for u, e1_list in index.out_edges.items():
        if len(buckets["2hop_bridge"]) >= q_2hop_cap and len(buckets["explain_path"]) >= q_expl_cap:
            break
        u_node = index.nodes_by_id.get(u, {})
        u_name = str(u_node.get("name", "")).strip()
        if not u_name or normal(u_name) in GENERIC_ENTITY_NAMES or index.degree.get(u, 0) > 35:
            continue

        per_u_cnt = 0
        for e1 in e1_list:
            if per_u_cnt >= 3:
                break
            b = str(e1.get("target", ""))
            if b == u or not (2 <= index.degree.get(b, 0) <= 30):
                continue
            b_node = index.nodes_by_id.get(b, {})
            b_name = str(b_node.get("name", "")).strip()
            b_kind = str(b_node.get("kind") or "đối tượng").strip()
            if not b_name or normal(b_name) in GENERIC_ENTITY_NAMES or normal(b_kind) in ("mốc thời gian", "số đo"):
                continue
            r1 = str(e1.get("relation", "")).strip()
            ev1 = str(e1.get("evidence", "")).strip()

            for e2 in index.out_edges.get(b, ()):
                c = str(e2.get("target", ""))
                if c in (u, b):
                    continue
                c_node = index.nodes_by_id.get(c, {})
                c_name = str(c_node.get("name", "")).strip()
                c_kind = str(c_node.get("kind") or "thực thể").strip()
                r2 = str(e2.get("relation", "")).strip()
                ev2 = str(e2.get("evidence", "")).strip()
                if not c_name or not r1 or not r2 or r1 == r2 or normal(c_name) in GENERIC_ENTITY_NAMES:
                    continue

                step_counter += 1
                chain_str = f"{u_name} ──[{r1}]──► {b_name} ──[{r2}]──► {c_name}"
                ans_str = (
                    f"Thực thể đích là **{c_name}** (thông qua cầu nối trung gian **{b_name}**).\n"
                    f"- Bước 1: {u_name} {clean_rel_name(r1)} {b_name} — Bằng chứng: \"{ev1}\" [{e1['id']} | {e1.get('doc_name', '')}].\n"
                    f"- Bước 2: {b_name} {clean_rel_name(r2)} {c_name} — Bằng chứng: \"{ev2}\" [{e2['id']} | {e2.get('doc_name', '')}]."
                )

                if len(buckets["2hop_bridge"]) < q_2hop_cap:
                    q_b = synthesize_2hop_bridge_question(
                        u_name, r1, b_name, b_kind, r2, c_name, c_kind, idx_seed=step_counter
                    )
                    _make_sample(
                        "2hop_bridge",
                        "2-Hop Bridge (Suy luận bắc cầu)",
                        q_b,
                        c_name,
                        ans_str,
                        chain_str,
                        [u],
                        [u, b, c],
                        [e1, e2],
                        c,
                        bridge_id=b,
                        bridge_name=b_name,
                    )
                    per_u_cnt += 1

                if len(buckets["explain_path"]) < q_expl_cap and step_counter % 2 == 0:
                    q_e = synthesize_explain_question(u_name, c_name, b_name, idx_seed=step_counter)
                    _make_sample(
                        "explain_path",
                        "Explainable Path (Giải thích liên kết)",
                        q_e,
                        b_name,
                        ans_str,
                        chain_str,
                        [u, c],
                        [u, b, c],
                        [e1, e2],
                        c,
                        bridge_id=b,
                        bridge_name=b_name,
                    )
                break

    # 2. 2-Hop Intersection
    inter_idx = 0
    for c, in_list in index.in_edges.items():
        if len(buckets["2hop_intersection"]) >= q_inter_cap:
            break
        if not (2 <= len(in_list) <= 25):
            continue
        c_node = index.nodes_by_id.get(c, {})
        c_name = str(c_node.get("name", "")).strip()
        c_kind = str(c_node.get("kind") or "thực thể").strip()
        if not c_name or normal(c_name) in GENERIC_ENTITY_NAMES:
            continue

        distinct_in: list[dict[str, Any]] = []
        seen_srcs: set[str] = set()
        for e_in in in_list:
            s_id = str(e_in.get("source", ""))
            if s_id != c and s_id not in seen_srcs and s_id in index.nodes_by_id:
                seen_srcs.add(s_id)
                distinct_in.append(e_in)
            if len(distinct_in) >= 3:
                break
        if len(distinct_in) < 2:
            continue

        e1, e2 = distinct_in[0], distinct_in[1]
        a_id, b_id = str(e1["source"]), str(e2["source"])
        a_name = str(index.nodes_by_id[a_id].get("name", "")).strip()
        b_name = str(index.nodes_by_id[b_id].get("name", "")).strip()
        r1 = str(e1.get("relation", "")).strip()
        r2 = str(e2.get("relation", "")).strip()
        if not a_name or not b_name or a_name == b_name:
            continue

        inter_idx += 1
        q_i = synthesize_intersection_question(a_name, r1, b_name, r2, c_name, c_kind, idx_seed=inter_idx)
        chain_i = f"{a_name} ──[{r1}]──► {c_name} ◄──[{r2}]── {b_name}"
        ans_i = (
            f"Thực thể giao điểm chung là **{c_name}** ({c_kind}).\n"
            f"- Nhánh 1: {a_name} {clean_rel_name(r1)} {c_name} — Bằng chứng: \"{e1.get('evidence', '')}\" [{e1['id']} | {e1.get('doc_name', '')}].\n"
            f"- Nhánh 2: {b_name} {clean_rel_name(r2)} {c_name} — Bằng chứng: \"{e2.get('evidence', '')}\" [{e2['id']} | {e2.get('doc_name', '')}]."
        )
        _make_sample(
            "2hop_intersection",
            "2-Hop Intersection (Giao điểm 2 thực thể)",
            q_i,
            c_name,
            ans_i,
            chain_i,
            [a_id, b_id],
            [a_id, b_id, c],
            [e1, e2],
            c,
        )

    # 3. Multi-Attribute Star
    star_idx = 0
    for u, e_list in index.out_edges.items():
        if len(buckets["multi_attr_star"]) >= q_star_cap:
            break
        if len(e_list) < 2:
            continue
        u_node = index.nodes_by_id.get(u, {})
        u_name = str(u_node.get("name", "")).strip()
        if not u_name or normal(u_name) in GENERIC_ENTITY_NAMES:
            continue

        distinct_edges: list[dict[str, Any]] = []
        seen_rels: set[str] = set()
        for e in e_list:
            rn = normal(str(e.get("relation", "")))
            if rn and rn not in seen_rels and str(e.get("target", "")) != u:
                seen_rels.add(rn)
                distinct_edges.append(e)
            if len(distinct_edges) >= 3:
                break
        if len(distinct_edges) < 2:
            continue

        e_a, e_b = distinct_edges[0], distinct_edges[1]
        t_a = index.nodes_by_id.get(str(e_a["target"]), {})
        t_b = index.nodes_by_id.get(str(e_b["target"]), {})
        ta_name = str(t_a.get("name", "")).strip()
        tb_name = str(t_b.get("name", "")).strip()
        if not ta_name or not tb_name:
            continue

        star_idx += 1
        q_s = synthesize_star_question(
            u_name, e_a.get("relation", ""), ta_name, e_b.get("relation", ""), tb_name, idx_seed=star_idx
        )
        short_s = f"{ta_name}; {tb_name}"
        chain_s = f"{u_name}: [{e_a.get('relation', '')}] -> {ta_name} & [{e_b.get('relation', '')}] -> {tb_name}"
        ans_s = (
            f"Thông tin tổng hợp về **{u_name}**:\n"
            f"- **{clean_rel_name(e_a.get('relation', ''))}**: **{ta_name}** — Bằng chứng: \"{e_a.get('evidence', '')}\" [{e_a['id']} | {e_a.get('doc_name', '')}].\n"
            f"- **{clean_rel_name(e_b.get('relation', ''))}**: **{tb_name}** — Bằng chứng: \"{e_b.get('evidence', '')}\" [{e_b['id']} | {e_b.get('doc_name', '')}]."
        )
        _make_sample(
            "multi_attr_star",
            "Multi-Attribute (Tổng hợp đa nhánh)",
            q_s,
            short_s,
            ans_s,
            chain_s,
            [u],
            [u, str(e_a["target"]), str(e_b["target"])],
            [e_a, e_b],
            str(e_b["target"]),
        )

    # 4. 1-Hop Factoid & 1-Hop Inverse
    edge_counter = 0
    for e in index.edges:
        if len(buckets["1hop_forward"]) >= q_1hop_f_cap and len(buckets["1hop_inverse"]) >= q_1hop_i_cap:
            break
        u = str(e.get("source", ""))
        v = str(e.get("target", ""))
        if u == v or u not in index.nodes_by_id or v not in index.nodes_by_id:
            continue
        u_node = index.nodes_by_id[u]
        v_node = index.nodes_by_id[v]
        u_name = str(u_node.get("name", "")).strip()
        v_name = str(v_node.get("name", "")).strip()
        u_kind = str(u_node.get("kind") or "thực thể").strip()
        v_kind = str(v_node.get("kind") or "thực thể").strip()
        rel = str(e.get("relation", "")).strip()
        ev = str(e.get("evidence", "")).strip()
        if not u_name or not v_name or not rel:
            continue

        edge_counter += 1
        if len(buckets["1hop_forward"]) < q_1hop_f_cap and normal(u_name) not in GENERIC_ENTITY_NAMES:
            q_f = synthesize_1hop_natural_question(u_name, rel, v_name, v_kind, idx_seed=edge_counter)
            ans_f = (
                f"Theo dữ liệu lịch sử, **{u_name}** {clean_rel_name(rel)} **{v_name}**.\n"
                f"- Bằng chứng nguyên văn: \"{ev}\" [{e['id']} | {e.get('doc_name', '')}]."
            )
            _make_sample(
                "1hop_forward",
                "1-Hop Factoid (Tra cứu xuôi)",
                q_f,
                v_name,
                ans_f,
                f"{u_name} ──[{rel}]──► {v_name}",
                [u],
                [u, v],
                [e],
                v,
            )

        if (
            len(buckets["1hop_inverse"]) < q_1hop_i_cap
            and normal(v_name) not in GENERIC_ENTITY_NAMES
            and index.degree.get(v, 0) <= 15
            and edge_counter % 2 == 1
        ):
            q_inv = synthesize_1hop_inverse_question(u_name, rel, v_name, u_kind, idx_seed=edge_counter)
            ans_inv = (
                f"Chủ thể {clean_rel_name(rel)} **{v_name}** là **{u_name}** ({u_kind}).\n"
                f"- Bằng chứng nguyên văn: \"{ev}\" [{e['id']} | {e.get('doc_name', '')}]."
            )
            _make_sample(
                "1hop_inverse",
                "1-Hop Inverse (Tra cứu ngược)",
                q_inv,
                u_name,
                ans_inv,
                f"{u_name} ──[{rel}]──► {v_name}",
                [v],
                [u, v],
                [e],
                u,
            )

    # Phân chia phân tầng (Stratified Split: 80% train, 10% val, 10% test)
    train_items: list[dict[str, Any]] = []
    val_items: list[dict[str, Any]] = []
    test_items: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}

    global_idx = 0
    for cat_key, cat_list in buckets.items():
        n_c = len(cat_list)
        if n_c == 0:
            continue
        cat_label = cat_list[0]["category"]
        category_counts[cat_label] = n_c
        n_train = int(round(n_c * train_ratio))
        n_val = int(round(n_c * val_ratio))
        if n_train + n_val > n_c:
            n_val = max(0, n_c - n_train)

        for i, item in enumerate(cat_list):
            global_idx += 1
            item["id"] = f"gret_qa_{global_idx:04d}"
            if i < n_train:
                item["split"] = "train"
                train_items.append(item)
            elif i < n_train + n_val:
                item["split"] = "val"
                val_items.append(item)
            else:
                item["split"] = "test"
                test_items.append(item)
            all_items.append(item)

    return {
        "total_samples": len(all_items),
        "train_count": len(train_items),
        "val_count": len(val_items),
        "test_count": len(test_items),
        "category_counts": category_counts,
        "all_samples": all_items,
        "train_samples": train_items,
        "val_samples": val_items,
        "test_samples": test_items,
    }


def paraphrase_qa_questions_with_llm(
    items: list[dict[str, Any]],
    *,
    provider: str = "DeepSeek",
    api_key: str = "",
    model: str = "deepseek-chat",
    base_url: str = "",
    client: Any = None,
    batch_size: int = 10,
) -> list[dict[str, Any]]:
    """Dùng LLM (DeepSeek / OpenAI) viết lại một danh sách câu hỏi thành văn phong người dùng thật 100%."""
    if not items:
        return []

    spec = providers.provider_spec(provider)
    try:
        LLMGateway._validate_credentials(spec, api_key, model, client)
        adapter = make_adapter(
            spec,
            api_key,
            providers.resolve_base_url(provider, base_url),
            client=client,
            timeout=90.0,
        )
    except Exception:
        # Nếu không có kết nối LLM thì trả về nguyên bản
        return items

    system_prompt = (
        "Bạn là chuyên gia ngôn ngữ học tiếng Việt. Nhiệm vụ của bạn là viết lại (paraphrase) danh sách câu hỏi "
        "thành văn phong tự nhiên 100% như người dùng thật gõ tìm kiếm trên Google hoặc hỏi trong đời thường.\n"
        "Quy tắc:\n"
        "1. Giữ nguyên nghĩa gốc, đúng tên riêng các thực thể lịch sử/địa danh.\n"
        "2. Tuyệt đối không dùng các từ ngữ máy móc như 'theo đồ thị tri thức', 'có mối quan hệ', 'đối tượng nào'.\n"
        "3. Trả về đúng định dạng JSON danh sách các chuỗi câu hỏi: [\"câu 1\", \"câu 2\", ...]."
    )

    updated_items = [dict(it) for it in items]
    for i in range(0, len(updated_items), batch_size):
        chunk = updated_items[i : i + batch_size]
        q_list = [it["question"] for it in chunk]
        user_prompt = f"Hãy viết lại tự nhiên {len(q_list)} câu hỏi sau:\n" + "\n".join(
            f"{idx + 1}. {q}" for idx, q in enumerate(q_list)
        )
        try:
            resp = adapter.chat(
                model=model,
                system=system_prompt,
                user=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            content = resp.content.strip()
            # Trích xuất JSON mảng
            m = re.search(r"\[.*\]", content, re.DOTALL)
            if m:
                paraphrased = json.loads(m.group(0))
                if isinstance(paraphrased, list) and len(paraphrased) == len(chunk):
                    for it, p_q in zip(chunk, paraphrased):
                        it["original_question"] = it["question"]
                        it["question"] = str(p_q).strip()
        except Exception:
            pass

    return updated_items
