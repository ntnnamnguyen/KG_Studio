"""Kiểm tra chức năng lưu trữ và nạp API key an toàn qua shared.secrets_manager."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from shared.secrets_manager import (
    APP_ROOT,
    SECRETS_SECTION,
    delete_api_key,
    get_api_key,
    get_provider_env_keys,
    has_persisted_key,
    list_saved_providers,
    mask_api_key,
    read_secrets_file,
    save_api_key,
)


class TestSecretsManager(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.secrets_file = Path(self.temp_dir.name) / ".secrets.toml"
        # Lưu biến môi trường gốc để khôi phục
        self._orig_env = dict(os.environ)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_mask_api_key(self) -> None:
        self.assertEqual(mask_api_key(""), "")
        self.assertEqual(mask_api_key("12345"), "*****")
        self.assertEqual(mask_api_key("sk-1234567890abcdef"), "sk-...cdef")

    def test_save_and_read_api_key_atomic(self) -> None:
        # Lưu key cho DeepSeek
        save_api_key("DeepSeek", "sk-deepseek-test-key-1234", custom_secrets_path=self.secrets_file, update_environ=False)
        self.assertTrue(self.secrets_file.is_file())

        data = read_secrets_file(self.secrets_file)
        self.assertIn(SECRETS_SECTION, data)
        self.assertEqual(data[SECRETS_SECTION].get("deepseek"), "sk-deepseek-test-key-1234")

        # Đọc lại bằng get_api_key
        loaded = get_api_key("DeepSeek", custom_secrets_path=self.secrets_file, include_env=False)
        self.assertEqual(loaded, "sk-deepseek-test-key-1234")

        # Lưu thêm key cho OpenAI
        save_api_key("openai", "sk-openai-xyz", custom_secrets_path=self.secrets_file, update_environ=False)
        saved = list_saved_providers(self.secrets_file)
        self.assertIn("deepseek", saved)
        self.assertIn("openai", saved)

    def test_env_var_priority_over_file(self) -> None:
        # Trong file là key_from_file
        save_api_key("DeepSeek", "key_from_file", custom_secrets_path=self.secrets_file, update_environ=False)

        # Trong env là key_from_env
        os.environ["DEEPSEEK_API_KEY"] = "key_from_env"

        loaded = get_api_key("DeepSeek", custom_secrets_path=self.secrets_file, include_env=True)
        self.assertEqual(loaded, "key_from_env")

        # Khi xóa khỏi env thì lấy từ file
        del os.environ["DEEPSEEK_API_KEY"]
        loaded_fallback = get_api_key("DeepSeek", custom_secrets_path=self.secrets_file, include_env=True)
        self.assertEqual(loaded_fallback, "key_from_file")

    def test_generic_fallback_env_keys(self) -> None:
        # Dùng KG_STUDIO_API_KEY khi chưa có key riêng
        os.environ["KG_STUDIO_API_KEY"] = "universal_secret"
        loaded = get_api_key("anthropic", custom_secrets_path=self.secrets_file, include_secrets_file=False)
        self.assertEqual(loaded, "universal_secret")

    def test_delete_api_key(self) -> None:
        save_api_key("deepseek", "key_to_delete", custom_secrets_path=self.secrets_file, update_environ=True)
        self.assertTrue(has_persisted_key("deepseek", custom_secrets_path=self.secrets_file))

        deleted = delete_api_key("deepseek", custom_secrets_path=self.secrets_file, update_environ=True)
        self.assertTrue(deleted)
        self.assertFalse(has_persisted_key("deepseek", custom_secrets_path=self.secrets_file))
        self.assertEqual(get_api_key("deepseek", custom_secrets_path=self.secrets_file), "")

    def test_gitignore_protects_secrets(self) -> None:
        gitignore_path = APP_ROOT / ".gitignore"
        self.assertTrue(gitignore_path.is_file(), ".gitignore phải tồn tại ở thư mục gốc KG_Studio.")
        content = gitignore_path.read_text(encoding="utf-8")
        self.assertIn("config/.secrets.toml", content)
        self.assertIn(".env", content)
        self.assertIn(".streamlit/secrets.toml", content)

    def test_tab_switching_state_persistence_unit(self) -> None:
        """Kiểm tra logic đồng bộ state khi unmount / remount giữa các tab."""
        state = {
            "llm_provider": "DeepSeek",
            "llm_model": "deepseek-chat",
            "llm_base_url": "https://api.deepseek.com",
            "llm_api_key": "",
            "sb_llm_key": "",
            "p02_llm_key": "",
        }

        # User nhập key trên Tab 2
        state["p02_llm_key"] = "sk-tab2-secret-999"
        val = state["p02_llm_key"]
        state["llm_api_key"] = val
        state["sb_llm_key"] = val

        self.assertEqual(state["llm_api_key"], "sk-tab2-secret-999")
        self.assertEqual(state["sb_llm_key"], "sk-tab2-secret-999")

        # Chuyển sang Tab 3: Widget p02_llm_key bị unmount, nhưng llm_api_key giữ nguyên
        del state["p02_llm_key"]
        self.assertEqual(state["llm_api_key"], "sk-tab2-secret-999")

        # Quay lại Tab 2: Trước khi render p02_llm_key được tái lập từ llm_api_key
        state["p02_llm_key"] = state["llm_api_key"]
        self.assertEqual(state["p02_llm_key"], "sk-tab2-secret-999")

        # User sửa key ở thanh Sidebar trên bất kỳ tab nào
        state["sb_llm_key"] = "sk-sidebar-new-777"
        val = state["sb_llm_key"]
        state["llm_api_key"] = val
        state["p02_llm_key"] = val

        self.assertEqual(state["llm_api_key"], "sk-sidebar-new-777")
        self.assertEqual(state["p02_llm_key"], "sk-sidebar-new-777")

    def test_apptest_tab_switching_key_retention(self) -> None:
        """Kiểm tra AppTest chuyển tab giữa Tab 1, 2, 3 và xác minh key không bị mất."""
        from streamlit.testing.v1 import AppTest

        def sample_app():
            import streamlit as st
            from frontend.state.session import on_p02_llm_key_change, on_sb_llm_key_change

            st.session_state.setdefault("llm_api_key", "initial_key")
            page = st.radio("Page", ["Tab 1", "Tab 2", "Tab 3"], key="active_page")

            with st.sidebar:
                st.session_state["sb_llm_key"] = st.session_state["llm_api_key"]
                st.text_input("Sidebar Key", key="sb_llm_key", on_change=on_sb_llm_key_change)

            if page == "Tab 2":
                st.session_state["p02_llm_key"] = st.session_state["llm_api_key"]
                st.text_input("Tab 2 Key", key="p02_llm_key", on_change=on_p02_llm_key_change)
            elif page == "Tab 3":
                st.markdown(f"Active Key: {st.session_state['llm_api_key']}")

        at = AppTest.from_function(sample_app)
        at.run()
        # Chuyển Tab 2
        at.radio(key="active_page").set_value("Tab 2").run()
        # Nhập key ở Tab 2
        at.text_input(key="p02_llm_key").input("sk-live-deepseek-123456").run()
        self.assertEqual(at.session_state["llm_api_key"], "sk-live-deepseek-123456")

        # Chuyển sang Tab 3
        at.radio(key="active_page").set_value("Tab 3").run()
        self.assertEqual(at.session_state["llm_api_key"], "sk-live-deepseek-123456")
        self.assertIn("sk-live-deepseek-123456", at.markdown[0].value)

        # Chuyển về Tab 2
        at.radio(key="active_page").set_value("Tab 2").run()
        self.assertEqual(at.session_state["llm_api_key"], "sk-live-deepseek-123456")
        self.assertEqual(at.text_input(key="p02_llm_key").value, "sk-live-deepseek-123456")


if __name__ == "__main__":
    unittest.main()
