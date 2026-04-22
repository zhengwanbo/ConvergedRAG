import logging
import secrets
from datetime import datetime
from functools import wraps
from typing import Any

from quart import Response, jsonify, request

from admin.server.roles import RoleMgr
from admin.server.services import (
    ConfigMgr,
    EnvironmentsMgr,
    SandboxMgr,
    ServiceMgr,
    SettingsMgr,
    UserMgr,
    UserServiceMgr,
)
from api.apps import current_user, login_required, login_user, logout_user
from api.common.exceptions import AdminException, UserNotFoundError
from api.db import UserTenantRole
from api.db.services import UserService
from api.db.services.user_service import TenantService, UserTenantService
from api.utils.api_utils import generate_confirmation_token, get_request_json
from api.utils.crypt import decrypt
from common import settings
from common.connection_utils import construct_response
from common.constants import ActiveEnum, StatusEnum
from common.misc_utils import get_uuid
from common.time_utils import current_timestamp, datetime_format, get_format_time
from common.versions import get_ragflow_version

page_name = "admin"
url_prefix = "/admin/v1"


def success_response(data=None, message="Success", code=0):
    return jsonify({"code": code, "message": message, "data": data}), 200


def error_response(message="Error", code=-1, data=None):
    return jsonify({"code": code, "message": message, "data": data}), 400


def _check_admin_auth():
    user = UserService.filter_by_id(current_user.id)
    if not user:
      raise UserNotFoundError(current_user.email)
    if not user.is_superuser:
      raise AdminException("Not admin", 403)
    if user.is_active == ActiveEnum.INACTIVE.value:
      raise AdminException(f"User {current_user.email} inactive", 403)
    return user


def check_admin_auth(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        _check_admin_auth()
        return await func(*args, **kwargs)

    return wrapper


def init_default_admin():
    users = UserService.query(is_superuser=True)
    if not users:
        default_admin = {
            "id": get_uuid(),
            "password": settings.DEFAULT_PASSWORD if hasattr(settings, "DEFAULT_PASSWORD") else "admin",
            "nickname": "admin",
            "is_superuser": True,
            "email": "admin@ragflow.io",
            "creator": "system",
            "status": "1",
            "is_active": ActiveEnum.ACTIVE.value,
        }
        UserMgr.create_user(default_admin["email"], default_admin["password"], "admin")
    elif not any([u.is_active == ActiveEnum.ACTIVE.value for u in users]):
        raise AdminException(
            "No active admin. Please update 'is_active' in db manually.", 500
        )


def _verify_admin_user(email: str, password: str):
    users = UserService.query(email=email)
    if not users:
        raise UserNotFoundError(email)

    psw = decrypt(password)
    user = UserService.query_user(email, psw)
    if not user:
        raise AdminException("Email and password do not match!")
    if not user.is_superuser:
        raise AdminException("Not admin", 403)
    if user.is_active == ActiveEnum.INACTIVE.value:
        raise AdminException(f"User {email} inactive", 403)
    return user


@manager.route("/ping", methods=["GET"])  # noqa: F821
async def ping():
    return success_response("PONG")


@manager.route("/login", methods=["POST"])  # noqa: F821
async def login():
    try:
        data = await get_request_json()
        if not data:
            return error_response("Authorize admin failed.", 400)

        email = data.get("email", "")
        password = data.get("password", "")
        user = _verify_admin_user(email, password)

        response_data = user.to_json()
        user.access_token = get_uuid()
        login_user(user)
        user.update_time = current_timestamp()
        user.update_date = datetime_format(datetime.now())
        user.last_login_time = get_format_time()
        user.save()

        return await construct_response(
            data=response_data,
            auth=user.get_id(),
            message="Welcome back!",
        )
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/logout", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def logout():
    try:
        current_user.access_token = f"INVALID_{secrets.token_hex(16)}"
        current_user.save()
        logout_user()
        return success_response(True)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/auth", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def auth_admin():
    return success_response(None, "Admin is authorized", 0)


@manager.route("/users", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def list_users():
    try:
        return success_response(UserMgr.get_all_users(), "Get all users", 0)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users", methods=["POST"])  # noqa: F821
@login_required
@check_admin_auth
async def create_user():
    try:
        data = await get_request_json()
        if not data or "username" not in data or "password" not in data:
            return error_response("Username and password are required", 400)

        username = data["username"]
        password = data["password"]
        role = data.get("role", "user")
        nickname = data.get("nickname", "")
        language = data.get("language")
        timezone = data.get("timezone")

        if not nickname:
            return error_response("Nickname is required", 400)

        res = UserMgr.create_user(
            username,
            password,
            role,
            nickname=nickname,
            language=language,
            timezone=timezone,
        )
        if res["success"]:
            user_info = res["user_info"]
            user_info.pop("password", None)
            return success_response(user_info, "User created successfully")
        return error_response("create user failed")
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>", methods=["DELETE"])  # noqa: F821
@login_required
@check_admin_auth
async def delete_user(username):
    try:
        res = UserMgr.delete_user(username)
        if res["success"]:
            return success_response(None, res["message"])
        return error_response(res["message"])
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/password", methods=["PUT"])  # noqa: F821
@login_required
@check_admin_auth
async def change_password(username):
    try:
        data = await get_request_json()
        if not data or "new_password" not in data:
            return error_response("New password is required", 400)
        return success_response(None, UserMgr.update_user_password(username, data["new_password"]))
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/activate", methods=["PUT"])  # noqa: F821
@login_required
@check_admin_auth
async def alter_user_activate_status(username):
    try:
        data = await get_request_json()
        if not data or "activate_status" not in data:
            return error_response("Activation status is required", 400)
        return success_response(None, UserMgr.update_user_activate_status(username, data["activate_status"]))
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/admin", methods=["PUT"])  # noqa: F821
@login_required
@check_admin_auth
async def grant_admin(username):
    try:
        if current_user.email == username:
            return error_response(f"can't grant current user: {username}", 409)
        return success_response(None, UserMgr.grant_admin(username))
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/admin", methods=["DELETE"])  # noqa: F821
@login_required
@check_admin_auth
async def revoke_admin(username):
    try:
        if current_user.email == username:
            return error_response(f"can't grant current user: {username}", 409)
        return success_response(None, UserMgr.revoke_admin(username))
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_user_details(username):
    try:
        return success_response(UserMgr.get_user_details(username))
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/datasets", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_user_datasets(username):
    try:
        return success_response(UserServiceMgr.get_user_datasets(username))
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/agents", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_user_agents(username):
    try:
        return success_response(UserServiceMgr.get_user_agents(username))
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/services", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_services():
    try:
        return success_response(ServiceMgr.get_all_services(), "Get all services", 0)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/services/<service_id>", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_service(service_id):
    try:
        return success_response(ServiceMgr.get_service_details(service_id))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/services/<service_id>", methods=["DELETE"])  # noqa: F821
@login_required
@check_admin_auth
async def shutdown_service(service_id):
    try:
        return success_response(ServiceMgr.shutdown_service(service_id))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/services/<service_id>", methods=["PUT"])  # noqa: F821
@login_required
@check_admin_auth
async def restart_service(service_id):
    try:
        return success_response(ServiceMgr.restart_service(service_id))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/roles", methods=["POST"])  # noqa: F821
@login_required
@check_admin_auth
async def create_role():
    try:
        data = await get_request_json()
        if not data or "role_name" not in data:
            return error_response("Role name is required", 400)
        return success_response(RoleMgr.create_role(data["role_name"], data["description"]))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/roles/<role_name>", methods=["PUT"])  # noqa: F821
@login_required
@check_admin_auth
async def update_role(role_name: str):
    try:
        data = await get_request_json()
        if not data or "description" not in data:
            return error_response("Role description is required", 400)
        return success_response(RoleMgr.update_role_description(role_name, data["description"]))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/roles/<role_name>", methods=["DELETE"])  # noqa: F821
@login_required
@check_admin_auth
async def delete_role(role_name: str):
    try:
        return success_response(RoleMgr.delete_role(role_name))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/roles", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def list_roles():
    try:
        return success_response(RoleMgr.list_roles())
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/roles/<role_name>/permission", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_role_permission(role_name: str):
    try:
        return success_response(RoleMgr.get_role_permission(role_name))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/roles/<role_name>/permission", methods=["POST"])  # noqa: F821
@login_required
@check_admin_auth
async def grant_role_permission(role_name: str):
    try:
        data = await get_request_json()
        if not data or "actions" not in data or "resource" not in data:
            return error_response("Permission is required", 400)
        return success_response(
            RoleMgr.grant_role_permission(role_name, data["actions"], data["resource"])
        )
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/roles/<role_name>/permission", methods=["DELETE"])  # noqa: F821
@login_required
@check_admin_auth
async def revoke_role_permission(role_name: str):
    try:
        data = await get_request_json()
        if not data or "actions" not in data or "resource" not in data:
            return error_response("Permission is required", 400)
        return success_response(
            RoleMgr.revoke_role_permission(role_name, data["actions"], data["resource"])
        )
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<user_name>/role", methods=["PUT"])  # noqa: F821
@login_required
@check_admin_auth
async def update_user_role(user_name: str):
    try:
        data = await get_request_json()
        if not data or "role_name" not in data:
            return error_response("Role name is required", 400)
        return success_response(RoleMgr.update_user_role(user_name, data["role_name"]))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<user_name>/permission", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_user_permission(user_name: str):
    try:
        return success_response(RoleMgr.get_user_permission(user_name))
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/variables", methods=["PUT"])  # noqa: F821
@login_required
@check_admin_auth
async def set_variable():
    try:
        data = await get_request_json()
        if not data or "var_name" not in data:
            return error_response("Var name is required", 400)
        if "var_value" not in data:
            return error_response("Var value is required", 400)
        SettingsMgr.update_by_name(data["var_name"], data["var_value"])
        return success_response(None, "Set variable successfully")
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/variables", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_variable():
    try:
        if request.content_length is None or request.content_length == 0:
            return success_response(list(SettingsMgr.get_all()))
        data = await get_request_json()
        if not data or "var_name" not in data:
            return error_response("Var name is required", 400)
        return success_response(SettingsMgr.get_by_name(data["var_name"]))
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/configs", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_config():
    try:
        return success_response(list(ConfigMgr.get_all()))
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/environments", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_environments():
    try:
        return success_response(list(EnvironmentsMgr.get_all()))
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/keys", methods=["POST"])  # noqa: F821
@login_required
@check_admin_auth
async def generate_user_api_key(username: str):
    try:
        user_details = UserMgr.get_user_details(username)
        if not user_details:
            return error_response("User not found!", 404)
        tenants = UserServiceMgr.get_user_tenants(username)
        if not tenants:
            return error_response("Tenant not found!", 404)
        tenant_id = tenants[0]["tenant_id"]
        obj: dict[str, Any] = {
            "tenant_id": tenant_id,
            "token": generate_confirmation_token(),
            "beta": generate_confirmation_token().replace("ragflow-", "")[:32],
            "create_time": current_timestamp(),
            "create_date": datetime_format(datetime.now()),
            "update_time": None,
            "update_date": None,
        }
        if not UserMgr.save_api_key(obj):
            return error_response("Failed to generate API key!", 500)
        return success_response(obj, "API key generated successfully")
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/keys", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_user_api_keys(username: str):
    try:
        return success_response(UserMgr.get_user_api_key(username), "Get user API keys")
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/users/<username>/keys/<key>", methods=["DELETE"])  # noqa: F821
@login_required
@check_admin_auth
async def delete_user_api_key(username: str, key: str):
    try:
        deleted = UserMgr.delete_api_key(username, key)
        if deleted:
            return success_response(None, "API key deleted successfully")
        return error_response("API key not found or could not be deleted", 404)
    except AdminException as e:
        return error_response(e.message, e.code)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/version", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def show_version():
    try:
        return success_response({"version": get_ragflow_version()})
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/sandbox/providers", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def list_sandbox_providers():
    try:
        return success_response(SandboxMgr.list_providers())
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/sandbox/providers/<provider_id>/schema", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_sandbox_provider_schema(provider_id: str):
    try:
        return success_response(SandboxMgr.get_provider_config_schema(provider_id))
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/sandbox/config", methods=["GET"])  # noqa: F821
@login_required
@check_admin_auth
async def get_sandbox_config():
    try:
        return success_response(SandboxMgr.get_config())
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@manager.route("/sandbox/config", methods=["POST"])  # noqa: F821
@login_required
@check_admin_auth
async def set_sandbox_config():
    try:
        data = await get_request_json()
        if not data:
            return error_response("Request body is required", 400)
        provider_type = data.get("provider_type")
        if not provider_type:
            return error_response("provider_type is required", 400)
        config = data.get("config", {})
        set_active = data.get("set_active", True)
        return success_response(
            SandboxMgr.set_config(provider_type, config, set_active),
            "Sandbox configuration updated successfully",
        )
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        logging.exception("set_sandbox_config unexpected error")
        return error_response(str(e), 500)


@manager.route("/sandbox/test", methods=["POST"])  # noqa: F821
@login_required
@check_admin_auth
async def test_sandbox_connection():
    try:
        data = await get_request_json()
        if not data:
            return error_response("Request body is required", 400)
        provider_type = data.get("provider_type")
        if not provider_type:
            return error_response("provider_type is required", 400)
        config = data.get("config", {})
        return success_response(SandboxMgr.test_connection(provider_type, config))
    except AdminException as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)
