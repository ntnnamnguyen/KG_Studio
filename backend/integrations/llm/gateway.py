"""Facade `LLMGateway`: điểm gọi duy nhất cho trích xuất, kiểm tra kết nối và xác minh căn chỉnh."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from shared.catalog_utils import EDC_SCHEMA, validate_edc_payload
from shared.schemas.prompts import PreparedExtractionRequestDTO

from . import providers, token_budget
from .clients import make_adapter
from .errors import LLMError
from .parsing import build_user_message, clean_llm_json, pick_choice_letter
from .providers import ProviderSpec

_JSON_OBJECT_FORMAT = {"type": "json_object"}
_EDC_SCHEMA_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "edc_extraction", "strict": True, "schema": EDC_SCHEMA},
}


@dataclass
class ExtractionResult:
    data: dict
    input_tokens: int = 0
    output_tokens: int = 0
    raw: str = ""
    warnings: list[str] = field(default_factory=list)
    prepared_request: PreparedExtractionRequestDTO | None = None


class LLMGateway:
    """Cổng gọi LLM thống nhất. Giữ API tĩnh cũ để các engine, facade và UI không phải đổi."""

    PROVIDERS = providers.PROVIDERS
    DEFAULT_PROVIDER = providers.DEFAULT_PROVIDER
    DEFAULT_MODELS = providers.DEFAULT_MODELS

    # --- Tra cứu nhà cung cấp & ngân sách token ---
    provider_spec = staticmethod(providers.provider_spec)
    provider_key = staticmethod(providers.provider_key)
    resolve_base_url = staticmethod(providers.resolve_base_url)
    recommend_token_limits = staticmethod(token_budget.recommend_token_limits)
    build_user_message = staticmethod(build_user_message)

    @staticmethod
    def _validate_credentials(spec: ProviderSpec, api_key: str, model: str, client) -> None:
        if spec.requires_api_key and not (api_key or "").strip() and client is None:
            raise LLMError("Chưa nhập API key.", "auth")
        if not (model or "").strip():
            raise LLMError("Chưa nhập Model ID.", "model")

    # --- Chuẩn bị Request dùng chung (Preview & Execution Parity) ---
    @staticmethod
    def prepare_extraction_request(
        provider: str,
        model: str,
        system_prompt: str,
        chunk: str,
        allowed_relations: list[str],
        *,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 0,
        open_mode: bool = False,
        project_id: str = "",
        configuration_id: str = "",
        prompt_version_id: str = "",
        prompt_content_hash: str = "",
        base_instructions: str = "",
        appended_content: str = "",
        loop_index: int = 1,
        is_draft: bool = False,
        retrieval_summary: dict | None = None,
    ) -> PreparedExtractionRequestDTO:
        """Dựng dữ liệu request trích xuất hoàn chỉnh, tính toán ngân sách token, user message và mã băm request."""
        spec = providers.provider_spec(provider)
        warnings: list[str] = []
        raw_chars = len(chunk or "")

        fitted_chunk, warn_in = token_budget.fit_chunk_to_input_budget(chunk or "", system_prompt or "", max_input_tokens)
        out_tokens, warn_out = token_budget.clamp_output_tokens(provider, model, max_tokens)
        for w in (warn_in, warn_out):
            if w and w not in warnings:
                warnings.append(w)

        fitted_chars = len(fitted_chunk)
        if raw_chars > 0 and fitted_chars < raw_chars:
            cut_chars = raw_chars - fitted_chars
            cut_warn = f"Đoạn văn bản bị cắt bớt {cut_chars:,} ký tự do vượt ngân sách input tokens."
            if cut_warn not in warnings:
                warnings.append(cut_warn)

        resp_format = _JSON_OBJECT_FORMAT if (not open_mode or spec.key == "deepseek") else _EDC_SCHEMA_FORMAT
        user_msg = build_user_message(fitted_chunk, allowed_relations, open_mode)

        # Băm request chuẩn không chứa secret / api key
        hash_payload = (
            f"{provider}|{model}|{system_prompt}|{user_msg}|{temperature}|{out_tokens}|"
            f"{json.dumps(resp_format, sort_keys=True)}"
        )
        req_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

        cfg_id = configuration_id or ("edc" if open_mode else "closed")
        return PreparedExtractionRequestDTO(
            project_id=project_id,
            configuration_id=cfg_id,
            mode=cfg_id,
            prompt_version_id=prompt_version_id,
            prompt_content_hash=prompt_content_hash,
            base_instructions=base_instructions or system_prompt,
            appended_content=appended_content,
            system_prompt=system_prompt,
            user_message=user_msg,
            raw_chunk_text=chunk or "",
            fitted_chunk_text=fitted_chunk,
            raw_chars=raw_chars,
            fitted_chars=fitted_chars,
            allowed_relations=list(allowed_relations),
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=out_tokens,
            max_input_tokens=max_input_tokens,
            response_format=resp_format,
            warnings=warnings,
            loop_index=loop_index,
            request_hash=req_hash,
            is_draft=is_draft,
            retrieval_summary=dict(retrieval_summary or {}),
        )

    # --- Trích xuất tri thức ---
    @staticmethod
    def extract(
        provider: str,
        api_key: str,
        model: str,
        system_prompt: str,
        chunk: str,
        allowed_relations: list[str],
        *,
        base_url: str = "",
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 0,
        client=None,
        open_mode: bool = False,
        project_id: str = "",
        configuration_id: str = "",
        prompt_version_id: str = "",
        prompt_content_hash: str = "",
        base_instructions: str = "",
        appended_content: str = "",
        loop_index: int = 1,
        retrieval_summary: dict | None = None,
    ) -> ExtractionResult:
        spec = providers.provider_spec(provider)
        LLMGateway._validate_credentials(spec, api_key, model, client)

        prep = LLMGateway.prepare_extraction_request(
            provider,
            model,
            system_prompt,
            chunk,
            allowed_relations,
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            open_mode=open_mode,
            project_id=project_id,
            configuration_id=configuration_id,
            prompt_version_id=prompt_version_id,
            prompt_content_hash=prompt_content_hash,
            base_instructions=base_instructions,
            appended_content=appended_content,
            loop_index=loop_index,
            retrieval_summary=retrieval_summary,
        )

        warnings = list(prep.warnings)
        adapter = make_adapter(spec, api_key, providers.resolve_base_url(provider, base_url), client=client)
        resp = adapter.chat(
            model=model,
            system=prep.system_prompt,
            user=prep.user_message,
            temperature=prep.temperature,
            max_tokens=prep.max_tokens,
            response_format=prep.response_format,
        )
        warnings.extend(resp.warnings)

        if resp.finish_reason == "length":
            raise LLMError(
                f"Câu trả lời bị cắt do chạm giới hạn token (finish_reason=length, output={resp.output_tokens}/{prep.max_tokens} tokens). "
                f"Đoạn văn bản quá dài hoặc mật độ thực thể quá dày; hãy giảm 'Kích thước đoạn (chunk_size)' xuống khoảng 2000-2500 ký tự.",
                "token_limit",
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                raw=resp.content,
            )

        try:
            parsed = clean_llm_json(resp.content)
            data = validate_edc_payload(parsed) if open_mode else parsed
        except ValueError as exc:
            raise LLMError(
                f"Đầu ra JSON không đúng cấu trúc trích xuất: {exc}",
                "json",
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                raw=resp.content,
            ) from exc

        return ExtractionResult(
            data=data,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            raw=resp.content,
            warnings=warnings,
            prepared_request=prep,
        )

    # --- Kiểm tra kết nối ---
    @staticmethod
    def test_connection(provider: str, api_key: str, model: str, base_url: str = "", client=None) -> tuple[bool, str]:
        try:
            LLMGateway.extract(
                provider,
                api_key,
                model,
                'Chỉ trả JSON hợp lệ: {"thuc_the": [], "quan_he": []}.',
                "Kiểm tra kết nối JSON.",
                [],
                base_url=base_url,
                max_tokens=256,
                client=client,
                open_mode=False,
            )
            return True, f"Kết nối thành công với mô hình {model.strip()}."
        except Exception as exc:
            return False, f"Kết nối thất bại: {exc}"

    # --- Bộ xác minh căn chỉnh (Target Alignment) ---
    @staticmethod
    def verify_alignment_choice(
        provider: str,
        api_key: str,
        model: str,
        verification_prompt: str,
        valid_letters: list[str],
        *,
        base_url: str = "",
        client=None,
    ) -> str | None:
        """Hỏi LLM chọn 1 chữ cái trong `valid_letters`; mọi lỗi đều trả None (không chặn luồng chính)."""
        spec = providers.provider_spec(provider)
        try:
            adapter = make_adapter(
                spec,
                api_key,
                providers.resolve_base_url(provider, base_url),
                client=client,
                timeout=30.0,
                max_retries=0,
            )
            resp = adapter.chat(
                model=model,
                user=verification_prompt,
                temperature=0.0,
                max_tokens=8 if spec.api_style == providers.API_STYLE_ANTHROPIC else 16,
            )
            return pick_choice_letter(resp.content, valid_letters)
        except Exception:
            return None

