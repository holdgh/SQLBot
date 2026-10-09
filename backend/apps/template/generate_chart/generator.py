from apps.template.template import get_base_template


def get_chart_template():
    template = get_base_template()
    return template['template']['chart']

def get_base_terminology_template():
    template = get_base_template()
    return template['template']['terminology']

def get_base_data_training_template():
    template = get_base_template()
    return template['template']['data_training']

# ========= 【改造标记 METRIC-CENTER】↓ 指标块包装模板 =========
def get_base_metric_template():
    template = get_base_template()
    return template['template']['metric']
# ========= 【改造标记 METRIC-CENTER】↑ 结束 =========
