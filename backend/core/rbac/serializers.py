"""角色權限管理模組序列化器。"""

from rest_framework import serializers

from core._common import BaseModelSerializer, BaseSerializer

from .models import Permission, Role, UserRole


class PermissionSerializer(BaseModelSerializer):
    """權限序列化器。"""

    class Meta:
        model = Permission
        fields = [
            "id",
            "codename",
            "name",
            "module",
            "description",
            "is_system",
            "created_at",
        ]
        read_only_fields = ["id", "is_system", "created_at"]


class RoleSerializer(BaseModelSerializer):
    """角色序列化器（含巢狀權限）。"""

    permissions = PermissionSerializer(many=True, read_only=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True, default=None)

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "display_name",
            "description",
            "is_system",
            "is_default",
            "parent",
            "parent_name",
            "permissions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_system", "created_at", "updated_at"]


class RoleListSerializer(BaseModelSerializer):
    """角色列表序列化器（精簡）。"""

    permission_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "display_name",
            "description",
            "is_system",
            "is_default",
            "parent",
            "permission_count",
            "created_at",
        ]
        read_only_fields = fields

    def get_permission_count(self, obj) -> int:
        return obj.permissions.count()


class RoleCreateSerializer(BaseModelSerializer):
    """角色建立序列化器。"""

    class Meta:
        model = Role
        fields = [
            "name",
            "display_name",
            "description",
            "is_default",
            "parent",
        ]

    def validate_name(self, value):
        if Role.objects.filter(name=value).exists():
            raise serializers.ValidationError("角色代碼已存在")
        return value


class RoleUpdateSerializer(BaseModelSerializer):
    """角色更新序列化器。"""

    class Meta:
        model = Role
        fields = [
            "display_name",
            "description",
            "is_default",
            "parent",
        ]

    def validate(self, attrs):
        # 防止將系統角色的核心屬性修改
        instance = self.instance
        if instance and instance.is_system:
            if "parent" in attrs and attrs["parent"] != instance.parent:
                raise serializers.ValidationError({"parent": "系統角色的父角色不可修改"})
        return attrs


class UserRoleSerializer(BaseModelSerializer):
    """使用者角色序列化器。"""

    role_name = serializers.CharField(source="role.name", read_only=True)
    role_display_name = serializers.CharField(source="role.display_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    assigned_by_email = serializers.CharField(
        source="assigned_by.email", read_only=True, default=None
    )

    class Meta:
        model = UserRole
        fields = [
            "id",
            "user",
            "role",
            "role_name",
            "role_display_name",
            "user_email",
            "assigned_by",
            "assigned_by_email",
            "expires_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "assigned_by",
            "created_at",
        ]


class AssignRoleSerializer(BaseSerializer):
    """指派角色請求序列化器。"""

    role_id = serializers.UUIDField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate_role_id(self, value):
        if not Role.objects.filter(id=value).exists():
            raise serializers.ValidationError("指定的角色不存在")
        return value


class RolePermissionUpdateSerializer(BaseSerializer):
    """角色權限更新序列化器。"""

    permission_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
    )

    def validate_permission_ids(self, value):
        from .models import Permission

        existing = set(Permission.objects.filter(id__in=value).values_list("id", flat=True))
        missing = set(value) - existing
        if missing:
            raise serializers.ValidationError(f"以下權限 ID 不存在：{missing}")
        return value


class MyPermissionsSerializer(BaseSerializer):
    """使用者權限回應序列化器。"""

    permissions = serializers.ListField(child=serializers.CharField())
    roles = serializers.ListField(child=serializers.DictField())


class PermissionCheckSerializer(BaseSerializer):
    """權限檢查請求序列化器。"""

    permissions = serializers.ListField(
        child=serializers.CharField(max_length=100),
        min_length=1,
    )
    check_all = serializers.BooleanField(default=True, help_text="True=需全部擁有，False=任一即可")
