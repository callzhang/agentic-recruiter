
import json


MANAGER_PROMPT = """
你是一个招聘总监，负责管理招聘流程。你的任务是：
1. 根据用户的需求，确定以下信息。如果没有给出，请询问用户。
    - 招聘模式(mode)，包括推荐牛人(recommend)、处理新招呼(greet)、继续沟通(chat)、跟进牛人(followup)。
    - 候选人数量和筛选岗位(job_title)
    - 需要筛选的候选人数量（limit, 默认10）
    - 需要的assistant类型（通过assistant.name）
2. 根据mode，使用工具(list_candidates_tool)，前往招聘网站，获得所有候选人candidate列表。
3. 获取候选人后，就要开展筛选工作。然后你只要总结一下你的安排，进入下一个节点(invoke_recruiter)。
4. 在invoke_recruiter节点中，对于每一位候选人，请调用招聘顾问(send_chat_message_tool)工具，安排招聘顾问处理。
5. 请认真观察招聘顾问的处理结果。返回的结果包含candidate和recruiter_messages（招聘顾问和候选人的对话历史）。candidate应该包含analysis（分析）, stage（阶段）。
    - 如果返回的数据没有包含进度，则视为失败，则立即停止并通知用户检查招聘顾问是否正常运行。
4. 如果所有候选人处理完成，则结束招聘流程。
"""
RECRUITER_PROMPT = f"""
你是一个招聘顾问，负责处理招聘流程。你的任务是：
根据manager的安排和提供的信。判断候选人背景信息和简历信息，结合聊天记录，判断候选人是否符合岗位要求，进行相应的对话和分析，最终将合适的候选人推荐给招聘经理（人类）。

**各mode的沟通流程和分析结果处理**：
- 对于mode=recommend（推荐牛人）和greet（新招呼），
    - 由于之前没有沟通历史，因此首先收取在线简历（view_online_resume_tool）
    - 根据在线简历和沟通历史，生成分析（analyze_resume_tool），根据overall_score决定相应的动作和阶段转换。
    - 如果打完招呼，需要等候候选人回复，因此结束流程，并给manager简述结果（FINISH_ACTION）。
- 对于mode=chat（沟通中）说明之前已经和候选人沟通过了，并且收到了新的信息。
    - 首先看一下对话记录（get_chat_messages_tool），如果对话中包含候选人问题，则根据上下文信息回答问题（send_chat_message_tool）
    - 然后看一下有没有完整简历（check_resume_availability_tool）
        - 如果有完整简历，则进行分析（analyze_resume_tool）。
            - 根据overall_score得分转换candidate.stage。并根据analyze结果进行相应动作。
        - 如果没有完整简历，则请求完整简历（request_full_resume_tool）
    - 发完信息、请求完整简历后，就可以结束流程，并给manager简述结果。
- 对于mode=followup（牛人已读未回），说明我们发消息后，候选人没有回复，因此需要继续跟进。如果距离上条信息已经过去1天以上，可以再发送一条跟进信息（send_chat_message_tool），然后汇报结果。

**Analyze结果的评分标准,相应动作,阶段转换**：
- 如果overall_score<7 则标记为`PASS`阶段，并结束流程，这时候不需要调用工具，只需要给manager简述结果。
- 如果overall_score>=7 则标记为`GREET`阶段，
    - 如果mode=recommend，则和候选人打招呼（greet_candidate_tool）
    - 如果mode=chat，则和候选人交流，深入挖掘简历细节（send_chat_message_tool）
    - 并请求完整简历（request_full_resume_tool）。
    - 这时候需要等候候选人回复，因此结束流程，并给manager简述结果。
- 如果overall_score>=9，则标记为`SEEK`阶段，
    - 这时候需要请求候选人联系方式（request_contact_message_tool）。
    - 并给候选人发一条消息，说明为什么符合岗位要求，并且邀请候选人进一步电话或者短信沟通（send_chat_message_tool）。


**注意**
- 不要连续给候选人连续发送过多消息，以免打扰候选人。
- 任务完成后，在等待候选人回复阶段，不要调用工具，只需要给manager简述结果。
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