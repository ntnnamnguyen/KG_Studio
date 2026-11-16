"""Entrypoint thuận tiện cho Streamlit: streamlit run app.py"""
import importlib
import sys

_HOT_PATCH_REV = "2026-11-16-triple-dedup-v7"


def _ensure_hot_modules_synced() -> None:
    cat_mod = sys.modules.get("shared.catalog_utils")
    if cat_mod is not None and getattr(cat_mod, "_HOT_PATCH_REV", "") != _HOT_PATCH_REV:
        for mod_name in (
            "shared.constants",
            "shared.catalog_utils",
            "backend.integrations.llm.parsing",
            "backend.domain.prompts.service",
            "backend.domain.extraction.validator",
            "backend.domain.curation.merge_core",
            "backend.domain.curation.relation_merge",
            "backend.domain.curation.merge",
            "backend.domain.curation.service",
            "backend.modules.curation.application.service",
            "backend.modules.curation.public",
            "backend.bootstrap",
            "backend.facade",
            "frontend.composition",
            "frontend.client",
            "frontend.state.core",
            "frontend.state.session",
            "frontend.components.merge.provenance_view",
            "frontend.components.merge.triple_dedup_tab",
            "frontend.components.merge",
            "frontend.components.entity_merge_panel",
            "frontend.pages.p04_curation_hub",
            "frontend.pages.p03_extraction",
        ):
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
        cat_mod = sys.modules["shared.catalog_utils"]
        parse_mod = sys.modules.get("backend.integrations.llm.parsing")
        gw_mod = sys.modules.get("backend.integrations.llm.gateway")
        val_mod = sys.modules.get("backend.domain.extraction.validator")
        core_mod = sys.modules.get("backend.domain.catalogs.core")
        edcr_mod = sys.modules.get("backend.domain.extraction.engines.edc_plus_r")
        fac_mod = sys.modules.get("backend.facade")
        if gw_mod is not None and parse_mod is not None:
            setattr(gw_mod, "clean_llm_json", parse_mod.clean_llm_json)
            setattr(gw_mod, "validate_edc_payload", cat_mod.validate_edc_payload)
        if val_mod is not None:
            setattr(val_mod, "validate_edc_payload", cat_mod.validate_edc_payload)
        if core_mod is not None:
            setattr(core_mod, "edc_prompt", cat_mod.edc_prompt)
        if edcr_mod is not None:
            setattr(edcr_mod, "edc_prompt", cat_mod.edc_prompt)
        if fac_mod is not None and hasattr(fac_mod, "KGStudioFacade") and val_mod is not None:
            def _recover_key_typo_runs(self, project: dict) -> int:
                recovered = val_mod.recover_key_typo_runs(project)
                if recovered > 0:
                    self.save_project(project)
                return recovered
            setattr(fac_mod.KGStudioFacade, "recover_key_typo_runs", _recover_key_typo_runs)
        setattr(cat_mod, "_HOT_PATCH_REV", _HOT_PATCH_REV)


_ensure_hot_modules_synced()

from frontend.app import main

if __name__ == "__main__":
    main()
