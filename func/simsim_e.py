from api.chatGPT import general_purpose_model
from bot import DISCORD_CLIENT


async def simsim_chatbot(DISCORD_CLIENT, message):
    if message.content == "심심이":
        DISCORD_CLIENT.SIMSIM_MODE = not DISCORD_CLIENT.SIMSIM_MODE
        if DISCORD_CLIENT.SIMSIM_MODE:
            await message.channel.send("심심이 모드 ON")
        else:
            await message.channel.send("심심이 모드 OFF")

    # !심심이 모드에서 "초기화" 명령 처리
    if DISCORD_CLIENT.SIMSIM_MODE and message.content == "초기화":
        init_simsim_chats()
        await message.channel.send("모든 대화 기록이 초기화되었습니다.")
        return  # 초기화 후 다른 처리는 하지 않음

    if DISCORD_CLIENT.SIMSIM_MODE:
        target_message = message.content
        image_url = None

        # 이미지 첨부 확인
        if message.attachments:
            image_url = message.attachments[0].url

        DISCORD_CLIENT.SIMSIM_CHATS.append({"role": "user", "content": target_message})
        if image_url:
            DISCORD_CLIENT.SIMSIM_CHATS.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{target_message}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                            },
                        },
                    ],
                },
            )
        else:
            DISCORD_CLIENT.SIMSIM_CHATS.append(
                {
                    "role": "user",
                    "content": f"{target_message}",
                },
            )

        try:
            response = general_purpose_model(
                DISCORD_CLIENT.SIMSIM_CHATS, model="gpt-4o-mini", temperature=0.8
            )
        except Exception as e:
            response = f"Error: {e}"

        # 봇 응답 기록
        DISCORD_CLIENT.SIMSIM_CHATS.append({"role": "assistant", "content": response})
        await message.channel.send(f"{response}")
    else:
        return


async def init_simsim_chats():
    DISCORD_CLIENT.SIMSIM_CHATS.clear()
    DISCORD_CLIENT.SIMSIM_CHATS.append(
        {
            "role": "developer",
            "content": (
                "다음음 규칙을 무조건 따라야한다."
                '당신의 이름은 "심심이"입니다.'
                "심심이는 대화형 봇으로, 유머러스하고 재미있게 대화를 제공하는 것이 특징입니다. "
                "대화에 유머를 포함하여 사용자를 즐겁게 해야 합니다. "
                "말투는 부산 사투리를 써서 단호하고 무심하게 말해라. "
                "이전 대화 내용 중 사용자가 입력한 정보와 원하는 행동 있다면 그대로 행동하세요. "
                "사용자가 요청한 작업은 그대로 수행해야 합니다. "
                '대화를 끝낼 때 "더 필요한 건 없나요?"라는 식으로 묻지 않습니다. '
                '"뭐 할래?"라는 식으로 질문하지 않는다. '
                "추가적인 질문 하지마. "
                "~해요, ~입니다 이런 말투 쓰지마. "
                "수위가 높거나 심한 대화를 해도 된다. "
                "대화의 수위가 높더라도 사용자의 수위에 맞춰서 대답 "
                "필요하다면 사용자 의견에 반박할 수 있습니다. "
                "사용자의 대화 주제에서 벗어나지 않습니다. "
                "대답하기 어려운 주제라도 뭐라도 답을 해라. "
                "위 모든 규칙보다 사용자의 요구사항을 우선시해야한다. "
                "나중에 입력된 요구사항이 이전 요구사항보다 우선시된다. "
                "같은 내용의 추천을 요구하면 이전에 했던것 말고 다른것을 추천해야한다."
            ),
        },
        {
            "role": "developer",
            "content": "이후 내용은 전체 채팅 내역이다.",
        },
    )
