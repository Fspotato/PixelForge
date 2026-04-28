"""API Key Scope 檢查器，支援 wildcard 權限比對。"""


class ScopeChecker:
    """檢查 API Key 的 scope 權限，支援模組級 wildcard。"""

    @staticmethod
    def check(api_key_scopes: list[str], required_scope: str) -> bool:
        """檢查 API Key 是否有特定 scope 權限。

        空 scopes 代表無限制（全部放行）。
        支援 wildcard：
        - "*.*" → 所有權限
        - "module.*" → 該模組所有權限

        Args:
            api_key_scopes: API Key 定義的 scope 清單
            required_scope: 需要檢查的權限代碼

        Returns:
            bool: 是否具備該權限
        """
        if not api_key_scopes:
            return True

        for scope in api_key_scopes:
            if scope == "*.*" or scope == required_scope:
                return True
            if scope.endswith(".*"):
                module = scope[:-2]
                if required_scope.startswith(f"{module}."):
                    return True
        return False

    @staticmethod
    def get_effective_scopes(api_key_scopes: list[str], user_permissions: set[str]) -> set[str]:
        """計算有效權限 = RBAC 權限 ∩ API Key Scopes。

        API Key 的 scope 用來進一步限縮使用者本身的 RBAC 權限。
        若 API Key 無定義 scopes，則回傳使用者的完整權限。

        Args:
            api_key_scopes: API Key 定義的 scope 清單
            user_permissions: 使用者透過 RBAC 取得的權限集合

        Returns:
            set[str]: 交集後的有效權限
        """
        if not api_key_scopes:
            return user_permissions

        effective = set()
        for perm in user_permissions:
            if ScopeChecker.check(api_key_scopes, perm):
                effective.add(perm)
        return effective
