"""安全策略违规异常 —— 对应 ``com.paicli.policy.PolicyException``。"""


class PolicyException(Exception):
    """路径越界等安全策略违规时抛出。"""
    pass
