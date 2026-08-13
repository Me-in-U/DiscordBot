import random
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from cogs.lol_scrim import LolScrimCommands
from cogs.lol_scrim.recruitment import LolScrimRecruitmentView

from util.lol.scrim import (
    MAX_SCRIM_PLAYERS,
    LolScrimRoster,
    TeamSlot,
    build_lol_scrim_match,
    format_lol_scrim_roster,
    format_lol_scrim_team_slots,
)


LOL_SCRIM_PATH = Path("util/lol/scrim.py")
LEGACY_LOL_SCRIM_PATH = Path("util/lol_scrim.py")
LOL_SCRIM_COG_PATH = Path("cogs/lol_scrim/__init__.py")
LOL_SCRIM_RECRUITMENT_PATH = Path("cogs/lol_scrim/recruitment.py")
LEGACY_LOL_SCRIM_COG_PATH = Path("cogs/lol_scrim.py")


class LolScrimMatchTests(unittest.TestCase):
    def test_lol_scrim_lives_under_lol_package(self):
        self.assertTrue(LOL_SCRIM_PATH.exists())
        self.assertFalse(LEGACY_LOL_SCRIM_PATH.exists())

    def test_lol_scrim_cog_uses_package_layout(self):
        self.assertTrue(LOL_SCRIM_COG_PATH.exists())
        self.assertTrue(LOL_SCRIM_RECRUITMENT_PATH.exists())
        self.assertFalse(LEGACY_LOL_SCRIM_COG_PATH.exists())

    def test_build_lol_scrim_match_assigns_exactly_ten_players(self):
        match = build_lol_scrim_match(
            [f"유저{i}" for i in range(1, 11)],
            rng=random.Random(7),
        )

        all_players = match.all_players()
        self.assertEqual(len(all_players), MAX_SCRIM_PLAYERS)
        self.assertEqual(set(all_players), {f"유저{i}" for i in range(1, 11)})
        self.assertEqual([slot.position for slot in match.red], ["탑", "정글", "미드", "원딜", "서폿"])
        self.assertEqual([slot.position for slot in match.blue], ["탑", "정글", "미드", "원딜", "서폿"])

    def test_build_lol_scrim_match_requires_exactly_ten_players(self):
        for player_count in (9, 11):
            with self.subTest(player_count=player_count), self.assertRaises(ValueError):
                build_lol_scrim_match(
                    [f"유저{i}" for i in range(player_count)],
                    rng=random.Random(1),
                )

    def test_roster_rejects_duplicates_and_removes_disconnected_users(self):
        roster = LolScrimRoster()

        self.assertTrue(roster.add(1, "<@1>"))
        self.assertFalse(roster.add(1, "<@1>"))
        self.assertTrue(roster.add(2, "<@2>"))
        self.assertEqual(roster.retain({2}), [1])
        self.assertEqual(roster.labels(), ["<@2>"])

    def test_format_lol_scrim_roster_keeps_ten_numbered_slots(self):
        lines = format_lol_scrim_roster(["<@1>", "<@2>"]).splitlines()

        self.assertEqual(len(lines), MAX_SCRIM_PLAYERS)
        self.assertEqual(lines[0], "`01` <@1>")
        self.assertEqual(lines[1], "`02` <@2>")
        self.assertEqual(lines[-1], "`10` 빈자리")

    def test_format_lol_scrim_team_slots_for_embed_field(self):
        self.assertEqual(
            format_lol_scrim_team_slots(
                [
                    TeamSlot("탑", "A"),
                    TeamSlot("정글", "B"),
                    TeamSlot("미드", "C"),
                    TeamSlot("원딜", "D"),
                    TeamSlot("서폿", "E"),
                ]
            ),
            "`탑` **A**\n`정글` **B**\n`미드` **C**\n`원딜` **D**\n`서폿` **E**",
        )


class LolScrimRecruitmentViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.voice_channel = Mock(spec=discord.VoiceChannel)
        self.voice_channel.id = 77
        self.voice_channel.name = "내전 음성방"
        self.voice_channel.members = []
        self.release_callback = Mock()
        self.view = LolScrimRecruitmentView(
            guild_id=10,
            voice_channel=self.voice_channel,
            owner_id=1,
            owner_display_name="모집자",
            release_callback=self.release_callback,
        )

    def tearDown(self) -> None:
        self.view.stop()

    def _member(
        self,
        user_id: int,
        *,
        voice_channel: object | None = None,
    ) -> Mock:
        member = Mock(spec=discord.Member)
        member.id = user_id
        member.bot = False
        member.mention = f"<@{user_id}>"
        member.voice = SimpleNamespace(
            channel=voice_channel if voice_channel is not None else self.voice_channel
        )
        member.guild_permissions = SimpleNamespace(manage_guild=False)
        return member

    @staticmethod
    def _interaction(member: Mock) -> SimpleNamespace:
        return SimpleNamespace(
            guild_id=10,
            user=member,
            response=SimpleNamespace(
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )

    async def test_view_exposes_join_leave_and_cancel_buttons(self):
        self.assertEqual(
            [child.label for child in self.view.children],
            ["참가", "참가 취소", "모집 취소"],
        )
        embed = self.view.build_recruitment_embed()
        self.assertEqual(embed.title, "롤 내전 참가자 모집")
        self.assertEqual(embed.fields[0].name, "참가 현황 0/10")
        self.assertEqual(len(embed.fields[0].value.splitlines()), 10)

    async def test_only_members_in_the_target_voice_channel_can_join(self):
        other_channel = SimpleNamespace(id=88)
        member = self._member(1, voice_channel=other_channel)
        interaction = self._interaction(member)

        await self.view.join_button.callback(interaction)

        self.assertEqual(self.view.roster.count, 0)
        interaction.response.send_message.assert_awaited_once_with(
            "먼저 `내전 음성방` 음성방에 참가해주세요.",
            ephemeral=True,
        )

    async def test_duplicate_join_is_rejected_privately(self):
        member = self._member(1)
        self.voice_channel.members = [member]
        first_interaction = self._interaction(member)
        second_interaction = self._interaction(member)

        await self.view.join_button.callback(first_interaction)
        await self.view.join_button.callback(second_interaction)

        self.assertEqual(self.view.roster.count, 1)
        second_interaction.response.send_message.assert_awaited_once_with(
            "이미 내전 참가자로 등록되어 있습니다.",
            ephemeral=True,
        )

    async def test_tenth_join_automatically_assigns_teams_and_finishes(self):
        members = [self._member(user_id) for user_id in range(1, 11)]
        self.voice_channel.members = members
        last_interaction = None

        for member in members:
            last_interaction = self._interaction(member)
            await self.view.join_button.callback(last_interaction)

        self.assertIsNotNone(last_interaction)
        self.assertTrue(self.view.finished)
        self.assertEqual(self.view.roster.count, MAX_SCRIM_PLAYERS)
        self.release_callback.assert_called_once_with(self.view)
        kwargs = last_interaction.response.edit_message.await_args.kwargs
        self.assertEqual(kwargs["embed"].title, "롤 내전 팀 배정 완료")
        self.assertTrue(all(child.disabled for child in self.view.children))

    async def test_voice_channel_departure_removes_a_registered_member(self):
        member = self._member(1)
        self.voice_channel.members = [member]
        interaction = self._interaction(member)
        await self.view.join_button.callback(interaction)
        message = SimpleNamespace(edit=AsyncMock())
        self.view.bind_message(message)

        await self.view.remove_disconnected_participant(member.id)

        self.assertEqual(self.view.roster.count, 0)
        kwargs = message.edit.await_args.kwargs
        self.assertEqual(kwargs["embed"].fields[0].name, "참가 현황 0/10")

    async def test_timeout_disables_buttons_and_shows_closed_embed(self):
        message = SimpleNamespace(edit=AsyncMock())
        self.view.bind_message(message)

        await self.view.on_timeout()

        self.assertTrue(self.view.finished)
        self.release_callback.assert_called_once_with(self.view)
        kwargs = message.edit.await_args.kwargs
        self.assertEqual(kwargs["embed"].title, "롤 내전 모집 종료")
        self.assertTrue(all(child.disabled for child in self.view.children))

    async def test_owner_can_cancel_recruitment(self):
        owner = self._member(1)
        interaction = self._interaction(owner)

        await self.view.cancel_button.callback(interaction)

        self.assertTrue(self.view.finished)
        self.release_callback.assert_called_once_with(self.view)
        kwargs = interaction.response.edit_message.await_args.kwargs
        self.assertEqual(kwargs["embed"].title, "롤 내전 모집 취소")


class LolScrimCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cog = LolScrimCommands(SimpleNamespace())
        self.voice_channel = Mock(spec=discord.VoiceChannel)
        self.voice_channel.id = 77
        self.voice_channel.name = "내전 음성방"
        self.voice_channel.members = []
        self.member = Mock(spec=discord.Member)
        self.member.id = 1
        self.member.display_name = "모집자"
        self.member.bot = False
        self.member.voice = SimpleNamespace(channel=self.voice_channel)

    def tearDown(self) -> None:
        self.cog.cog_unload()

    def _interaction(self, message: object) -> SimpleNamespace:
        return SimpleNamespace(
            guild_id=10,
            user=self.member,
            response=SimpleNamespace(send_message=AsyncMock()),
            original_response=AsyncMock(return_value=message),
        )

    async def test_command_has_no_manual_add_or_exclude_parameters(self):
        self.assertEqual(self.cog.create_lol_scrim.parameters, [])

    async def test_command_starts_only_one_recruitment_per_voice_channel(self):
        message = SimpleNamespace(jump_url="https://discord.test/recruitment")
        first_interaction = self._interaction(message)
        second_interaction = self._interaction(message)

        await self.cog.create_lol_scrim.callback(self.cog, first_interaction)
        await self.cog.create_lol_scrim.callback(self.cog, second_interaction)

        self.assertIn(self.voice_channel.id, self.cog._active_recruitments)
        first_kwargs = first_interaction.response.send_message.await_args.kwargs
        self.assertEqual(first_kwargs["embed"].title, "롤 내전 참가자 모집")
        self.assertIsInstance(first_kwargs["view"], LolScrimRecruitmentView)
        second_interaction.response.send_message.assert_awaited_once_with(
            "이 음성방에서는 이미 내전 참가자를 모집하고 있습니다. "
            "기존 모집: https://discord.test/recruitment",
            ephemeral=True,
        )


if __name__ == "__main__":
    unittest.main()
