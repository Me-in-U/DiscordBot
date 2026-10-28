import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from func.youtube_post import parse_youtube_post_html
from util.youtube.community import parse_youtube_community_posts_html
from util.maplestory.fetcher import _fetch_html
from util.lostark.notices import parse_lostark_notice_list


class UpstreamParsingTests(unittest.IsolatedAsyncioTestCase):
    def test_youtube_assignment_variants_work_for_post_and_community(self):
        payload = {'contents': {'backstagePostRenderer': {
            'postId': 'UgkxExample', 'contentText': {'simpleText': '본문 {문자열} \\" 내용'},
        }}}
        for assignment in ('var ytInitialData=', 'ytInitialData = ', 'window["ytInitialData"] =', "window['ytInitialData']=\n"):
            with self.subTest(assignment=assignment):
                html = '<script>' + assignment + json.dumps(payload) + ';</script>'
                community = parse_youtube_community_posts_html(html)
                post = parse_youtube_post_html(html, 'https://youtube.com/post/UgkxExample')
                self.assertEqual(community[0].post_id, post.post_id)
                self.assertEqual(community[0].text, post.text)

    def test_invalid_or_missing_initial_data_is_not_treated_as_no_posts(self):
        for html in ('<html>점검 중</html>', '<script>ytInitialData=[];</script>', '<script>ytInitialData={</script>'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                parse_youtube_community_posts_html(html)

    async def test_maple_maintenance_redirect_403_retries_same_host_over_https(self):
        error = aiohttp.ClientResponseError(
            SimpleNamespace(real_url='http://gamebulletin.nexon.com/maplestory/game3.html?ReturnUrl=/News/Notice'),
            (), status=403,
        )
        with patch('util.maplestory.fetcher.fetch_text_with_retry', new_callable=AsyncMock,
                   side_effect=[error, '<html>점검 안내</html>']) as fetch:
            with patch('util.maplestory.fetcher.aiohttp.ClientSession') as client:
                client.return_value.__aenter__.return_value = MagicMock()
                await _fetch_html('https://maplestory.nexon.com/News/Notice')
        self.assertEqual(fetch.await_args_list[1].args[1],
                         'https://gamebulletin.nexon.com/maplestory/game3.html?ReturnUrl=/News/Notice')

    def test_lostark_missing_list_retains_page_title_in_diagnostic(self):
        with self.assertRaisesRegex(ValueError, '서비스 점검'):
            parse_lostark_notice_list('<html><title>서비스 점검</title></html>')
