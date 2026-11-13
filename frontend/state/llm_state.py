"""Đồng bộ cấu hình nhà cung cấp LLM, API key và giới hạn token giữa Sidebar và Trang 2."""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.integrations.llm import LLMGateway
from shared.secrets_manager import get_api_key


def _safe_set_widget_state(key: str, val: Any) -> None:
    """Gán an toàn vào session_state tránh lỗi StreamlitWidgetAlreadyInstantiatedError."""
    if st.session_state.get(key) == val:
        return
    try:
        st.session_state[key] = val
    except Exception:
        pass


def sync_llm_state_from_store() -> None:
    """Đồng bộ giá trị từ canonical session_state sang các widget keys (sb_* và p02_*)."""
    k = st.session_state.get("llm_api_key", "")
    _safe_set_widget_state("sb_llm_key", k)
    _safe_set_widget_state("p02_llm_key", k)

    m = st.session_state.get("llm_model", "")
    _safe_set_widget_state("sb_llm_model", m)
    _safe_set_widget_state("p02_llm_model", m)

    u = st.session_state.get("llm_base_url", "")
    _safe_set_widget_state("sb_llm_url", u)
    _safe_set_widget_state("p02_llm_url", u)

    p = st.session_state.get("llm_provider", LLMGateway.DEFAULT_PROVIDER)
    _safe_set_widget_state("sb_llm_provider", p)
    _safe_set_widget_state("p02_llm_prov", p)

    mi = int(st.session_state.get("llm_max_input_tokens", 16000))
    _safe_set_widget_state("sb_llm_max_in", mi)
    _safe_set_widget_state("p02_llm_max_in", mi)

    mo = int(st.session_state.get("llm_max_output_tokens", 16384))
    _safe_set_widget_state("sb_llm_max_out", mo)
    _safe_set_widget_state("p02_llm_max_out", mo)


def _sync_llm_state_field(field_name: str, src_key: str, dest_key: str, is_int: bool = False) -> None:
    raw = st.session_state.get(src_key, 0 if is_int else "")
    val = int(raw) if is_int else str(raw).strip()
    st.session_state[field_name] = val
    _safe_set_widget_state(dest_key, val)


def switch_llm_provider(new_provider: str) -> None:
    """Chuyển đổi nhà cung cấp LLM: cập nhật provider, model, URL, nạp API key đã lưu và đề xuất token."""
    if new_provider not in LLMGateway.PROVIDERS:
        return
    new_model = LLMGateway.DEFAULT_MODELS.get(new_provider, "")
    new_url = LLMGateway.resolve_base_url(new_provider)
    saved_key = get_api_key(new_provider)
    auto_rec = LLMGateway.recommend_token_limits(new_provider, new_model)
    st.session_state["extraction_chunk_size"] = auto_rec["recommended_chunk_size"]

    updates = {
        ("llm_provider", "sb_llm_provider", "p02_llm_prov"): new_provider,
        ("llm_model", "sb_llm_model", "p02_llm_model"): new_model,
        ("llm_base_url", "sb_llm_url", "p02_llm_url"): new_url,
        ("llm_api_key", "sb_llm_key", "p02_llm_key"): saved_key,
        ("llm_max_input_tokens", "sb_llm_max_in", "p02_llm_max_in"): auto_rec["max_input_tokens"],
        ("llm_max_output_tokens", "sb_llm_max_out", "p02_llm_max_out"): auto_rec["max_output_tokens"],
    }
    for (state_key, *widget_keys), val in updates.items():
        st.session_state[state_key] = val
        for w_key in widget_keys:
            _safe_set_widget_state(w_key, val)


def on_sb_llm_provider_change() -> None:
    """Callback đổi nhà cung cấp LLM từ Sidebar."""
    new_p = st.session_state.get("sb_llm_provider")
    if new_p and new_p in LLMGateway.PROVIDERS:
        switch_llm_provider(new_p)


def on_p02_llm_provider_change() -> None:
    """Callback đổi nhà cung cấp LLM từ Trang 2."""
    new_p = st.session_state.get("p02_llm_prov")
    if new_p and new_p in LLMGateway.PROVIDERS:
        switch_llm_provider(new_p)


def _make_llm_change_handler(field: str, src: str, dest: str, is_int: bool = False):
    def handler() -> None:
        _sync_llm_state_field(field, src, dest, is_int=is_int)
    return handler


on_sb_llm_key_change = _make_llm_change_handler("llm_api_key", "sb_llm_key", "p02_llm_key")
on_p02_llm_key_change = _make_llm_change_handler("llm_api_key", "p02_llm_key", "sb_llm_key")
on_sb_llm_model_change = _make_llm_change_handler("llm_model", "sb_llm_model", "p02_llm_model")
on_p02_llm_model_change = _make_llm_change_handler("llm_model", "p02_llm_model", "sb_llm_model")
on_sb_llm_url_change = _make_llm_change_handler("llm_base_url", "sb_llm_url", "p02_llm_url")
on_p02_llm_url_change = _make_llm_change_handler("llm_base_url", "p02_llm_url", "sb_llm_url")
on_sb_llm_max_in_change = _make_llm_change_handler("llm_max_input_tokens", "sb_llm_max_in", "p02_llm_max_in", is_int=True)
on_p02_llm_max_in_change = _make_llm_change_handler("llm_max_input_tokens", "p02_llm_max_in", "sb_llm_max_in", is_int=True)
on_sb_llm_max_out_change = _make_llm_change_handler("llm_max_output_tokens", "sb_llm_max_out", "p02_llm_max_out", is_int=True)
on_p02_llm_max_out_change = _make_llm_change_handler("llm_max_output_tokens", "p02_llm_max_out", "sb_llm_max_out", is_int=True)
