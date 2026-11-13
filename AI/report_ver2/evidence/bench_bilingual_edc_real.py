"""Benchmark offline trên DỮ LIỆU THẬT của KG Studio (chỉ đọc, không sửa project/source).

Mục tiêu: kiểm chứng các giả thuyết của kế hoạch `bilingual-cidoc-edc-optimization-plan.md`
bằng gold do CON NGƯỜI đã duyệt trong các dự án thật (không dùng catalog/test tự soạn):

  Bài A (Schema Retriever +R): gold = quan hệ / loại thực thể của các cạnh "Đã duyệt" trong từng chunk.
  Bài B (Target Alignment)   : gold = canonical_name mà người dùng đã chọn khi gộp đề xuất (status=merged).

Chạy:  .\\.venv-win\\Scripts\\python.exe AI\\report_ver2\\evidence\\bench_bilingual_edc_real.py
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from backend.domain.documents.processor import document_chunks  # noqa: E402
from backend.integrations.embedder_gateway import EmbedderGateway  # noqa: E402
from shared.catalog_utils import relation_catalog  # noqa: E402
from shared.prompt_templates import format_canon_query, format_catalog_passage, format_sr_query  # noqa: E402
from shared.text_utils import clean_relation_name, normal, tokenize_vn  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
RNG = np.random.default_rng(20261114)
STATUS_OK = "Đã duyệt"

PROJECTS = {
    "kg_hanoi_edc_r_a": "tên ASCII snake_case, 1 token, KHÔNG khớp văn bản (giống 'name tiếng Anh' = nhiễu)",
    "hanoiqa6": "tên snake_case có dấu tiếng Việt (1 token)",
    "test1": "tên tiếng Việt có khoảng trắng (name mang tín hiệu thật)",
}

_STOP = {"của", "và", "các", "những", "một", "được", "trong", "cho", "với", "hoặc", "là", "có", "tại", "vào",
         "thuộc", "thực", "thể", "thực_thể", "nguồn", "đích"}


class HeadSplitEmbedder(EmbedderGateway):
    """Mô phỏng O2: tách vùng head theo `| , ;` (mỗi cụm <= 8 từ) thay vì cả cụm <= 6 từ. Chỉ dùng cho PASSAGE."""

    def _encode_hybrid_single(self, raw_text: str) -> np.ndarray:
        stripped = self._strip_instruct(raw_text)
        clean = normal(stripped)
        if not clean:
            return np.zeros(self.dim, dtype=np.float32)
        heads: list[str] = []
        if ":" in stripped:
            for sub in re.split(r"[|,;]+", stripped.split(":", 1)[0]):
                s = normal(sub)
                if 0 < len(s.split()) <= 8:
                    heads.append(s)
        base_tokens = set(tokenize_vn(clean, include_bigrams=True))
        padded_words = " " + " ".join(tokenize_vn(clean, include_bigrams=False)) + " "
        parts = [clean]
        for h in heads:
            parts += [h, h]
        for phrase, syns in self.synonym_map.items():
            np_ = normal(phrase)
            if "_".join(np_.split()) in base_tokens or f" {np_} " in padded_words:
                parts += syns + syns
        word = np.zeros(self.dim, dtype=np.float32)
        for tok in tokenize_vn(" ".join(parts), include_bigrams=True):
            if tok in _STOP:
                continue
            dg = hashlib.md5(tok.encode("utf-8")).digest()
            word[int.from_bytes(dg[:4], "little") % self.dim] += (1.0 if (dg[4] & 1) == 0 else -1.0) * (
                2.8 if "_" in tok else 1.4) * self.term_weights.get(tok, 1.0)
        n = float(np.linalg.norm(word))
        if n > 1e-8:
            word /= n
        chars = np.zeros(self.dim, dtype=np.float32)
        padded = f" {clean} "
        for k in (3, 4):
            for i in range(max(0, len(padded) - k + 1)):
                dg = hashlib.md5(f"c{k}:{padded[i:i + k]}".encode("utf-8")).digest()
                chars[int.from_bytes(dg[:4], "little") % self.dim] += 1.0 if (dg[4] & 1) == 0 else -1.0
        n = float(np.linalg.norm(chars))
        if n > 1e-8:
            chars /= n
        vec = 0.88 * word + 0.12 * chars
        n = float(np.linalg.norm(vec))
        return vec / n if n > 1e-8 else vec


BASE = EmbedderGateway("hybrid_vn:default")
SPLIT = HeadSplitEmbedder("hybrid_vn:default")


# ---- các cách dựng passage (đối tượng so sánh) ----------------------------------------------------------
def p_current(it: dict) -> str:
    return format_catalog_passage(it["name"], it.get("definition", ""), it.get("description", ""))


def _vn_text(it: dict) -> str:
    d, f = (it.get("description") or "").strip(), (it.get("definition") or "").strip()
    return f"{d}: {f}" if d and f else (f or d)


def p_hide_name(it: dict) -> str:  # Chiến lược D: bỏ name khỏi vector, fallback name nếu trống mô tả
    return _vn_text(it) or it["name"]


def p_name_tail(it: dict) -> str:  # Chiến lược C: mô tả VN lên head, name xuống cuối thân (1x)
    t = _vn_text(it)
    return f"{t} | {it['name']}" if t else it["name"]


VARIANTS = {
    "V0 hiện tại (name head 3x)": (p_current, BASE),
    "V1 ẩn name (D)": (p_hide_name, BASE),
    "V2 name xuống cuối (C)": (p_name_tail, BASE),
    "V3 ẩn name + head-split": (p_hide_name, SPLIT),
    "V4 name cuối + head-split": (p_name_tail, SPLIT),
}


# ---- nạp dữ liệu thật -----------------------------------------------------------------------------------
def load(name: str) -> dict:
    return json.loads((REPO / "data" / "projects" / name / "project.json").read_text(encoding="utf-8"))


def build_sr_gold(project: dict) -> list[dict]:
    rel_names = {r["name"] for r in relation_catalog(project)}
    type_names = {t["name"] for t in project.get("entity_types", [])}
    nodes = {n["id"]: n for n in project.get("nodes", [])}
    chunks = {(d["id"], c["chunk_number"]): c["text"] for d in project["documents"] for c in document_chunks(d)}
    gold: dict[tuple, dict] = collections.defaultdict(lambda: {"rel": set(), "type": set()})
    for e in project.get("edges", []):
        if e.get("status") != STATUS_OK:
            continue
        key = (e.get("doc_id"), e.get("chunk_number"))
        if key not in chunks:
            continue
        if e.get("relation") in rel_names:
            gold[key]["rel"].add(e["relation"])
        for nid in (e.get("source"), e.get("target")):
            kind = (nodes.get(nid) or {}).get("kind")
            if kind in type_names:
                gold[key]["type"].add(kind)
    return [{"text": chunks[k], **v} for k, v in gold.items() if v["rel"] or v["type"]]


def recall_curve(order: list[str], gold: set[str], ks: tuple[int, ...]) -> list[float]:
    return [len(gold & set(order[:k])) / len(gold) for k in ks]


def boot_ci(diff: np.ndarray, n: int = 2000) -> tuple[float, float]:
    idx = RNG.integers(0, len(diff), size=(n, len(diff)))
    means = diff[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def shrink_catalog(project: dict, cases: list[dict], n_rel: int = 76, n_type: int = 30):
    """Mô phỏng schema cỡ 76/30 của người dùng bằng dữ liệu thật: giữ n nhãn dùng nhiều nhất trong cạnh đã duyệt
    (schema được biên soạn thường xoay quanh nhãn phổ biến -> thiên về dễ, ghi rõ trong báo cáo)."""
    rel_freq = collections.Counter(r for c in cases for r in c["rel"])
    type_freq = collections.Counter(t for c in cases for t in c["type"])
    keep_r = {n for n, _ in rel_freq.most_common(n_rel)}
    keep_t = {n for n, _ in type_freq.most_common(n_type)}
    rels = [r for r in relation_catalog(project) if r["name"] in keep_r]
    types = [t for t in project.get("entity_types", []) if t["name"] in keep_t]
    new_cases = [{"text": c["text"], "rel": c["rel"] & keep_r, "type": c["type"] & keep_t} for c in cases]
    return rels, types, [c for c in new_cases if c["rel"] or c["type"]]


def bench_sr(project: dict, cases: list[dict], rels: list[dict] | None = None, types: list[dict] | None = None,
             ks_rel: tuple[int, ...] = (15, 30), ks_type: tuple[int, ...] = (10, 25)) -> dict:
    rels = rels if rels is not None else relation_catalog(project)
    types = types if types is not None else project.get("entity_types", [])
    queries = BASE.encode([format_sr_query(c["text"]) for c in cases])
    res: dict[str, dict] = {}
    for vname, (pf, enc) in VARIANTS.items():
        out = {}
        for kind, cat, ks in (("rel", rels, ks_rel), ("type", types, ks_type)):
            mat = enc.encode([pf(it) for it in cat])
            names = [it["name"] for it in cat]
            per_case = []
            for qi, c in enumerate(cases):
                if not c[kind]:
                    continue
                order = [names[i] for i in np.argsort(-(mat @ queries[qi]))]
                per_case.append(recall_curve(order, c[kind], ks))
            out[kind] = np.array(per_case)
        res[vname] = out
    return res


# ---- Bài B: Target Alignment ---------------------------------------------------------------------------
def nz(s: str, is_rel: bool) -> str:
    return normal(clean_relation_name(s)) if is_rel else normal(re.sub(r"[_\-]+", " ", s))


def bench_align(project: dict) -> dict:
    out: dict[str, dict] = {}
    for kind in ("relations", "entity_types"):
        cat = relation_catalog(project) if kind == "relations" else project.get("entity_types", [])
        names = [it["name"] for it in cat]
        name_set = set(names)
        gold = [p for p in project.get("schema_proposals", [])
                if p.get("status") == "merged" and p.get("kind") == kind
                and p.get("canonical_name") in name_set and normal(p["name"]) != normal(p["canonical_name"])
                and p.get("name") not in name_set]
        if not gold:
            continue
        queries = BASE.encode([format_canon_query(p["name"], p.get("definition") or p["name"]) for p in gold])
        variants = {"A0 hiện tại": (p_current, BASE), "A1 name cuối": (p_name_tail, BASE),
                    "A2 name cuối + head-split": (p_name_tail, SPLIT)}
        kres: dict = {"n": len(gold), "variants": {}}
        for vname, (pf, enc) in variants.items():
            mat = enc.encode([pf(it) for it in cat])
            top1 = top3 = 0
            scores1, correct1 = [], []
            for qi, p in enumerate(gold):
                sc = mat @ queries[qi]
                order = np.argsort(-sc)
                ranked = [names[i] for i in order[:3]]
                top1 += ranked[0] == p["canonical_name"]
                top3 += p["canonical_name"] in ranked
                scores1.append(float(sc[order[0]]))
                correct1.append(ranked[0] == p["canonical_name"])
            kres["variants"][vname] = {"top1": top1, "top3": top3, "scores": scores1, "correct": correct1}
        # luật khớp chính xác (alias/mô tả), chỉ tính khi KHỚP DUY NHẤT trên toàn catalog.
        # LEAVE-ONE-OUT: alias do CHÍNH quyết định gộp này tạo ra (alias == tên đề xuất) bị loại khỏi mục đích,
        # nếu không sẽ rò rỉ gold (hệ thống tự thêm tên đề xuất vào aliases của canonical khi gộp).
        is_rel = kind == "relations"
        rules = {}
        for rname, use_desc, normalize, loo in (
            ("R-raw alias, KHÔNG loại rò rỉ (sai phương pháp — chỉ để minh họa)", False, False, False),
            ("R-norm alias (LOO, chuẩn hóa 2 phía)", False, True, True),
            ("R-norm alias + cụm mô tả (LOO)", True, True, True),
        ):
            fired = correct = ambiguous = 0
            for p in gold:
                pkey = nz(p["name"], is_rel)
                key = nz(p["name"], is_rel) if normalize else normal(p["name"])
                hits = []
                for it in cat:
                    aliases = it.get("aliases") or []
                    if loo and it["name"] == p["canonical_name"]:
                        aliases = [a for a in aliases if nz(a, is_rel) != pkey]
                    keys = {normal(a) if not normalize else nz(a, is_rel) for a in aliases}
                    if use_desc:
                        keys |= {nz(x, is_rel) for x in re.split(r"[,;/|]+", it.get("description") or "") if x.strip()}
                    if key in keys:
                        hits.append(it["name"])
                if len(hits) == 1:
                    fired += 1
                    correct += hits[0] == p["canonical_name"]
                elif len(hits) > 1:
                    ambiguous += 1
            rules[rname] = {"fired": fired, "correct": correct, "ambiguous": ambiguous}
        kres["rules"] = rules
        # sanity: truy vấn bằng chính (name, definition) của mục catalog phải trả đúng mục đó (kiểm tra pipeline không hỏng)
        probe = [it for it in cat if it.get("definition")][:200]
        if probe:
            mat = BASE.encode([p_current(it) for it in cat])
            qv = BASE.encode([format_canon_query(it["name"], it["definition"]) for it in probe])
            nm = [it["name"] for it in cat]
            kres["sanity_self_top1"] = sum(nm[int(np.argmax(mat @ qv[i]))] == probe[i]["name"] for i in range(len(probe))) / len(probe)
        out[kind] = kres
    return out


def fmt(a: np.ndarray, base: np.ndarray | None, col: int) -> str:
    m = a[:, col].mean() * 100
    if base is None:
        return f"{m:5.1f}%"
    d = a[:, col] - base[:, col]
    lo, hi = boot_ci(d)
    return f"{m:5.1f}% (Δ{(d.mean()*100):+5.1f} [{lo*100:+.1f}; {hi*100:+.1f}])"


def sr_table(res: dict, lines: list[str], heads: tuple[str, str, str, str]) -> None:
    base = res["V0 hiện tại (name head 3x)"]
    lines.append(f"| Biến thể | {heads[0]} | {heads[1]} | {heads[2]} | {heads[3]} |\n|---|---|---|---|---|")
    for vname, r in res.items():
        b = None if vname.startswith("V0") else base
        cells = [fmt(r["rel"], None if b is None else b["rel"], 0), fmt(r["rel"], None if b is None else b["rel"], 1),
                 fmt(r["type"], None if b is None else b["type"], 0), fmt(r["type"], None if b is None else b["type"], 1)]
        lines.append(f"| {vname} | " + " | ".join(cells) + " |")


def main() -> None:
    names = sys.argv[1:] or list(PROJECTS)
    lines: list[str] = ["# Kết quả benchmark dữ liệu thật (tự sinh bởi bench_bilingual_edc_real.py)\n"]
    for pname in names:
        project = load(pname)
        cases = build_sr_gold(project)
        rels, types = relation_catalog(project), project.get("entity_types", [])
        lines.append(f"\n## Dự án `{pname}` — {PROJECTS.get(pname, 'dự án tùy chọn')}\n")
        lines.append(f"- Catalog: {len(rels)} quan hệ, {len(types)} loại | Chunk có gold: {len(cases)} | "
                     f"gold quan hệ: {sum(len(c['rel']) for c in cases)}, gold loại: {sum(len(c['type']) for c in cases)}\n")
        lines.append("\n### Bài A1 — Schema Retriever (+R), catalog ĐẦY ĐỦ: Recall trung bình theo chunk "
                     "(Δ so với V0, [CI95 bootstrap theo chunk])\n")
        sr_table(bench_sr(project, cases), lines, ("Rel R@15", "Rel R@30", "Type R@10", "Type R@25"))
        s_rels, s_types, s_cases = shrink_catalog(project, cases)
        lines.append(f"\n### Bài A2 — catalog thu nhỏ {len(s_rels)} quan hệ / {len(s_types)} loại (cỡ schema của người dùng), "
                     f"{len(s_cases)} chunk\n")
        sr_table(bench_sr(project, s_cases, s_rels, s_types, (15, 30), (10, 25)), lines,
                 ("Rel R@15", "Rel R@30", "Type R@10", "Type R@25"))
        al = bench_align(project)
        lines.append("\n### Bài B — Target Alignment: gold = canonical người dùng đã chọn khi gộp\n")
        if not al:
            lines.append("_Không có đề xuất `merged` hợp lệ để làm gold._\n")
        for kind, k in al.items():
            n = k["n"]
            lines.append(f"\n**{kind}** — n = {n} đề xuất đã gộp | sanity (truy vấn bằng chính mục catalog → Top-1): "
                         f"{k.get('sanity_self_top1', float('nan')):.0%}\n")
            lines.append("| Biến thể passage | Top-1 | Top-3 | Auto≥0.86: phủ / đúng | Auto≥0.60: phủ / đúng |\n|---|---|---|---|---|")
            for vname, v in k["variants"].items():
                sc, ok = np.array(v["scores"]), np.array(v["correct"])
                cells = [f"{int((sc >= t).sum())} / {int((ok & (sc >= t)).sum())}" for t in (0.86, 0.60)]
                lines.append(f"| {vname} | {v['top1']/n:.1%} | {v['top3']/n:.1%} | {cells[0]} | {cells[1]} |")
            lines.append("\n| Luật khớp chính xác (duy nhất) | Kích hoạt | Đúng | Mơ hồ (>1 mục) |\n|---|---|---|---|")
            for rname, r in k["rules"].items():
                lines.append(f"| {rname} | {r['fired']} | {r['correct']} | {r['ambiguous']} |")
    text = "\n".join(lines) + "\n"
    (OUT_DIR / "bench_results.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
