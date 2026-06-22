import unittest

from api.riot import RiotRankLookupError, get_rank_data


class _FakeResponse:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, *, headers):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError("unexpected Riot API request")
        status, payload = self.responses.pop(0)
        return _FakeResponse(status, payload)


class RiotApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_rank_data_selects_solo_queue_from_api_entries(self):
        session = _FakeSession(
            [
                (200, {"puuid": "puuid-123"}),
                (
                    200,
                    [
                        {
                            "queueType": "RANKED_FLEX_SR",
                            "tier": "GOLD",
                            "rank": "II",
                            "leaguePoints": 12,
                            "wins": 4,
                            "losses": 6,
                        },
                        {
                            "queueType": "RANKED_SOLO_5x5",
                            "tier": "PLATINUM",
                            "rank": "I",
                            "leaguePoints": 75,
                            "wins": 30,
                            "losses": 20,
                        },
                    ],
                ),
            ]
        )

        data = await get_rank_data("RiotUser", "KR1", "solo", session=session)

        self.assertEqual(data["game_name"], "RiotUser")
        self.assertEqual(data["tag_line"], "KR1")
        self.assertEqual(data["tier"], "PLATINUM")
        self.assertEqual(data["rank"], "I")
        self.assertEqual(data["league_points"], 75)
        self.assertEqual(data["rank_type_kor"], "솔랭")
        self.assertEqual(data["win_rate"], 60.0)

    async def test_get_rank_data_selects_flex_queue_from_api_entries(self):
        session = _FakeSession(
            [
                (200, {"puuid": "puuid-123"}),
                (
                    200,
                    [
                        {
                            "queueType": "RANKED_SOLO_5x5",
                            "tier": "DIAMOND",
                            "rank": "IV",
                            "leaguePoints": 1,
                            "wins": 10,
                            "losses": 10,
                        },
                        {
                            "queueType": "RANKED_FLEX_SR",
                            "tier": "EMERALD",
                            "rank": "III",
                            "leaguePoints": 44,
                            "wins": 8,
                            "losses": 2,
                        },
                    ],
                ),
            ]
        )

        data = await get_rank_data("RiotUser", "KR1", "flex", session=session)

        self.assertEqual(data["tier"], "EMERALD")
        self.assertEqual(data["rank_type_kor"], "자랭")
        self.assertEqual(data["win_rate"], 80.0)

    async def test_get_rank_data_raises_lookup_error_for_http_error(self):
        session = _FakeSession([(404, {"status": {"message": "not found"}})])

        with self.assertRaisesRegex(RiotRankLookupError, "Riot ID"):
            await get_rank_data("Missing", "KR1", "solo", session=session)

    async def test_get_rank_data_raises_lookup_error_when_rank_queue_is_absent(self):
        session = _FakeSession(
            [
                (200, {"puuid": "puuid-123"}),
                (200, [{"queueType": "RANKED_FLEX_SR"}]),
            ]
        )

        with self.assertRaisesRegex(RiotRankLookupError, "솔랭"):
            await get_rank_data("RiotUser", "KR1", "solo", session=session)


if __name__ == "__main__":
    unittest.main()
