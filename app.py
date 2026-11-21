"""Entrypoint thuận tiện cho Streamlit: streamlit run app.py"""
import importlib
import sys

_HOT_PATCH_REV = "2026-11-17-state-sync-fix-v12"


def _ensure_hot_modules_synced() -> None:
    cat_mod = sys.modules.get("shared.catalog_utils")
    if cat_mod is not None and getattr(cat_mod, "_HOT_PATCH_REV", "") != _HOT_PATCH_REV:
        saved_container = getattr(sys.modules.get("backend.bootstrap"), "_CONTAINER", None)
        saved_facade = getattr(sys.modules.get("backend.facade"), "_FACADE", None)
        saved_comp = getattr(sys.modules.get("frontend.composition"), "_COMPOSITION", None)
        saved_client = getattr(sys.modules.get("frontend.client"), "_CLIENT", None)
        cfg_mod = sys.modules.get("shared.config_loader")
        if cfg_mod is not None and hasattr(cfg_mod, "load_config") and hasattr(cfg_mod, "CONFIG"):
            try:
                fresh_cfg = cfg_mod.load_config(getattr(cfg_mod, "CONFIG_PATH", None))
                cfg_mod.CONFIG.clear()
                cfg_mod.CONFIG.update(fresh_cfg)
            except Exception:
                pass
        for mod_name in (
            "shared.constants",
            "shared.catalog_utils",
            "backend.integrations.llm.token_budget",
            "backend.integrations.llm.parsing",
            "backend.integrations.llm.gateway",
            "backend.domain.prompts.service",
            "backend.domain.extraction.validator",
            "backend.domain.curation.merge_core",
            "backend.domain.curation.relation_merge",
            "backend.domain.curation.merge",
            "backend.domain.curation.service",
            "backend.modules.curation.application.service",
            "backend.modules.curation.public",
            "frontend.state.core",
            "frontend.state.curation_state",
            "frontend.state.session",
            "frontend.components.shared_curation_ui",
            "frontend.components.edc_bulk_actions.view",
            "frontend.components.edc_bulk_actions",
            "frontend.components.curation_table.entity_view",
            "frontend.components.curation_table",
            "frontend.components.evidence_panel.edge_inspector",
            "frontend.components.evidence_panel.entity_inspector",
            "frontend.components.evidence_panel",
            "frontend.components.merge.provenance_view",
            "frontend.components.merge.entity_tab",
            "frontend.components.merge.relation_tab",
            "frontend.components.merge.entity_type_tab",
            "frontend.components.merge.triple_dedup_tab",
            "frontend.components.merge",
            "frontend.components.ml_lab_panel",
            "frontend.components.entity_merge_panel",
            "frontend.pages.p02_catalogs_prompts",
            "frontend.pages.p04_curation_hub",
            "frontend.pages.p03_extraction",
            "frontend.pages.p05_graph_export",
        ):
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
        if saved_container is not None and "backend.bootstrap" in sys.modules:
            setattr(sys.modules["backend.bootstrap"], "_CONTAINER", saved_container)
        if saved_facade is not None and "backend.facade" in sys.modules:
            setattr(sys.modules["backend.facade"], "_FACADE", saved_facade)
        if saved_comp is not None and "frontend.composition" in sys.modules:
            setattr(sys.modules["frontend.composition"], "_COMPOSITION", saved_comp)
        if saved_client is not None and "frontend.client" in sys.modules:
            setattr(sys.modules["frontend.client"], "_CLIENT", saved_client)
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
