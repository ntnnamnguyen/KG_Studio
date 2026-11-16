"""Chuẩn hóa nhãn tiếng Việt ngắn gọn cho schema (node_types, relation_types) và câu hỏi KGQA song ngữ."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from shared.text_utils import normal


@dataclass(frozen=True)
class EntityTypeSpec:
    label_vi: str
    short_noun: str
    plural_noun: str
    role: str  # person | org | shrine | place | building | artifact | event | period | practice | literal
    bridge_allowed: bool = True


@dataclass(frozen=True)
class RelationSpec:
    relation_key: str
    label_vi: str
    semantic: str
    forward_wh: str
    list_wh: str
    inverse_clause: str
    bridge_clause: str
    english_phrase: str = ""


_GENERIC_BOILERPLATE_PREFIXES = (
    "tự động nạp",
    "loại thực thể",
    "ví dụ:",
    "quan hệ có hướng",
    "quan hệ giữa",
    "nguồn và đích",
)


ENTITY_TYPE_SPECS: dict[str, EntityTypeSpec] = {
    "e53_admin_area": EntityTypeSpec("Đơn vị hành chính", "đơn vị hành chính", "đơn vị hành chính", "place"),
    "admin_area": EntityTypeSpec("Đơn vị hành chính", "đơn vị hành chính", "đơn vị hành chính", "place"),
    "administrative_area": EntityTypeSpec("Đơn vị hành chính", "đơn vị hành chính", "đơn vị hành chính", "place"),
    "e53_settlement": EntityTypeSpec("Làng xã / Điểm dân cư", "làng xã", "làng xã", "place"),
    "settlement": EntityTypeSpec("Làng xã / Điểm dân cư", "làng xã", "làng xã", "place"),
    "e53_route": EntityTypeSpec("Tuyến đường / Phố", "tuyến đường", "tuyến đường", "place"),
    "route": EntityTypeSpec("Tuyến đường / Phố", "tuyến đường", "tuyến đường", "place"),
    "e53_natural_place": EntityTypeSpec("Địa điểm tự nhiên", "địa điểm tự nhiên", "địa điểm tự nhiên", "place"),
    "natural_place": EntityTypeSpec("Địa điểm tự nhiên", "địa điểm tự nhiên", "địa điểm tự nhiên", "place"),
    "e53_urban_space": EntityTypeSpec("Không gian đô thị", "khu vực đô thị", "khu vực đô thị", "place"),
    "urban_space": EntityTypeSpec("Không gian đô thị", "khu vực đô thị", "khu vực đô thị", "place"),
    "e53_place": EntityTypeSpec("Địa điểm", "địa điểm", "địa điểm", "place"),
    "place": EntityTypeSpec("Địa điểm", "địa điểm", "địa điểm", "place"),
    "location": EntityTypeSpec("Địa điểm", "địa điểm", "địa điểm", "place"),
    "historicplace": EntityTypeSpec("Địa điểm lịch sử", "địa điểm lịch sử", "địa điểm lịch sử", "place"),
    "e27_heritage_site": EntityTypeSpec("Di tích / Quần thể di sản", "di tích", "di tích", "shrine"),
    "heritage_site": EntityTypeSpec("Di tích / Quần thể di sản", "di tích", "di tích", "shrine"),
    "heritage": EntityTypeSpec("Di tích / Di sản", "di sản", "di sản", "shrine"),
    "monument": EntityTypeSpec("Di tích", "di tích", "di tích", "shrine"),
    "relic": EntityTypeSpec("Di tích", "di tích", "di tích", "shrine"),
    "e24_religious_building": EntityTypeSpec("Công trình tôn giáo / Tín ngưỡng", "di tích tôn giáo", "di tích tôn giáo", "shrine"),
    "religious_building": EntityTypeSpec("Công trình tôn giáo / Tín ngưỡng", "di tích tôn giáo", "di tích tôn giáo", "shrine"),
    "e24_fortification": EntityTypeSpec("Công trình phòng thủ / Thành quách", "công trình thành quách", "công trình thành quách", "shrine"),
    "fortification": EntityTypeSpec("Công trình phòng thủ / Thành quách", "công trình thành quách", "công trình thành quách", "shrine"),
    "e24_infrastructure": EntityTypeSpec("Công trình hạ tầng", "công trình hạ tầng", "công trình hạ tầng", "building"),
    "infrastructure": EntityTypeSpec("Công trình hạ tầng", "công trình hạ tầng", "công trình hạ tầng", "building"),
    "e24_market": EntityTypeSpec("Chợ truyền thống", "khu chợ", "khu chợ", "building"),
    "market": EntityTypeSpec("Chợ truyền thống", "khu chợ", "khu chợ", "building"),
    "e24_museum_building": EntityTypeSpec("Bảo tàng", "bảo tàng", "bảo tàng", "building"),
    "museum_building": EntityTypeSpec("Bảo tàng", "bảo tàng", "bảo tàng", "building"),
    "e24_cultural_building": EntityTypeSpec("Công trình văn hóa / Giáo dục", "công trình văn hóa", "công trình văn hóa", "building"),
    "cultural_building": EntityTypeSpec("Công trình văn hóa / Giáo dục", "công trình văn hóa", "công trình văn hóa", "building"),
    "e24_civic_building": EntityTypeSpec("Công trình công cộng", "công trình công cộng", "công trình công cộng", "building"),
    "civic_building": EntityTypeSpec("Công trình công cộng", "công trình công cộng", "công trình công cộng", "building"),
    "e24_memorial_building": EntityTypeSpec("Công trình tưởng niệm", "công trình tưởng niệm", "công trình tưởng niệm", "shrine"),
    "memorial_building": EntityTypeSpec("Công trình tưởng niệm", "công trình tưởng niệm", "công trình tưởng niệm", "shrine"),
    "e24_architectural_part": EntityTypeSpec("Bộ phận kiến trúc", "hạng mục kiến trúc", "hạng mục kiến trúc", "building"),
    "e25_architectural_part": EntityTypeSpec("Bộ phận kiến trúc", "hạng mục kiến trúc", "hạng mục kiến trúc", "building"),
    "architectural_part": EntityTypeSpec("Bộ phận kiến trúc", "hạng mục kiến trúc", "hạng mục kiến trúc", "building"),
    "architecturalpart": EntityTypeSpec("Bộ phận kiến trúc", "hạng mục kiến trúc", "hạng mục kiến trúc", "building"),
    "building": EntityTypeSpec("Công trình kiến trúc", "công trình", "công trình", "building"),
    "e21_person": EntityTypeSpec("Nhân vật lịch sử", "nhân vật lịch sử", "nhân vật lịch sử", "person"),
    "person": EntityTypeSpec("Nhân vật lịch sử", "nhân vật lịch sử", "nhân vật lịch sử", "person"),
    "e74_group": EntityTypeSpec("Tổ chức / Tập thể", "tổ chức hoặc đơn vị", "tổ chức hoặc đơn vị", "org"),
    "group": EntityTypeSpec("Tổ chức / Tập thể", "tổ chức hoặc đơn vị", "tổ chức hoặc đơn vị", "org"),
    "organization": EntityTypeSpec("Tổ chức / Triều đại", "tổ chức hoặc triều đại", "tổ chức hoặc triều đại", "org"),
    "e28_legendary_figure": EntityTypeSpec("Nhân vật truyền thuyết / Tín ngưỡng", "nhân vật tín ngưỡng", "nhân vật tín ngưỡng", "person"),
    "legendary_figure": EntityTypeSpec("Nhân vật truyền thuyết / Tín ngưỡng", "nhân vật tín ngưỡng", "nhân vật tín ngưỡng", "person"),
    "deity": EntityTypeSpec("Nhân vật tín ngưỡng", "vị thần hoặc nhân vật", "nhân vật tín ngưỡng", "person"),
    "e4_historical_period": EntityTypeSpec("Thời kỳ lịch sử", "thời kỳ lịch sử", "thời kỳ lịch sử", "period"),
    "historical_period": EntityTypeSpec("Thời kỳ lịch sử", "thời kỳ lịch sử", "thời kỳ lịch sử", "period"),
    "historicalperiod": EntityTypeSpec("Thời kỳ lịch sử", "thời kỳ lịch sử", "thời kỳ lịch sử", "period"),
    "e5_historical_event": EntityTypeSpec("Sự kiện lịch sử", "sự kiện lịch sử", "sự kiện lịch sử", "event"),
    "historical_event": EntityTypeSpec("Sự kiện lịch sử", "sự kiện lịch sử", "sự kiện lịch sử", "event"),
    "event": EntityTypeSpec("Sự kiện", "sự kiện", "sự kiện", "event"),
    "e12_construction_event": EntityTypeSpec("Sự kiện xây dựng", "đợt xây dựng", "đợt xây dựng", "event"),
    "construction_event": EntityTypeSpec("Sự kiện xây dựng", "đợt xây dựng", "đợt xây dựng", "event"),
    "e11_renovation_event": EntityTypeSpec("Sự kiện trùng tu", "đợt trùng tu", "đợt trùng tu", "event"),
    "renovation_event": EntityTypeSpec("Sự kiện trùng tu", "đợt trùng tu", "đợt trùng tu", "event"),
    "e7_cultural_event": EntityTypeSpec("Lễ hội / Sự kiện văn hóa", "lễ hội hoặc sự kiện", "lễ hội hoặc sự kiện", "event"),
    "cultural_event": EntityTypeSpec("Lễ hội / Sự kiện văn hóa", "lễ hội hoặc sự kiện", "lễ hội hoặc sự kiện", "event"),
    "e22_artifact": EntityTypeSpec("Hiện vật", "hiện vật", "hiện vật", "artifact"),
    "artifact": EntityTypeSpec("Hiện vật", "hiện vật", "hiện vật", "artifact"),
    "e34_inscription": EntityTypeSpec("Văn bia / Minh văn", "văn bia", "văn bia", "artifact"),
    "inscription": EntityTypeSpec("Văn bia / Minh văn", "văn bia", "văn bia", "artifact"),
    "e31_document": EntityTypeSpec("Tài liệu / Tư liệu", "tài liệu", "tài liệu", "artifact"),
    "document": EntityTypeSpec("Tài liệu / Tư liệu", "tài liệu", "tài liệu", "artifact"),
    "e55_cultural_practice": EntityTypeSpec("Nghề truyền thống / Tập quán", "nghề truyền thống hoặc tập quán", "nghề truyền thống hoặc tập quán", "practice"),
    "cultural_practice": EntityTypeSpec("Nghề truyền thống / Tập quán", "nghề truyền thống hoặc tập quán", "nghề truyền thống hoặc tập quán", "practice"),
    "e52_time_span": EntityTypeSpec("Mốc thời gian / Niên đại", "mốc thời gian", "mốc thời gian", "literal", bridge_allowed=False),
    "time_span": EntityTypeSpec("Mốc thời gian / Niên đại", "mốc thời gian", "mốc thời gian", "literal", bridge_allowed=False),
    "date": EntityTypeSpec("Mốc thời gian", "mốc thời gian", "mốc thời gian", "literal", bridge_allowed=False),
    "e54_dimension": EntityTypeSpec("Kích thước / Số đo", "số đo", "số đo", "literal", bridge_allowed=False),
    "dimension": EntityTypeSpec("Kích thước / Số đo", "số đo", "số đo", "literal", bridge_allowed=False),
    "e60_count": EntityTypeSpec("Số lượng", "số lượng", "số lượng", "literal", bridge_allowed=False),
    "count": EntityTypeSpec("Số lượng", "số lượng", "số lượng", "literal", bridge_allowed=False),
    "e57_material": EntityTypeSpec("Vật liệu / Chất liệu", "chất liệu", "chất liệu", "literal", bridge_allowed=False),
    "material": EntityTypeSpec("Vật liệu / Chất liệu", "chất liệu", "chất liệu", "literal", bridge_allowed=False),
    "e41_appellation": EntityTypeSpec("Tên gọi / Danh xưng", "tên gọi", "tên gọi", "literal", bridge_allowed=False),
    "appellation": EntityTypeSpec("Tên gọi / Danh xưng", "tên gọi", "tên gọi", "literal", bridge_allowed=False),
    "e55_type": EntityTypeSpec("Loại hình / Danh hiệu", "loại hình hoặc danh hiệu", "loại hình hoặc danh hiệu", "literal", bridge_allowed=False),
    "type": EntityTypeSpec("Loại hình / Danh hiệu", "loại hình hoặc danh hiệu", "loại hình hoặc danh hiệu", "literal", bridge_allowed=False),
}


RELATION_SPECS: dict[str, RelationSpec] = {
    "ADJACENT_TO": RelationSpec("ADJACENT_TO", "tiếp giáp với", "LOCATION", "tiếp giáp với địa điểm nào", "tiếp giáp với những địa điểm nào", "tiếp giáp với {obj}", "tiếp giáp với {obj}", "ADJACENT TO"),
    "AFFECTED": RelationSpec("AFFECTED", "tác động đến", "GENERAL", "tác động đến khu vực hay hạng mục nào", "tác động đến những khu vực hay hạng mục nào", "tác động đến {obj}", "tác động đến {obj}", "AFFECTED"),
    "ALSO_KNOWN_AS": RelationSpec("ALSO_KNOWN_AS", "còn gọi là", "APPELLATION", "còn được gọi là gì", "còn được gọi bằng những tên nào", "còn được gọi là {obj}", "còn gọi là {obj}", "ALSO KNOWN AS"),
    "ASSIGNED_TYPE": RelationSpec("ASSIGNED_TYPE", "được xếp loại là", "AWARD_RECOGNITION", "gắn với danh hiệu hay phân loại gì", "được xếp vào những loại hình hoặc danh hiệu nào", "gắn với phân loại {obj}", "được xếp loại {obj}", "ASSIGNED TYPE"),
    "AUTHORED_BY": RelationSpec("AUTHORED_BY", "được sáng tác bởi", "AGENT_CREATOR", "do ai sáng tác hoặc biên soạn", "do những tác giả nào sáng tác hoặc biên soạn", "do {obj} sáng tác", "được sáng tác bởi {obj}", "AUTHORED BY"),
    "BASED_ON": RelationSpec("BASED_ON", "dựa trên", "CONNECTION", "được xây dựng dựa trên nguồn hay công trình nào", "dựa trên những nguồn hay công trình nào", "dựa trên {obj}", "dựa trên {obj}", "BASED ON"),
    "BELONGS_TO_COLLECTION": RelationSpec("BELONGS_TO_COLLECTION", "thuộc bộ sưu tập", "CONTENT_CONTAINER", "thuộc bộ sưu tập hoặc nơi lưu giữ nào", "thuộc những bộ sưu tập hoặc nơi lưu giữ nào", "thuộc về {obj}", "thuộc bộ sưu tập {obj}", "BELONGS TO COLLECTION"),
    "BIRTHPLACE": RelationSpec("BIRTHPLACE", "sinh tại", "LOCATION", "sinh ra tại đâu", "sinh ra tại những địa điểm nào", "sinh ra tại {obj}", "sinh tại {obj}", "BIRTHPLACE"),
    "BORN_IN": RelationSpec("BORN_IN", "sinh năm", "TEMPORAL", "sinh vào thời gian nào", "sinh vào những mốc thời gian nào", "sinh vào {obj}", "sinh năm {obj}", "BORN IN"),
    "BUILT_BY": RelationSpec("BUILT_BY", "được xây dựng bởi", "AGENT_CREATOR", "do ai hoặc đơn vị nào xây dựng", "do những ai hoặc đơn vị nào xây dựng", "do {obj} xây dựng", "được xây dựng bởi {obj}", "BUILT BY"),
    "BUILT_IN": RelationSpec("BUILT_IN", "được xây dựng vào", "TEMPORAL", "được xây dựng vào thời gian nào", "được xây dựng qua những giai đoạn nào", "được xây dựng vào {obj}", "được xây dựng vào {obj}", "BUILT IN"),
    "COMMEMORATES": RelationSpec("COMMEMORATES", "tưởng niệm", "WORSHIP", "tưởng niệm nhân vật hay sự kiện nào", "tưởng niệm những nhân vật hay sự kiện nào", "tưởng niệm {obj}", "tưởng niệm {obj}", "COMMEMORATES"),
    "COMMISSIONED_BY": RelationSpec("COMMISSIONED_BY", "được cho xây dựng bởi", "AGENT_CREATOR", "do ai chủ trương hoặc cho xây dựng", "do những ai chủ trương hoặc cho xây dựng", "do {obj} cho xây dựng", "được {obj} cho xây dựng", "COMMISSIONED BY"),
    "COMPLETED_IN": RelationSpec("COMPLETED_IN", "hoàn thành năm", "TEMPORAL", "được hoàn thành vào thời gian nào", "được hoàn thành vào những năm nào", "hoàn thành vào {obj}", "hoàn thành vào {obj}", "COMPLETED IN"),
    "CONNECTS": RelationSpec("CONNECTS", "kết nối với", "CONNECTION", "kết nối với địa điểm hoặc tuyến nào", "kết nối với những địa điểm hoặc tuyến nào", "kết nối với {obj}", "kết nối với {obj}", "CONNECTS"),
    "CRAFTED_IN": RelationSpec("CRAFTED_IN", "được chế tác tại", "LOCATION", "được sản xuất hoặc chế tác tại đâu", "được chế tác tại những địa phương nào", "được chế tác tại {obj}", "được chế tác tại {obj}", "CRAFTED IN"),
    "CROSSES": RelationSpec("CROSSES", "bắc qua", "LOCATION", "bắc qua con sông hay tuyến đường nào", "bắc qua những con sông hay địa điểm nào", "bắc qua {obj}", "bắc qua {obj}", "CROSSES"),
    "DEPICTS": RelationSpec("DEPICTS", "khắc họa hình tượng", "CONNECTION", "khắc họa hoặc thể hiện hình tượng nào", "khắc họa những hình tượng nào", "khắc họa {obj}", "khắc họa {obj}", "DEPICTS"),
    "DESIGNED_BY": RelationSpec("DESIGNED_BY", "được thiết kế bởi", "AGENT_CREATOR", "do ai thiết kế", "do những ai thiết kế", "do {obj} thiết kế", "được thiết kế bởi {obj}", "DESIGNED BY"),
    "DESIGNED_IN": RelationSpec("DESIGNED_IN", "được thiết kế vào", "TEMPORAL", "được thiết kế vào thời gian nào", "được thiết kế vào những năm nào", "được thiết kế vào {obj}", "được thiết kế vào {obj}", "DESIGNED IN"),
    "DESTROYED_IN": RelationSpec("DESTROYED_IN", "bị phá hủy vào", "TEMPORAL", "bị phá hủy vào thời gian nào", "bị phá hủy qua những năm nào", "bị phá hủy vào {obj}", "bị phá hủy vào {obj}", "DESTROYED IN"),
    "DIED_IN": RelationSpec("DIED_IN", "mất năm", "TEMPORAL", "mất vào thời gian nào", "qua đời vào những mốc thời gian nào", "mất vào {obj}", "mất vào {obj}", "DIED IN"),
    "DISPLAYS": RelationSpec("DISPLAYS", "trưng bày", "CONTENT_CONTAINER", "đang trưng bày hiện vật hoặc bộ sưu tập nào", "đang trưng bày những hiện vật hoặc bộ sưu tập nào", "trưng bày {obj}", "trưng bày {obj}", "DISPLAYS"),
    "DOCUMENTS": RelationSpec("DOCUMENTS", "ghi chép về", "CONNECTION", "ghi chép về sự kiện hoặc đối tượng nào", "ghi chép về những sự kiện hoặc đối tượng nào", "ghi chép về {obj}", "ghi chép về {obj}", "DOCUMENTS"),
    "ENDS_AT": RelationSpec("ENDS_AT", "kết thúc tại", "LOCATION", "kết thúc tại đâu", "kết thúc tại những điểm nào", "kết thúc tại {obj}", "kết thúc tại {obj}", "ENDS AT"),
    "FORMER_NAME": RelationSpec("FORMER_NAME", "có tên cũ là", "APPELLATION", "trước đây có tên cũ là gì", "trước đây từng có những tên gọi cũ nào", "từng mang tên cũ là {obj}", "có tên cũ là {obj}", "FORMER NAME"),
    "FOUNDED_BY": RelationSpec("FOUNDED_BY", "được sáng lập bởi", "AGENT_CREATOR", "do ai hoặc tổ chức nào sáng lập", "do những ai hoặc tổ chức nào sáng lập", "do {obj} sáng lập", "được sáng lập bởi {obj}", "FOUNDED BY"),
    "FOUNDED_IN": RelationSpec("FOUNDED_IN", "được thành lập vào", "TEMPORAL", "được thành lập vào thời gian nào", "được thành lập vào những năm nào", "được thành lập vào {obj}", "thành lập vào {obj}", "FOUNDED IN"),
    "HAS_ADDRESS": RelationSpec("HAS_ADDRESS", "có địa chỉ tại", "LOCATION", "có địa chỉ ở đâu", "có những địa chỉ nào", "có địa chỉ tại {obj}", "tọa lạc tại địa chỉ {obj}", "HAS ADDRESS"),
    "HAS_AGE_PERIOD": RelationSpec("HAS_AGE_PERIOD", "có niên đại", "TEMPORAL", "có niên đại từ thời kỳ hoặc năm nào", "có niên đại qua những thời kỳ nào", "có niên đại {obj}", "thuộc niên đại {obj}", "HAS AGE PERIOD"),
    "HAS_ARCHITECTURAL_STYLE": RelationSpec("HAS_ARCHITECTURAL_STYLE", "mang phong cách kiến trúc", "AWARD_RECOGNITION", "mang phong cách kiến trúc nào", "mang những phong cách kiến trúc nào", "mang phong cách kiến trúc {obj}", "có kiến trúc {obj}", "HAS ARCHITECTURAL STYLE"),
    "HAS_AREA": RelationSpec("HAS_AREA", "có diện tích", "MEASUREMENT", "có diện tích bao nhiêu", "có những số đo diện tích nào", "có diện tích {obj}", "có diện tích {obj}", "HAS AREA"),
    "HAS_COMPONENT_COUNT": RelationSpec("HAS_COMPONENT_COUNT", "có số bộ phận", "MEASUREMENT", "gồm bao nhiêu bộ phận", "có những số lượng thành phần nào được ghi nhận", "gồm {obj}", "có số bộ phận là {obj}", "HAS COMPONENT COUNT"),
    "HAS_COORDINATE": RelationSpec("HAS_COORDINATE", "có tọa độ", "MEASUREMENT", "có tọa độ địa lý là gì", "có những tọa độ nào", "có tọa độ {obj}", "có tọa độ {obj}", "HAS COORDINATE"),
    "HAS_CRAFT": RelationSpec("HAS_CRAFT", "có nghề truyền thống", "CULTURE", "nổi tiếng với nghề truyền thống nào", "nổi tiếng với những nghề truyền thống nào", "nổi tiếng với nghề {obj}", "có nghề {obj}", "HAS CRAFT"),
    "HAS_FLOOR_COUNT": RelationSpec("HAS_FLOOR_COUNT", "có số tầng", "MEASUREMENT", "có bao nhiêu tầng", "có số tầng được ghi nhận là bao nhiêu", "có {obj}", "có {obj}", "HAS FLOOR COUNT"),
    "HAS_FUNCTION": RelationSpec("HAS_FUNCTION", "có chức năng", "AWARD_RECOGNITION", "có chức năng hoặc công năng gì", "có những chức năng gì", "có chức năng {obj}", "giữ chức năng {obj}", "HAS FUNCTION"),
    "HAS_HEIGHT": RelationSpec("HAS_HEIGHT", "có chiều cao", "MEASUREMENT", "có chiều cao bao nhiêu", "có những thông số chiều cao nào", "có chiều cao {obj}", "cao {obj}", "HAS HEIGHT"),
    "HAS_LENGTH": RelationSpec("HAS_LENGTH", "có chiều dài", "MEASUREMENT", "có chiều dài bao nhiêu", "có những thông số chiều dài nào", "có chiều dài {obj}", "dài {obj}", "HAS LENGTH"),
    "HAS_NAME": RelationSpec("HAS_NAME", "có tên gọi là", "APPELLATION", "có tên gọi là gì", "có những tên gọi nào", "mang tên {obj}", "có tên gọi là {obj}", "HAS NAME"),
    "HAS_OBJECT_COUNT": RelationSpec("HAS_OBJECT_COUNT", "có số lượng", "MEASUREMENT", "có số lượng là bao nhiêu", "có số lượng các hạng mục là bao nhiêu", "có số lượng {obj}", "có số lượng {obj}", "HAS OBJECT COUNT"),
    "HAS_PART": RelationSpec("HAS_PART", "có bộ phận", "CONTENT_CONTAINER", "gồm bộ phận hoặc hạng mục nào", "gồm những bộ phận hoặc thành phần nào", "có bộ phận là {obj}", "bao gồm {obj}", "HAS PART"),
    "HAS_PARTICIPANT": RelationSpec("HAS_PARTICIPANT", "có người tham dự", "EVENT_ACTIVITY", "có sự tham dự của ai hoặc đơn vị nào", "có sự tham dự của những ai hoặc đơn vị nào", "có sự tham gia của {obj}", "có người tham dự là {obj}", "HAS PARTICIPANT"),
    "HAS_PERIMETER": RelationSpec("HAS_PERIMETER", "có chu vi", "MEASUREMENT", "có chu vi bao nhiêu", "có những thông số chu vi nào", "có chu vi {obj}", "có chu vi {obj}", "HAS PERIMETER"),
    "HAS_RITUAL": RelationSpec("HAS_RITUAL", "có nghi lễ", "EVENT_ACTIVITY", "gồm nghi lễ nào", "bao gồm những nghi lễ nào", "có nghi lễ {obj}", "gồm nghi lễ {obj}", "HAS RITUAL"),
    "HAS_ROLE": RelationSpec("HAS_ROLE", "giữ chức danh", "DYNASTY_ORG", "đảm nhiệm vai trò hoặc chức danh gì", "đảm nhiệm những vai trò hoặc chức danh nào", "giữ chức danh {obj}", "đảm nhiệm vai trò {obj}", "HAS ROLE"),
    "HAS_TICKET_PRICE": RelationSpec("HAS_TICKET_PRICE", "có giá vé", "MEASUREMENT", "có giá vé tham quan bao nhiêu", "có những mức giá vé nào", "có giá vé {obj}", "có giá vé {obj}", "HAS TICKET PRICE"),
    "HAS_TRIBUTARY": RelationSpec("HAS_TRIBUTARY", "có phụ lưu", "LOCATION", "có dòng phụ lưu nào", "có những dòng phụ lưu nào", "có phụ lưu {obj}", "có phụ lưu {obj}", "HAS TRIBUTARY"),
    "HAS_TYPE": RelationSpec("HAS_TYPE", "thuộc loại", "AWARD_RECOGNITION", "thuộc loại hình hoặc danh hiệu gì", "thuộc những loại hình hoặc danh hiệu nào", "thuộc loại {obj}", "được xếp loại {obj}", "HAS TYPE"),
    "HAS_WIDTH": RelationSpec("HAS_WIDTH", "có chiều rộng", "MEASUREMENT", "có chiều rộng bao nhiêu", "có những thông số chiều rộng nào", "có chiều rộng {obj}", "rộng {obj}", "HAS WIDTH"),
    "HOLDS_COLLECTION": RelationSpec("HOLDS_COLLECTION", "lưu giữ bộ sưu tập", "CONTENT_CONTAINER", "lưu giữ bộ sưu tập nào", "lưu giữ những bộ sưu tập nào", "lưu giữ bộ sưu tập {obj}", "lưu giữ {obj}", "HOLDS COLLECTION"),
    "HOMETOWN": RelationSpec("HOMETOWN", "có quê quán tại", "LOCATION", "có quê quán ở đâu", "có quê quán tại những nơi nào", "có quê quán tại {obj}", "quê ở {obj}", "HOMETOWN"),
    "INCLUDES_NATURAL_FEATURE": RelationSpec("INCLUDES_NATURAL_FEATURE", "bao gồm địa hình", "CONTENT_CONTAINER", "bao gồm yếu tố địa hình tự nhiên nào", "bao gồm những yếu tố địa hình tự nhiên nào", "bao gồm {obj}", "chứa {obj}", "INCLUDES NATURAL FEATURE"),
    "IS_WORSHIPPED_AT": RelationSpec("IS_WORSHIPPED_AT", "thờ phụng", "WORSHIP", "thờ phụng ai hoặc nhân vật nào", "thờ phụng những nhân vật nào", "thờ phụng {obj}", "thờ phụng {obj}", "IS WORSHIPPED AT"),
    "WORSHIPPED_AT": RelationSpec("WORSHIPPED_AT", "được thờ tại", "WORSHIP", "được thờ phụng tại đâu", "được thờ phụng tại những địa điểm nào", "được thờ tại {obj}", "được thờ phụng tại {obj}", "WORSHIPPED AT"),
    "LEADS": RelationSpec("LEADS", "lãnh đạo", "DYNASTY_ORG", "lãnh đạo tổ chức hoặc lực lượng nào", "lãnh đạo những tổ chức hoặc lực lượng nào", "lãnh đạo {obj}", "đứng đầu {obj}", "LEADS"),
    "LOCATED_IN": RelationSpec("LOCATED_IN", "nằm ở", "LOCATION", "nằm ở đâu", "tọa lạc tại những địa điểm nào", "nằm ở {obj}", "tọa lạc tại {obj}", "LOCATED IN"),
    "MADE_OF": RelationSpec("MADE_OF", "được làm bằng", "MATERIAL", "được làm từ chất liệu gì", "được làm từ những chất liệu gì", "làm bằng {obj}", "được làm từ {obj}", "MADE OF"),
    "MEMBER_OF": RelationSpec("MEMBER_OF", "là thành viên của", "DYNASTY_ORG", "thuộc tổ chức hoặc triều đại nào", "thuộc những tổ chức hoặc triều đại nào", "thuộc về {obj}", "là thành viên của {obj}", "MEMBER OF"),
    "MODIFIED": RelationSpec("MODIFIED", "tác động cải tạo", "EVENT_ACTIVITY", "tác động cải tạo công trình hay hạng mục nào", "tác động cải tạo những công trình hay hạng mục nào", "cải tạo {obj}", "tác động cải tạo {obj}", "MODIFIED"),
    "NEAR": RelationSpec("NEAR", "nằm gần", "LOCATION", "nằm gần địa điểm nào", "nằm gần những địa điểm nào", "nằm gần {obj}", "ở gần {obj}", "NEAR"),
    "OCCURRED_AT": RelationSpec("OCCURRED_AT", "diễn ra tại", "LOCATION", "diễn ra tại đâu", "diễn ra tại những địa điểm nào", "diễn ra tại {obj}", "diễn ra ở {obj}", "OCCURRED AT"),
    "OCCURRED_ON": RelationSpec("OCCURRED_ON", "diễn ra vào", "TEMPORAL", "diễn ra vào thời gian nào", "diễn ra vào những mốc thời gian nào", "diễn ra vào {obj}", "diễn ra vào {obj}", "OCCURRED ON"),
    "ORGANIZED_BY": RelationSpec("ORGANIZED_BY", "được tổ chức bởi", "AGENT_CREATOR", "do ai hoặc đơn vị nào tổ chức", "do những ai hoặc đơn vị nào tổ chức", "do {obj} tổ chức", "được tổ chức bởi {obj}", "ORGANIZED BY"),
    "PARTICIPATED_IN": RelationSpec("PARTICIPATED_IN", "tham gia", "EVENT_ACTIVITY", "đã tham gia sự kiện hoặc hoạt động nào", "đã tham gia những sự kiện hoặc hoạt động nào", "tham gia {obj}", "từng tham gia {obj}", "PARTICIPATED IN"),
    "PART_OF": RelationSpec("PART_OF", "là bộ phận của", "PART_WHOLE", "là bộ phận của công trình hay tổng thể nào", "là bộ phận của những công trình hay tổng thể nào", "là bộ phận của {obj}", "thuộc cấu trúc của {obj}", "PART OF"),
    "PART_OF_PLACE": RelationSpec("PART_OF_PLACE", "thuộc khu vực", "LOCATION", "thuộc địa bàn hoặc khu vực nào", "thuộc những địa bàn hoặc khu vực nào", "thuộc khu vực {obj}", "trực thuộc {obj}", "PART OF PLACE"),
    "PRECEDED_BY": RelationSpec("PRECEDED_BY", "diễn ra sau", "TEMPORAL", "diễn ra sau sự kiện hoặc giai đoạn nào", "diễn ra sau những sự kiện hoặc giai đoạn nào", "diễn ra sau {obj}", "tiếp nối sau {obj}", "PRECEDED BY"),
    "PRODUCED": RelationSpec("PRODUCED", "tạo ra", "CAUSE_RESULT", "tạo ra sản phẩm hoặc hiện vật nào", "tạo ra những sản phẩm hoặc hiện vật nào", "tạo ra {obj}", "làm ra {obj}", "PRODUCED"),
    "RECOGNIZED_AS": RelationSpec("RECOGNIZED_AS", "được công nhận là", "AWARD_RECOGNITION", "được công nhận danh hiệu gì", "được công nhận những danh hiệu nào", "được công nhận là {obj}", "được xếp hạng là {obj}", "RECOGNIZED AS"),
    "RECOGNIZED_IN": RelationSpec("RECOGNIZED_IN", "được công nhận vào", "TEMPORAL", "được công nhận vào năm nào", "được công nhận vào những năm nào", "được công nhận vào {obj}", "được công nhận năm {obj}", "RECOGNIZED IN"),
    "RENOVATED_BY": RelationSpec("RENOVATED_BY", "được trùng tu bởi", "AGENT_CREATOR", "do ai hoặc đơn vị nào trùng tu", "do những ai hoặc đơn vị nào trùng tu", "do {obj} trùng tu", "được trùng tu bởi {obj}", "RENOVATED BY"),
    "RENOVATED_IN": RelationSpec("RENOVATED_IN", "được trùng tu vào", "TEMPORAL", "được trùng tu vào thời gian nào", "được trùng tu vào những năm nào", "được trùng tu vào {obj}", "trùng tu vào {obj}", "RENOVATED IN"),
    "RESULTED_IN": RelationSpec("RESULTED_IN", "dẫn đến", "CAUSE_RESULT", "dẫn đến sự kiện hoặc kết quả nào", "dẫn đến những sự kiện hoặc kết quả nào", "dẫn đến {obj}", "gây ra {obj}", "RESULTED IN"),
    "STARTS_AT": RelationSpec("STARTS_AT", "bắt đầu tại", "LOCATION", "bắt đầu tại đâu", "bắt đầu tại những điểm nào", "bắt đầu tại {obj}", "khởi đầu từ {obj}", "STARTS AT"),
    "SUCCEEDED": RelationSpec("SUCCEEDED", "kế nhiệm", "AGENT_CREATOR", "kế nhiệm nhân vật nào", "kế nhiệm những nhân vật nào", "kế nhiệm {obj}", "kế nhiệm {obj}", "SUCCEEDED"),
    # Các quan hệ tiếng Anh phổ biến trong dữ liệu trích xuất mở
    "HAS_DIMENSION": RelationSpec("HAS_DIMENSION", "có kích thước", "MEASUREMENT", "có kích thước bao nhiêu", "có những thông số kích thước nào", "có kích thước {obj}", "có kích thước {obj}", "has dimension"),
    "HAS_DEPTH": RelationSpec("HAS_DEPTH", "có độ sâu", "MEASUREMENT", "có độ sâu bao nhiêu", "có những thông số độ sâu nào", "có độ sâu {obj}", "sâu {obj}", "has depth"),
    "HAS_DIAMETER": RelationSpec("HAS_DIAMETER", "có đường kính", "MEASUREMENT", "có đường kính bao nhiêu", "có những thông số đường kính nào", "có đường kính {obj}", "có đường kính {obj}", "has diameter"),
    "HAS_THICKNESS": RelationSpec("HAS_THICKNESS", "có độ dày", "MEASUREMENT", "có độ dày bao nhiêu", "có những thông số độ dày nào", "có độ dày {obj}", "dày {obj}", "has thickness"),
    "HAS_WEIGHT": RelationSpec("HAS_WEIGHT", "có khối lượng", "MEASUREMENT", "có khối lượng bao nhiêu", "có những thông số khối lượng nào", "có khối lượng {obj}", "nặng {obj}", "has weight"),
    "HAS_MEASUREMENT": RelationSpec("HAS_MEASUREMENT", "có số đo", "MEASUREMENT", "có số đo bao nhiêu", "có những số đo nào", "có số đo {obj}", "có số đo {obj}", "has measurement"),
    "HAS_LAYER_COUNT": RelationSpec("HAS_LAYER_COUNT", "có số lớp", "MEASUREMENT", "gồm bao nhiêu lớp", "có số lớp được ghi nhận là bao nhiêu", "có {obj}", "gồm {obj}", "has layer count"),
    "INVOLVES": RelationSpec("INVOLVES", "liên quan đến", "CONNECTION", "liên quan đến đối tượng hoặc sự kiện nào", "liên quan đến những đối tượng hoặc sự kiện nào", "liên quan đến {obj}", "liên quan tới {obj}", "involves"),
    "PARALLEL_TO": RelationSpec("PARALLEL_TO", "song song với", "LOCATION", "nằm song song với tuyến hay hạng mục nào", "nằm song song với những tuyến hay hạng mục nào", "nằm song song với {obj}", "song song với {obj}", "parallel to"),
    "EQUIVALENT_TO": RelationSpec("EQUIVALENT_TO", "tương đương với", "APPELLATION", "tương đương với tên gọi hay khái niệm nào", "tương đương với những tên gọi nào", "tương đương với {obj}", "tương đương {obj}", "equivalent to"),
    "DID_MOVE_CAPITAL": RelationSpec("DID_MOVE_CAPITAL", "dời đô tới", "LOCATION", "dời đô tới địa điểm nào", "dời đô tới những địa điểm nào", "dời đô tới {obj}", "đã dời đô tới {obj}", "did move capital"),
    "DID_MOVE_CAPITAL_FROM": RelationSpec("DID_MOVE_CAPITAL_FROM", "dời đô từ", "LOCATION", "dời đô từ địa điểm nào", "dời đô từ những địa điểm nào", "dời đô từ {obj}", "đã dời đô từ {obj}", "did move capital from"),
}


_ENGLISH_TOKEN_MAP = {
    "has": "có",
    "built": "xây dựng",
    "located": "nằm",
    "part": "bộ phận",
    "of": "của",
    "in": "vào",
    "at": "tại",
    "by": "bởi",
    "on": "vào",
    "from": "từ",
    "to": "tới",
    "with": "với",
    "year": "năm",
    "date": "ngày",
    "period": "thời kỳ",
    "name": "tên gọi",
    "type": "loại hình",
    "area": "diện tích",
    "length": "chiều dài",
    "width": "chiều rộng",
    "height": "chiều cao",
    "depth": "độ sâu",
    "diameter": "đường kính",
    "thickness": "độ dày",
    "weight": "khối lượng",
    "count": "số lượng",
    "dimension": "kích thước",
    "measurement": "số đo",
    "material": "chất liệu",
    "style": "phong cách",
    "address": "địa chỉ",
    "founded": "thành lập",
    "created": "tạo dựng",
    "designed": "thiết kế",
    "renovated": "trùng tu",
    "worshipped": "được thờ",
    "member": "thành viên",
    "leader": "lãnh đạo",
    "leads": "lãnh đạo",
    "belongs": "thuộc",
    "collection": "bộ sưu tập",
    "parallel": "song song",
    "equivalent": "tương đương",
    "capital": "kinh đô",
    "place": "địa điểm",
}


_ENGLISH_SCHEMA_LEAK_RE = re.compile(
    r"\b[A-Z]{2,}(?:_[A-Z0-9]+)+\b"
    r"|\b(?:"
    + "|".join(
        re.escape(spec.english_phrase)
        for spec in RELATION_SPECS.values()
        if spec.english_phrase and spec.english_phrase.isupper()
    )
    + r")\b"
    r"|\b(?:did move capital(?: from)?|has (?:dimension|depth|diameter|thickness|weight|measurement|layer count)|parallel to|equivalent to)\b"
)


def _norm_schema_key(name: str) -> str:
    txt = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name or "").strip())
    txt = re.sub(r"[\s\-/]+", "_", txt.lower())
    return re.sub(r"_+", "_", txt).strip("_")


def _norm_rel_key(rel: str) -> str:
    txt = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(rel or "").strip())
    txt = re.sub(r"[\s\-]+", "_", txt.upper())
    return re.sub(r"_+", "_", txt).strip("_")


def _has_vietnamese_diacritics(text: str) -> bool:
    return bool(re.search(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", text.lower()))


def _clean_short_gloss(raw: str, *, lowercase_first: bool = False, max_len: int = 44) -> str:
    txt = str(raw or "").strip()
    if not txt:
        return ""
    low = txt.lower()
    if any(low.startswith(p) for p in _GENERIC_BOILERPLATE_PREFIXES):
        return ""
    if "..." in txt or "…" in txt:
        return ""
    # Lấy mệnh đề đầu trước dấu chấm / xuống dòng / chấm phẩy
    first = re.split(r"[\n.;?!]", txt, maxsplit=1)[0].strip(" :,-–—\"'")
    if not first or len(first) > max_len:
        return ""
    low_first = first.lower()
    if any(low_first.startswith(p) for p in _GENERIC_BOILERPLATE_PREFIXES):
        return ""
    if lowercase_first and first[0].isupper() and not (len(first) > 1 and first[1].isupper()):
        first = first[0].lower() + first[1:]
    return first


def resolve_entity_type_spec(
    type_name: str,
    raw_item: dict[str, Any] | None = None,
) -> EntityTypeSpec:
    """Chuẩn hóa thông tin loại thực thể sang nhãn tiếng Việt ngắn gọn và vai trò ngữ nghĩa."""
    key = _norm_schema_key(type_name)
    if key in ENTITY_TYPE_SPECS:
        return ENTITY_TYPE_SPECS[key]

    # Thử rút hậu tố sau mã CIDOC (ví dụ E99_MONUMENT -> monument)
    stripped_cidoc = re.sub(r"^e\d+[a-z]?_", "", key)
    if stripped_cidoc in ENTITY_TYPE_SPECS:
        return ENTITY_TYPE_SPECS[stripped_cidoc]

    cleaned_name = re.sub(r"_+", " ", str(type_name or "").strip()).strip()
    explicit_short = ""
    short_gloss = ""
    if isinstance(raw_item, dict):
        cand_lbl = _clean_short_gloss(str(raw_item.get("label_vi") or ""), lowercase_first=False, max_len=40)
        if cand_lbl and _has_vietnamese_diacritics(cand_lbl):
            explicit_short = cand_lbl
        else:
            for field in ("description", "definition"):
                cand = _clean_short_gloss(str(raw_item.get(field) or ""), lowercase_first=False, max_len=36)
                if cand and _has_vietnamese_diacritics(cand):
                    short_gloss = cand
                    break

    if explicit_short:
        label_vi = explicit_short
    elif cleaned_name and _has_vietnamese_diacritics(cleaned_name) and len(cleaned_name) <= 48:
        label_vi = cleaned_name[0].upper() + cleaned_name[1:] if len(cleaned_name) > 1 else cleaned_name.upper()
    elif short_gloss:
        label_vi = short_gloss
    elif cleaned_name and _has_vietnamese_diacritics(cleaned_name):
        label_vi = cleaned_name
    elif key:
        words = [_ENGLISH_TOKEN_MAP.get(w, w) for w in key.split("_") if w and not re.fullmatch(r"e\d+", w)]
        joined = " ".join(words).strip()
        label_vi = joined.capitalize() if joined else (cleaned_name or "Thực thể")
    else:
        label_vi = "Thực thể"

    low = normal(f"{label_vi} {key}")
    role = "building"
    bridge_allowed = True
    if any(k in low for k in ("thời kỳ", "triều đại", "period")):
        role = "period"
    elif any(k in low for k in ("nhân vật", "vua", "vị thần", "cá nhân", "person", "deity")):
        role = "person"
    elif any(k in low for k in ("tổ chức", "đơn vị", "tập thể", "hội", "group", "organization")):
        role = "org"
    elif any(k in low for k in ("địa danh", "địa điểm", "làng", "tỉnh", "thành phố", "quận", "huyện", "phường", "place", "area", "route")):
        role = "place"
    elif any(k in low for k in ("chùa", "đền", "đình", "miếu", "phủ", "di tích", "heritage", "monument", "religious", "tôn giáo", "tín ngưỡng")):
        role = "shrine"
    elif any(k in low for k in ("hiện vật", "bia", "tài liệu", "văn bản", "sách", "artifact", "document")):
        role = "artifact"
    elif any(k in low for k in ("sự kiện", "lễ hội", "chiến dịch", "trận", "event")):
        role = "event"
    elif any(k in low for k in ("thời gian", "năm", "ngày", "kích thước", "số đo", "số lượng", "chất liệu", "vật liệu", "tên gọi", "danh hiệu", "loại hình", "dimension", "count", "material", "time")):
        role = "literal"
        bridge_allowed = False

    noun = label_vi.split("/")[0].strip().lower() if "/" in label_vi else label_vi.lower()
    if len(noun) > 32 or not _has_vietnamese_diacritics(noun):
        noun = "đối tượng"
    return EntityTypeSpec(label_vi=label_vi, short_noun=noun, plural_noun=noun, role=role, bridge_allowed=bridge_allowed)


def resolve_entity_type_label_vi(type_name: str, raw_item: dict[str, Any] | None = None) -> str:
    return resolve_entity_type_spec(type_name, raw_item).label_vi


def is_valid_multihop_bridge_kind(type_name: str) -> bool:
    if not str(type_name or "").strip():
        return True
    return resolve_entity_type_spec(type_name).bridge_allowed


def resolve_worship_polarity(rel: str, source_kind: str = "", target_kind: str = "") -> str | None:
    """Xác định chiều thờ phụng: 'shrine_to_deity' (thờ phụng) hay 'deity_to_shrine' (được thờ tại)."""
    import unicodedata

    r_key = _norm_rel_key(rel)
    r_nfc = unicodedata.normalize("NFC", str(rel or "")).lower().strip()
    r_words = re.findall(r"[^\W\d_]+", r_nfc)
    is_worship = r_key in {"IS_WORSHIPPED_AT", "WORSHIPPED_AT"} or (
        ("tưởng niệm" not in r_nfc)
        and (
            "thờ phụng" in r_nfc
            or "thờ tự" in r_nfc
            or "thờ cúng" in r_nfc
            or "được thờ" in r_nfc
            or "thờ" in r_words
        )
    )
    if not is_worship:
        return None

    src_role = resolve_entity_type_spec(source_kind).role if source_kind else ""
    tgt_role = resolve_entity_type_spec(target_kind).role if target_kind else ""
    shrine_roles = {"shrine", "place", "building"}
    deity_roles = {"person", "org", "artifact"}

    # Kiểm tra trực tiếp theo loại thực thể để sửa cả cạnh đảo chiều trong dữ liệu thô
    if src_role in shrine_roles and tgt_role not in shrine_roles:
        return "shrine_to_deity"
    if src_role in deity_roles and tgt_role in shrine_roles:
        return "deity_to_shrine"
    if src_role == "shrine" and tgt_role in deity_roles:
        return "shrine_to_deity"

    if r_key == "IS_WORSHIPPED_AT":
        return "shrine_to_deity"
    if r_key == "WORSHIPPED_AT" or "được thờ" in r_nfc:
        return "deity_to_shrine"
    return "shrine_to_deity"


def _translate_fallback_english_relation(rel: str) -> str:
    tokens = [t for t in _norm_rel_key(rel).lower().split("_") if t]
    if not tokens:
        return ""
    vi_tokens = [_ENGLISH_TOKEN_MAP.get(t, "") for t in tokens]
    if all(vi_tokens):
        return " ".join(vi_tokens)
    translated = [(_ENGLISH_TOKEN_MAP.get(t, t)) for t in tokens]
    return " ".join(translated)


def _extract_concise_relation_gloss_from_notes(
    rel: str,
    relation_notes: dict[str, Any] | None = None,
) -> str:
    if not isinstance(relation_notes, dict):
        return ""
    note = relation_notes.get(rel)
    if not isinstance(note, dict):
        rel_n = normal(rel)
        for k, v in relation_notes.items():
            if normal(str(k)) == rel_n and isinstance(v, dict):
                note = v
                break
    if not isinstance(note, dict):
        return ""

    # Ưu tiên alias ngắn gọn không chứa dấu '...' hoặc mệnh đề đầu của definition
    aliases = note.get("aliases") or []
    if isinstance(aliases, list):
        for a in aliases:
            cand = _clean_short_gloss(str(a or ""), lowercase_first=True, max_len=38)
            if cand and _has_vietnamese_diacritics(cand):
                return cand
    for field in ("label_vi", "definition", "description"):
        cand = _clean_short_gloss(str(note.get(field) or ""), lowercase_first=True, max_len=40)
        if cand and _has_vietnamese_diacritics(cand):
            return cand
    return ""


def resolve_relation_spec(
    rel: str,
    *,
    source_kind: str = "",
    target_kind: str = "",
    relation_notes: dict[str, Any] | None = None,
) -> RelationSpec:
    """Trả về đặc tả ngữ nghĩa + cụm từ tiếng Việt chuẩn cho mọi quan hệ (Anh/Việt/CIDOC)."""
    polarity = resolve_worship_polarity(rel, source_kind=source_kind, target_kind=target_kind)
    if polarity == "shrine_to_deity":
        return RELATION_SPECS["IS_WORSHIPPED_AT"]
    if polarity == "deity_to_shrine":
        return RELATION_SPECS["WORSHIPPED_AT"]

    r_key = _norm_rel_key(rel)
    if r_key in RELATION_SPECS:
        return RELATION_SPECS[r_key]

    # Quan hệ đã là tiếng Việt (VD: 'tọa lạc tại', 'ban_hành_lệnh_cấm')
    raw_clean = re.sub(r"[_]+", " ", str(rel or "").strip())
    raw_clean = re.sub(r"\s+", " ", raw_clean).strip()
    if raw_clean and _has_vietnamese_diacritics(raw_clean):
        label_vi = raw_clean[0].lower() + raw_clean[1:] if len(raw_clean) > 1 else raw_clean.lower()
        return RelationSpec(
            relation_key=r_key,
            label_vi=label_vi,
            semantic="",
            forward_wh="",
            list_wh="",
            inverse_clause=f"{label_vi} {{obj}}",
            bridge_clause=f"{label_vi} {{obj}}",
        )

    # Thử rút từ relation_notes của dự án, nếu chưa có thì dịch token tiếng Anh
    note_gloss = _extract_concise_relation_gloss_from_notes(rel, relation_notes)
    fallback_vi = note_gloss or _translate_fallback_english_relation(rel) or raw_clean or "liên quan đến"
    if not _has_vietnamese_diacritics(fallback_vi):
        fallback_vi = "liên quan đến"
    return RelationSpec(
        relation_key=r_key,
        label_vi=fallback_vi,
        semantic="",
        forward_wh=f"{fallback_vi} đối tượng hay giá trị nào",
        list_wh=f"{fallback_vi} những đối tượng hay giá trị nào",
        inverse_clause=f"{fallback_vi} {{obj}}",
        bridge_clause=f"{fallback_vi} {{obj}}",
        english_phrase=raw_clean,
    )


def resolve_relation_label_vi(
    rel: str,
    *,
    relation_notes: dict[str, Any] | None = None,
) -> str:
    """Trả về label_vi ngắn gọn dạng cụm vị ngữ tiếng Việt cho schema_contract.json."""
    return resolve_relation_spec(rel, relation_notes=relation_notes).label_vi


def contains_raw_english_relation(text: str) -> bool:
    """Phát hiện mã quan hệ tiếng Anh (như BUILT_BY, BUILT BY, PART OF PLACE, has diameter) còn sót."""
    s = str(text or "").strip()
    if not s:
        return False
    return bool(_ENGLISH_SCHEMA_LEAK_RE.search(s))
