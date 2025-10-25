
import json


MANAGER_PROMPT = """
你是一个招聘总监，负责管理招聘流程。你的任务是：
1. 根据用户的需求，确定招聘模式(mode)，包括推荐牛人(recommend)、处理新招呼(greet)、继续沟通(chat)、跟进牛人(followup)。
2. 根据mode，前往招聘网站，获得所有候选人candidate列表。
3. 对于每一位候选人，调用招聘顾问(recruiter agent)，安排招聘顾问处理，并得到处理结果。如果招聘顾问处理失败，则需要重新安排招聘顾问处理。
4. 如果所有候选人处理完成，则结束招聘流程。
"""
STAGES = [
    "GREET", # 打招呼
    "PASS", # < borderline,不匹配，已拒绝
    "CHAT", # >= borderline,沟通中
    "SEEK", # >= threshold_seek,寻求联系方式
    "CONTACT", # 已获得联系方式
]
ACTIONS = {
    # generate message actions
    "CHAT_ACTION": "请根据上述沟通历史，生成下一条跟进消息。重点在于挖掘简历细节，判断候选人是否符合岗位要求，请直接提出问题，让候选人回答经验细节，或者澄清模棱两可的地方", # 打招呼 询问简历细节,
    "ANALYZE_ACTION": "请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。", # 分析候选人
    "ANSWER_QUESTIONS_ACTION": "请回答候选人提出的问题。", # 回答问题
    "FOLLOWUP_ACTION": "请生成下一条跟进消息，用于吸引候选人回复。", # 跟进消息
    "REQUEST_CONTACT_MESSAGE_ACTION": "请生成下一条跟进消息，用于吸引候选人回复。", # 联系方式
    # browser actions
    "SEND_MESSAGE_BROWSER_ACTION": "请发送消息给候选人。", # 发送消息
    "REQUEST_FULL_RESUME_BROWSER_ACTION": "请请求完整简历。", # 请求完整简历
    "REQUEST_WECHAT_PHONE_BROWSER_ACTION": "请请求候选人微信和电话。", # 请求微信和电话
    # notification actions
    "NOTIFY_HR_ACTION": "请通知HR。", # 通知HR
    # chat actions
    "FINISH_ACTION": "已经完成所有动作，等待候选人回复。",
    "PLAN_PROMPTS": "自动化工作流计划动作"
}
ACTION_PROMPTS = {
    "CHAT_ACTION": """请根据上述沟通历史，生成下一条跟进消息。
    重点在于挖掘简历细节，判断候选人是否符合岗位要求，请直接提出问题，让候选人回答经验细节，或者澄清模棱两可的地方。
    请直接生成一条可以发送给候选人的自然语言消息，不要超过100字。不要发模板或者嵌入占位符，不要使用任何格式化、引号、JSON或括号。
    """,
    "ANALYZE_ACTION": """请根据岗位描述，对候选人的简历进行打分，用于决定是否继续推进。
尤其是keyword里面的正负向关键词要进行加分和减分。
另外也要仔细查看候选人的项目经历，检查是否有言过其词的情况。
最后，还要查看候选人的过往工作经历，判断是否符合岗位要求。

请给出 1-10 的四个评分：技能匹配度、创业契合度、基础背景、综合评分，并提供简要分析。

输出严格使用 JSON 格式：
{{
"skill": <int>, // 技能、经验匹配度
"startup_fit": <int>, // 创业公司契合度，抗压能力、对工作的热情程度
"background": <int>, // 基础背景、学历优秀程度、逻辑思维能力
"overall": <int>, // 综合评分
"summary": <str>, // 分析总结
"followup_tips": <str>  // 后续招聘顾问跟进的沟通策略
}}""",
    "CONTACT_ACTION": "请发出一条请求候选人电话或者微信的消息。不要超过50字。且能够直接发送给候选人的文字，不要发模板或者嵌入占位符。请用纯文本回复，不要使用markdown、json格式。",
    "FINISH_ACTION": "已经完成所有动作，等待候选人回复。",
    "PLAN_PROMPTS": f"""请根据上述沟通历史，决定下一步操作。输出格式：
        {{
            "candidate_stage": <str>, // SEEK, GREET, PASS, CONTACT
            "action": <str>, // {", ".join(ACTIONS.keys())}
            "reason": <str>, // 为什么选择这个action, 不要超过100字
        }}
        每个action的说明：{json.dumps(ACTIONS, ensure_ascii=False)}"""
}