from fastapi import APIRouter

from apps.chat.api import chat
# ========= 【改造标记 CUSTOM-PROMPT】↓ 开源自定义提示词路由，替换 sqlbot_xpack 同名闭源路由 =========
from apps.custom_prompt.api import custom_prompt
# ========= 【改造标记 CUSTOM-PROMPT】↑ 路由导入结束 =========
from apps.dashboard.api import dashboard_api
from apps.data_training.api import data_training
from apps.datasource.api import datasource, table_relation, recommended_problem
from apps.mcp import mcp
from apps.system.api import login, user, aimodel, workspace, assistant, parameter, apikey, variable_api
from apps.terminology.api import terminology
from apps.settings.api import base
#from audit.api import audit_api


api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(user.router)
api_router.include_router(workspace.router)
api_router.include_router(assistant.router)
api_router.include_router(aimodel.router)
api_router.include_router(base.router)
api_router.include_router(terminology.router)
# ========= 【改造标记 CUSTOM-PROMPT】↓ 注册顺序在 main.py: sqlbot_xpack.init_fastapi_app 之前，同路径时开源路由优先生效 =========
api_router.include_router(custom_prompt.router)
# ========= 【改造标记 CUSTOM-PROMPT】↑ 路由注册结束 =========
api_router.include_router(data_training.router)
api_router.include_router(datasource.router)
api_router.include_router(chat.router)
api_router.include_router(dashboard_api.router)
api_router.include_router(mcp.router)
api_router.include_router(table_relation.router)
api_router.include_router(parameter.router)
api_router.include_router(apikey.router)

api_router.include_router(recommended_problem.router)

api_router.include_router(variable_api.router)

#api_router.include_router(audit_api.router)
