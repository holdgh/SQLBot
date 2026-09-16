#!/usr/bin/env python3
# -*- coding:utf-8 -*-

# @Time    : 2026/9/15 15:45
# @Author  : gaohuan
# @Email   : 
# @FileName: main_mcp.py
# @Desc    :
# main_1.py
import uvicorn
# 从main导入已经定义好的mcp_app实例
from main import mcp_app

if __name__ == "__main__":
    uvicorn.run(
        "main:mcp_app",
        host="0.0.0.0",
        port=8001,
        # reload=True,  # 开发打开热重载
        proxy_headers=True,
        forwarded_allow_ips="*"
    )
