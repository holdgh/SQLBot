# -*- coding: utf-8 -*-
"""冒烟：find_custom_prompts 的 BM25 打分仅依据 name（问题排查.md 问题3）。"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'backend'))

from common.core.config import settings  # noqa: E402
from apps.custom_prompt.curd import custom_prompt as m  # noqa: E402
from apps.custom_prompt.models.custom_prompt_model import CustomPromptTypeEnum  # noqa: E402


class Row:
    def __init__(self, name, prompt):
        self.id = 1
        self.name = name
        self.prompt = prompt


ROWS = [
    Row('订单统计', '这是一段与问题无关的英文占位 text abc'),
    Row('无关条目', '订单 订单 订单 订单'),
]


class FakeResult:
    def fetchall(self):
        return ROWS


class FakeSession:
    def execute(self, stmt, params=None):
        return FakeResult()


settings.KEYWORD_RETRIEVAL_ENABLED = True
settings.KEYWORD_RETRIEVAL_TOP_COUNT = 10
settings.KEYWORD_RETRIEVAL_MIN_SCORE = 0.0
settings.KEYWORD_RETRIEVAL_MAX_CANDIDATES = 100

xml, prompts = m.find_custom_prompts(
    FakeSession(), CustomPromptTypeEnum.GENERATE_SQL, oid=1,
    datasource=None, question='订单')

print('prompts =', prompts)
assert len(prompts) == 1 and '英文占位' in prompts[0], \
    'BM25 应仅按 name 打分：name 命中者胜出，prompt 命中者（prompt=订单x4）应为 0 分被过滤'
assert xml
print('SMOKE OK: 打分仅依据 name')
