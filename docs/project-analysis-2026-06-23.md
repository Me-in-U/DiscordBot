# DiscordBot 프로젝트 전체 분석

작성일: 2026-06-23
기준 커밋: `34aab00` (`Harden DiscordBot exception handling`, 2026-06-22 12:00:00 +0900)
분석 범위: `bot.py`, `api/`, `cogs/`, `common/`, `func/`, `util/`, `test/`, Docker/Jenkins/문서

## Executive Summary

1. 기준 커밋의 검증 기준선은 Python 3.11.9, `compileall` 통과, unittest 154개 통과다.
2. Top 1 리스크는 Jenkins 배포 전에 테스트/컴파일 게이트가 없는 점이다.
3. Top 2 리스크는 `on_ready` 재진입 시 초기화/DB 업데이트/command sync가 반복될 수 있는 구조다.
4. Top 3 리스크는 YouTube 요약이 고정 임시 파일명을 사용해 동시 실행 시 파일 충돌이 가능한 점이다.
5. Top 4 리스크는 OpenAI response 객체와 사용자 메시지 원문이 운영 로그에 남을 수 있는 점이다.
6. Top 5 리스크는 `music.py`, `youtube_summary.py`, `loop.py` 같은 대형 파일이 변경 위험을 키우는 점이다.
7. 권장 처리 순서는 Jenkins 테스트 게이트, `on_ready` guard, YouTube temp workspace, 민감 로그 제거, 문서 최신화다.
8. 현재 작업트리에서는 위 1-4번 리스크의 1차 보강과 대형 파일 일부 분리가 구현되었다.
9. 현재 최신 검증은 `compileall` 통과, unittest 470개 통과다.
10. 이번 패치로 YouTube channel resolver helper가 `util/youtube/` 카테고리 패키지로 이동되었고, root YouTube util 정리가 이어졌다.

## 기준선

- 브랜치 상태: `main...origin/main`
- Python: `3.11.9`
- Python 파일 수: 96개
- 검증 결과:
  - `python -m compileall -q bot.py api cogs common func util test` 통과
  - `python -m unittest discover -s test` 통과, 154개
- `.env`, `.env.deploy`는 `.gitignore`로 제외되어 있고 tracked 파일은 아님

## 현재 작업트리 구현 진행 현황

이 문서의 진단은 기준 커밋 `34aab00` 상태를 대상으로 한다. 이후 현재 작업트리에서는 아래 항목이 구현되었다.

최신 검증 결과: `python -m compileall -q bot.py api cogs common func util test scripts` 통과, `python -m unittest discover -s test` 470개 통과.

| 상태 | 항목 | 구현 근거 |
| --- | --- | --- |
| 완료 | Jenkins 테스트 게이트 | `Jenkinsfile` `Verify` stage에서 whitespace check, 컨테이너 내부 Python 버전 출력, `compileall`, unittest 실행 |
| 완료 | Jenkins DB migration gate | `Migrate Database` stage에서 `python -m scripts.migrate_db`를 Deploy 전에 실행 |
| 완료 | Python minor version 통일 | `Dockerfile.deps`를 `python:3.11-slim`으로 변경하고 README/AGENTS에 Python 3.11 기준 명시 |
| 완료 | `on_ready` 재진입 guard | `bot.py`에 `_startup_completed` guard와 `build_party_list()` 재계산 경로 추가 |
| 완료 | YouTube temp workspace | `func/youtube_workspace.py` 추가, 영상 요약 자막/MP3 경로를 요청별 workspace 아래로 제한 |
| 완료 | YouTube link parser 분리 | `func/youtube_links.py` 추가, URL 정규화/링크 종류/ID 추출 책임 분리 |
| 완료 | YouTube Data API adapter 분리 | `func/youtube_api.py` 추가, 영상 제목/라이브 상태/댓글 조회를 `YouTubeApiError`로 매핑 |
| 완료 | YouTube post parser 분리 | `func/youtube_post.py`로 커뮤니티 게시물 HTML 파싱과 GPT 입력 포맷팅 이동, 기존 `func.youtube_summary` 공개 import 호환 유지 |
| 완료 | YouTube transcript helper 분리 | `func/youtube_transcript.py`로 자막 파일 읽기와 VTT noise 제거/줄바꿈 정규화 이동 |
| 완료 | YouTube media helper 분리 | `func/youtube_media.py`로 자막 다운로드, MP3 변환, STT, ffmpeg fallback 이동 |
| 완료 | YouTube GPT summarizer 분리 | `func/youtube_summarizer.py`로 영상/댓글/게시물 GPT 요약 helper 이동 |
| 완료 | YouTube summary UI 분리 | `func/youtube_summary_ui.py`로 prompt/title/Discord View/check_youtube_link 이동, 기존 `func.youtube_summary` 공개 import 호환 유지 |
| 완료 | YouTube process orchestration 분리 | `func/youtube_processor.py`로 post/video 요약 실행, 요청별 workspace cleanup, domain error mapping 이동, 기존 `func.youtube_summary` 공개 import 호환 유지 |
| 완료 | WebSub helper 분리 | `util/youtube_websub.py`에 callback URL/payload helper 추가, `cogs/loop.py` WebSub 요청 조립 책임 축소 |
| 완료 | WebSub subscription helper 1차 분리 | `util/youtube_websub_subscription.py`로 callback URL 구성, subscribe/unsubscribe 요청, live/upload 구독 대상 필터링, WebSub 상태 저장 이동 |
| 완료 | WebSub notification handler 1차 분리 | `util/youtube_websub_notification.py`로 Atom notification 파싱, 구독 조회, 후보 처리 결과 집계 이동 |
| 완료 | Loop task lifecycle 1차 분리 | `util/loop_task_lifecycle.py`로 task start/cancel 정책 이동, `LoopTasks.cog_unload()`에서 실행 중인 loop cancel |
| 완료 | YouTube loop runner 1차 분리 | `util/youtube_loop_runner.py`로 YouTube 후보 확인과 커뮤니티 task orchestration 이동, `LoopTasks`는 최상위 try/logging 유지 |
| 완료 | Daily refresh runner 1차 분리 | `util/daily_refresh_runner.py`로 기념일/DDAY/썬데이메이플/user message reset orchestration 이동, `new_day_clear`는 runner 호출만 유지 |
| 완료 | WebSub renewal runner 1차 분리 | `util/youtube_websub_renewal.py`로 주기적 WebSub 갱신 호출/성공 로그 orchestration 이동 |
| 완료 | YouTube video candidate runner 1차 분리 | `util/youtube_video_candidate_runner.py`로 live/upcoming/upload/shorts candidate 상태 처리 이동 |
| 완료 | YouTube video status helper 1차 분리 | `util/youtube/video_status.py`로 Google `videos.list` 요청과 응답 classification 이동 |
| 완료 | YouTube channel resolver helper 패키지 이동 | `util/youtube_channel_resolver.py`를 `util/youtube/channel_resolver.py`로 이동하고, `cogs.youtube_subscriptions`/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |
| 완료 | YouTube notification sender 1차 분리 | `util/youtube_notification_sender.py`로 live/upload 알림 대상 채널 resolve와 메시지 전송 이동 |
| 완료 | YouTube notification state persistence 2차 분리 | `util/youtube/notification_state.py`로 live/upload/pending 상태 저장과 pending check timestamp 갱신 이동 |
| 완료 | YouTube community notification 1차 분리 | `util/youtube_community_notification.py`로 커뮤니티 embed/send, 최초 seed, post ID 상태 저장 이동 |
| 완료 | YouTube community polling helper 1차 분리 | `util/youtube_community_polling.py`로 커뮤니티 post fetch, fetch 실패 warning, notification processing 위임 이동 |
| 완료 | YouTube Atom feed fallback 1차 분리 | `util/youtube_feed_fallback.py`로 feed polling throttle, feed fetch, seen update tracking, candidate dispatch 이동 |
| 완료 | Weekly 1557 report runner 1차 분리 | `util/weekly_1557_reporter.py`로 주간 1557 리포트 생성/전송/초기화 orchestration 이동 |
| 완료 | Presence status helper 1차 분리 | `util/presence_status.py`로 USER_MESSAGES 집계와 presence 문구 생성 이동 |
| 완료 | MapleStory notice loop runner 1차 분리 | `util/maplestory_notice_loop_runner.py`로 공지 결과 집계/로그 orchestration 이동, 3분 polling loop는 `cogs/loop.py`에 유지 |
| 완료 | 민감 로그 제거 | OpenAI response 객체 전체 출력 제거, 메시지 원문/sample 출력 제거 |
| 완료 | Cog 로드 실패 격리 | 선택 Cog 실패는 로깅 후 계속 진행, 필수 Cog 실패는 `RequiredCogLoadError`로 startup 실패 |
| 완료 | WebSub token 운영 필수화 | `.env.deploy` 또는 production 런타임에서 `YOUTUBE_WEBSUB_VERIFY_TOKEN` 누락 시 startup 실패 |
| 완료 | DB migration 분리 | `util/db.py`에 `DB_SCHEMA_VERSION`, `run_schema_migrations()`, `ensure_schema_ready()` 추가; startup은 schema 검증만 수행 |
| 완료 | 외부 API domain exception 확대 | `api/chatGPT.py`의 `OpenAIModelError`, `func/youtube_api.py`의 `YouTubeApiError`로 adapter 실패를 안전하게 매핑 |
| 완료 | 운영 리소스 문서화 | `docs/jenkins-deploy.md`에 `mem_limit: 500m`, YouTube 요약/STT 리소스 주의, health check 점검 절차 추가 |
| 완료 | music queue helper 1차 분리 | `util/music/queue.py`로 queue 조작/preview/URL enqueue/search entry enqueue helper 이동, `test/test_music_queue_helpers.py`에서 music package import 경로 검증 |
| 완료 | music queue display helper 분리 | `util/music/queue.py`로 대기열 embed title/description 조립 이동, `_track_title` import 회귀 테스트 추가 |
| 완료 | music queue action facade 분리 | `util/music/queue_actions.py`로 대기열 삭제/비우기/이동/셔플 action 결과와 사용자 응답 문구를 이동하고 `MusicCog`는 음성 채널 guard와 Discord 응답 전송만 담당하도록 축소 |
| 완료 | music queue metadata helper 분리 | `util/music/queue.py`의 `apply_queue_track_metadata()`로 yt-dlp metadata dict의 단일 entry 선택과 QueuedTrack title/duration/webpage/uploader/thumbnail 반영을 이동하고, `MusicCog`는 추출 결과 전달만 담당하도록 축소 |
| 완료 | music queue metadata extraction helper 분리 | `util/music/queue.py`의 `extract_queue_track_metadata()`로 yt-dlp 추출 예외 회수와 dict 결과 필터링을 이동하고, `MusicCog`는 executor scheduling과 metadata 반영만 담당하도록 축소 |
| 완료 | music queue metadata runner helper 분리 | `util/music/queue.py`의 `fill_queue_track_metadata()`로 executor 실행, metadata 추출, QueuedTrack 반영 sequence를 이동하고, `MusicCog`는 yt-dlp extractor와 executor 전달만 담당하도록 축소 |
| 완료 | music queue helper 패키지 이동 | `util/music_queue.py`를 `util/music/queue.py`로 이동하고, `cogs.music`/music util/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |
| 완료 | music playback command facade 분리 | `util/music/playback_actions.py`로 일시정지/다시재생/정지/반복의 상태 전이, elapsed 계산, 사용자 응답 문구를 이동하고 `MusicCog`는 voice 제어와 Discord 패널 갱신만 담당하도록 축소 |
| 완료 | music skip/seek command facade 분리 | `util/music/playback_actions.py`로 스킵 loop 메시지, 구간 이동 길이 검증, seeking flag 시작/완료/실패 복구, 성공/실패 사용자 응답 문구를 이동하고 `MusicCog`는 voice stop/play와 Discord 패널 갱신만 담당하도록 축소 |
| 완료 | music search result action facade 분리 | `util/music/search.py`로 `/재생` 검색과 즐겨찾기 검색의 결과 필터링, 빈 결과 메시지, embed title/description 조립을 이동하고 `MusicCog`는 yt-dlp 실행, View 생성, Discord 응답 전송만 담당하도록 축소 |
| 완료 | music search yt-dlp executor helper 분리 | `util/music/search.py`의 `run_music_search_query()`로 `ytsearch10:` query 조립, yt-dlp `extract_info(download=False)` 호출, executor scheduling을 이동하고, `MusicCog`는 search action 결과 처리만 담당하도록 축소 |
| 완료 | music search result response helper 분리 | `MusicCog._send_music_search_response()`로 검색 결과 없음 메시지, Embed/View 생성, ephemeral 전송 sequence를 단일화하고, `_play()`와 즐겨찾기 검색 경로는 helper 호출만 담당하도록 축소 |
| 완료 | music search flow helper 분리 | `util/music/search.py`의 `build_music_search_flow()`로 검색 실행과 `MusicSearchActionResult` 생성을 묶고, `_play()`와 즐겨찾기 검색 경로는 flow 결과 응답만 담당하도록 축소 |
| 완료 | music play search branch helper 분리 | `MusicCog._play_music_search_branch()`로 `/재생` 키워드 검색 분기의 검색 flow 실행과 검색 결과 응답 호출을 묶고, `_play()`는 URL/검색 분기 선택만 담당하도록 축소 |
| 완료 | music URL play branch helper 분리 | `MusicCog._play_music_url_branch()`로 `/재생` URL 분기의 defer, 음성 연결 guard, 대기열 추가, player 준비, 재생 시작 응답을 묶고, `_play()`는 검색/URL 분기 선택만 담당하도록 축소 |
| 완료 | music URL immediate playback helper 분리 | `MusicCog._start_music_url_immediate_playback()`으로 `/재생` URL 즉시 재생의 player 준비, 준비 실패 응답, playback start, 확인 응답을 묶고, `_play_music_url_branch()`는 음성 guard와 queue/immediate 분기 선택만 담당하도록 축소 |
| 완료 | music URL immediate playback preparation helper 분리 | `MusicCog._prepare_music_url_immediate_player()`로 `/재생` URL 즉시 재생의 player 준비와 준비 실패 응답을 묶고, `_start_music_url_immediate_playback()`은 준비된 player 결과만 사용하도록 축소 |
| 완료 | music URL immediate playback start helper 분리 | `MusicCog._start_music_url_prepared_playback()`으로 `/재생` URL 즉시 재생의 playback start 생성, prepared playback 시작, debug 로그, 확인 응답 전송을 묶고, `_start_music_url_immediate_playback()`은 준비된 player를 start helper에 전달하도록 축소 |
| 완료 | music URL queued response helper 분리 | `MusicCog._send_music_url_queued_response()`로 `/재생` URL 대기열 추가 시 metadata 보강 task와 auto-delete 응답을 묶고, `_play_music_url_branch()`는 queue/immediate 분기 선택만 담당하도록 축소 |
| 완료 | music URL voice guard helper 분리 | `MusicCog._ensure_music_url_voice_client()`로 `/재생` URL 분기의 음성 채널 확인, 음성 연결/이동, guard 실패 응답, voice transition debug를 묶고, `_play_music_url_branch()`는 voice client 결과만 사용하도록 축소 |
| 완료 | music URL queue decision helper 분리 | `MusicCog._should_start_music_url_immediate_playback()`으로 `/재생` URL 분기의 active voice 판정, URL play action 호출, queued 응답 위임, 즉시 재생 여부 반환을 묶고, `_play_music_url_branch()`는 helper 결과에 따라 immediate playback만 호출하도록 축소 |
| 완료 | music URL branch immediate dispatch helper 분리 | `MusicCog._dispatch_music_url_immediate_playback()`으로 `/재생` URL 분기의 즉시 재생 여부 판정과 즉시 재생 시작 호출을 묶고, `_play_music_url_branch()`는 voice guard와 state 조회 뒤 dispatch helper만 호출하도록 축소 |
| 완료 | music URL branch state context helper 분리 | `MusicCog._get_music_url_branch_context()`로 `/재생` URL 분기의 guild id와 `GuildMusicState` 조회를 묶고, `_play_music_url_branch()`는 context helper, voice guard, dispatch helper만 호출하도록 축소 |
| 완료 | music URL branch defer helper 분리 | `MusicCog._defer_music_url_branch()`로 `/재생` URL 분기의 `skip_defer` 조건과 Discord defer 호출을 묶고, `_play_music_url_branch()`는 defer, context, voice guard, dispatch helper만 호출하도록 축소 |
| 완료 | music play command branch dispatch helper 분리 | `MusicCog._dispatch_music_play_command_branch()`로 `/재생` 명령의 검색어/URL 분기 선택을 묶고, `_play()`는 debug 로그와 branch dispatch helper 호출만 담당하도록 축소 |
| 완료 | music play command debug logging helper 분리 | `util/music/logging.py`로 music debug logger factory와 `/재생` debug 메시지 조립 helper를 이동하고, `_play()`는 helper 결과를 `dbg` alias로 전달하도록 축소 |
| 완료 | music play_url_now voice guard helper 분리 | `MusicCog._ensure_play_url_now_voice_client()`로 즐겨찾기/즉시 URL 재생 경로의 음성 채널 확인, 음성 연결/이동, guard 실패 응답, voice transition debug를 묶고, `_play_url_now()`는 voice client 결과만 사용하도록 축소 |
| 완료 | music play_url_now playback state helper 분리 | `util.music.playback_actions`의 `begin_play_url_now_playback_action()`/`complete_play_url_now_playback_action()`으로 즐겨찾기/즉시 URL 재생 경로의 stopping/skipping/seeking 상태 전이를 이동하고, `_play_url_now()`는 voice stop side effect와 playback start orchestration만 담당하도록 축소 |
| 완료 | music play_url_now player preparation helper 분리 | `MusicCog._prepare_play_url_now_player()`로 즐겨찾기/즉시 URL 재생 경로의 `prepare_music_player()` 호출과 준비 실패 응답을 묶고, `_play_url_now()`는 준비된 player 결과만 사용하도록 축소 |
| 완료 | music play_url_now playback start helper 분리 | `MusicCog._start_play_url_now_prepared_playback()`으로 즐겨찾기/즉시 URL 재생 경로의 playback start 생성, prepared playback 시작, replacement 상태 복구, 확인 응답 전송을 묶고, `_play_url_now()`는 준비된 player와 replacement 여부만 전달하도록 축소 |
| 완료 | music play_url_now replacement branch helper 분리 | `MusicCog._begin_play_url_now_replacement()`로 즐겨찾기/즉시 URL 재생 경로의 active voice 판정, replacement 상태 시작, 기존 voice stop을 묶고, `_play_url_now()`는 반환된 replacement 여부만 playback start helper에 전달하도록 축소 |
| 완료 | music URL play action facade 분리 | `util/music/playback_actions.py`로 URL 재생 시 active voice 여부에 따른 대기열 추가/즉시 준비 판단, queue track 반환, 사용자 응답 문구를 이동하고 `MusicCog`는 voice 연결, player 준비, metadata 보강 task, Discord 응답 전송만 담당하도록 축소 |
| 완료 | music search-pick queue action facade 분리 | `util/music/queue_actions.py`의 `begin_search_pick_queue_action()`으로 검색 선택 URL 보정, active voice 큐 삽입, queue track 반환, 사용자 응답 문구를 이동하고 `MusicCog`는 voice guard, metadata 보강 task, Discord 응답 전송만 담당하도록 축소 |
| 완료 | music queue added response 경로 통일 | `QUEUE_ADDED_MESSAGE` 상수와 `_send_auto_delete()`로 `_play`, `_play_from_search_pick` 대기열 추가 응답/auto-delete 반복 제거 |
| 완료 | music search pick voice error 응답 경로 통일 | `_play_from_search_pick`의 음성 연결 실패 응답이 직접 `followup.send()` 대신 `_send_auto_delete()`를 통과하도록 정리 |
| 완료 | music play URL voice error 응답 경로 통일 | `_play` URL 재생 경로의 음성 연결 실패 응답이 직접 `followup.send()` 대신 `_send_auto_delete()`를 통과하도록 정리 |
| 완료 | music play URL preparation error 응답 경로 통일 | `_play` URL 재생 준비 실패 응답이 직접 `followup.send()` 대신 `_send_auto_delete()`를 통과하고 기존 `delete_after`를 유지하도록 정리 |
| 완료 | music control voice guard 응답 경로 통일 | `_pause`, `_resume`, `_skip`, `_stop`, `_seek`, `_toggle_loop`의 같은 음성 채널 guard 실패 응답이 `_send_auto_delete()`를 통과하도록 정리 |
| 완료 | music control simple response 경로 통일 | `_pause`, `_resume`, `_skip`, `_stop`, `_seek`, `_toggle_loop`의 재생 없음/성공/단순 오류 응답이 직접 `_auto_delete()`를 조립하지 않고 `_send_auto_delete()`를 통과하도록 정리 |
| 완료 | music favorite/queue display response 경로 통일 | `_save_music_favorite()`와 `_show_queue()`가 직접 `_auto_delete()`를 조립하지 않고 `_send_auto_delete()`를 통과하도록 정리, embed 대기열 표시의 20초 삭제 유지 |
| 완료 | music playback confirmation response 경로 통일 | `_play_url_now()`와 `_play()`의 `playback_start.confirmation_message` 응답이 직접 `followup.send()`/`_auto_delete()`를 조립하지 않고 `_send_auto_delete()`를 통과하도록 정리 |
| 완료 | music search result response 경로 통일 | `_play()` 키워드 검색과 `_search_music_for_favorite_slot()`의 검색 실패/결과 embed 응답이 `_send_ephemeral_response()`를 통과하고 Discord 전송 예외만 warning 로그로 남기도록 정리 |
| 완료 | music favorite management response 경로 통일 | `_open_music_favorite_manager()` 관리 View 응답과 `_play_music_favorite()` 빈 슬롯 안내가 `_send_ephemeral_response()`를 통과하고 defer 후 followup 계약을 유지하도록 정리 |
| 완료 | music panel/input validation response 경로 통일 | `/음악` 패널 설정 안내와 `/구간이동` 시간 형식 오류 응답이 `_send_ephemeral_response()`를 통과하도록 정리 |
| 완료 | music channel warning auto-delete 경로 통일 | `on_message()`의 음악 전용 채널 경고 전송/자동삭제 조립을 `_send_channel_auto_delete()`로 분리하고 Discord 전송 예외만 debug 로그로 남기도록 정리 |
| 완료 | music cleanup broad exception 경로 구체화 | `idle_disconnect`와 `_force_stop()`의 음성 연결 해제/패널 갱신 cleanup 실패를 `_disconnect_voice_client_safely()`와 `_edit_music_panel_safely()`로 분리하고 예상 가능한 예외만 debug 로그로 남기도록 정리 |
| 완료 | music 메타데이터/즐겨찾기 broad exception 경로 구체화 | 패널 ID/즐겨찾기 로드는 DB/row 변환 예외만 warning 로그로 fallback하고, 대기열 메타데이터 추출은 `DownloadError`/I/O/값 변환 오류만 debug 로그로 회수하도록 정리 |
| 완료 | music 재생 제어/임베드 broad exception 경로 구체화 | `_resume`, `_seek`, 반복 재생 소스 준비, 기본/재생 임베드 생성 실패를 domain/Discord/값 변환 예외로 좁히고, 남은 lifecycle broad catch는 logger stack 로그를 남기도록 정리 |
| 완료 | music 상태성 `print`/logger 정리 | `cogs/music.py`의 direct `print()`를 제거하고 debug/status 출력이 `logger.debug/info`를 통과하도록 AST 정책 테스트로 고정 |
| 완료 | music progress helper 1차 분리 | `util/music/progress.py`로 시간 포맷, 진행바, timeline helper 이동, `MusicCog` 공개 메서드는 호환 wrapper 유지 |
| 완료 | music search helper 1차 분리 | `util/music/search.py`로 HTTP URL 판별, 검색 결과 URL 정규화, YouTube watch entry filtering, 검색 결과 표시 문자열 생성 이동 |
| 완료 | music embed helper 1차 분리 | `util/music/embeds.py`로 기본 패널/재생 중 embed 생성 이동, `MusicCog` 공개 wrapper 유지 |
| 완료 | music extractor helper 1차 분리 | `util/music/extractor.py`로 yt-dlp 포맷 후보 우선순위/선택 로직 이동 |
| 완료 | music View/Modal 1차 분리 | `util/music/views.py`로 검색 결과, 즐겨찾기 관리, helper/control View, search/seek modal 이동, `cogs.music` import 호환 유지 |
| 완료 | music panel store 1차 분리 | `util/music/panel_store.py`로 panel message id 로드/저장/삭제 DB 접근 이동 |
| 완료 | music favorite snapshot helper 분리 | `util/music/favorites.py`로 현재 재생 player -> 즐겨찾기 snapshot 변환 이동, `MusicCog`는 호환 wrapper만 유지 |
| 완료 | music favorite 저장 payload/action 분리 | `util/music/favorites.py`로 검색 결과 entry와 현재 재생 snapshot을 저장 payload로 정규화하고, `MusicCog`는 DB upsert, 패널 refresh, Discord 응답만 담당하도록 축소 |
| 완료 | music favorite play action facade 분리 | `util/music/favorites.py`의 `build_music_favorite_play_action()`으로 빈 슬롯 사용자 문구와 즐겨찾기 재생 URL/prefix를 이동하고, `MusicCog`는 DB 조회, Discord 응답, 재생 호출만 담당하도록 축소 |
| 완료 | music favorite manager selection action 분리 | `util/music/favorites.py`의 `build_music_favorite_manager_selection_action()`으로 슬롯 선택값 검증, 상태 문구, Select option default 판정을 이동하고, `MusicFavoriteSlotSelect`는 결과 적용과 Discord edit만 담당하도록 축소 |
| 완료 | music favorite modal/search submit action 분리 | `util/music/favorites.py`의 search modal/submit action helper로 modal 슬롯 검증과 검색어 정규화를 이동하고, `FavoriteSearchModal`과 manager 검색 버튼은 helper 결과 전달만 담당하도록 축소 |
| 완료 | music favorite current save button action 분리 | `util/music/favorites.py`의 `build_music_favorite_current_save_button_action()`으로 현재곡 저장 버튼 disabled 판정과 선택 슬롯 검증을 이동하고, `MusicFavoriteManageView`는 버튼 생성/Discord callback 연결만 담당하도록 축소 |
| 완료 | music favorite current track save action 분리 | `util/music/favorites.py`의 `build_music_favorite_current_track_save_action()`으로 현재 재생곡 없음 메시지와 저장 payload 생성을 이동하고, `MusicCog`는 defer, 응답 전송, DB 저장 호출만 담당하도록 축소 |
| 완료 | music favorite search request action 분리 | `util/music/favorites.py`의 `build_music_favorite_search_request_action()`으로 즐겨찾기 검색 저장 요청의 슬롯 검증, 검색어 정규화, 빈 검색어 사용자 메시지를 이동하고, `MusicCog`는 yt-dlp 검색과 결과 응답만 담당하도록 축소 |
| 완료 | music favorite manager open action 분리 | `util/music/favorites.py`의 `build_music_favorite_manager_open_action()`으로 관리자 View 초기 payload, 현재곡 snapshot, 초기 상태 문구 생성을 이동하고, `MusicCog`는 favorites 로드, View 생성, Discord 응답만 담당하도록 축소 |
| 완료 | music favorite play request action 분리 | `util/music/favorites.py`의 `build_music_favorite_play_request_action()`으로 즐겨찾기 재생 요청의 슬롯 검증을 이동하고, `MusicCog`는 DB 조회, 결과 action 생성, Discord 응답/재생 호출만 담당하도록 축소 |
| 완료 | music favorite save entry action 분리 | `util/music/favorites.py`의 `build_music_favorite_search_entry_save_action()`으로 검색 결과 즐겨찾기 저장 action payload 생성을 이동하고, `MusicCog`는 action payload를 공통 저장 경로로 전달하도록 축소 |
| 완료 | music favorite save side effect action 분리 | `util/music/favorites.py`의 `save_music_favorite_payload()`로 즐겨찾기 DB 저장 side effect와 저장 완료 사용자 메시지 결과 생성을 이동하고, `MusicCog`는 favorites reload, 패널 refresh, Discord 응답만 담당하도록 축소 |
| 완료 | music favorite save response action 분리 | `util/music/favorites.py`의 `build_music_favorite_save_response_action()`으로 저장 결과 이후 favorites reload, 패널 refresh, 사용자 응답 정책을 action으로 이동하고, `MusicCog`는 action flag에 따라 Discord side effect만 실행하도록 축소 |
| 완료 | music favorite panel refresh action 분리 | `util/music/favorites.py`의 `build_music_favorite_panel_refresh_action()`으로 패널 갱신 skip 조건과 playing/helper 패널 모드 선택을 이동하고, `MusicCog`는 action 결과에 따라 View/Embed 생성과 메시지 편집만 담당하도록 축소 |
| 완료 | music favorite cache load action 분리 | `util/music/favorites.py`의 `build_music_favorite_cache_load_action()`으로 즐겨찾기 캐시 hit/refresh bypass 판단을 이동하고, `MusicCog`는 action 결과에 따라 cache hit 반환 또는 DB 조회만 담당하도록 축소 |
| 완료 | music favorite cache store action 분리 | `util/music/favorites.py`의 `build_music_favorite_cache_store_action()`으로 DB 로드 결과의 cache 저장 payload 생성을 이동하고, `MusicCog`는 action 결과를 캐시에 반영하도록 축소 |
| 완료 | music favorite load failure action 분리 | `util/music/favorites.py`의 `build_music_favorite_load_failure_action()`으로 즐겨찾기 DB/row 로드 실패 fallback payload 생성을 이동하고, `MusicCog`는 warning 로그와 action 결과 반영만 담당하도록 축소 |
| 완료 | music favorite cache hit result action 분리 | `util/music/favorites.py`의 `build_music_favorite_cache_hit_result_action()`으로 cache hit 반환 payload 생성을 이동하고, `MusicCog`는 action 결과 반환만 담당하도록 축소 |
| 완료 | music favorite cache apply helper 분리 | `util/music/favorites.py`의 `apply_music_favorite_cache_store_action()`으로 cache 저장 side effect와 반환값 생성을 이동하고, `MusicCog`는 helper 호출만 담당하도록 축소 |
| 완료 | music favorite current player wrapper 제거 | `MusicCog._current_player_as_favorite()` 호환 wrapper를 제거하고, 현재곡 즐겨찾기 저장 경로가 `current_player_to_music_favorite()`를 직접 호출하도록 축소 |
| 완료 | music state helper 1차 분리 | `util/music/state.py`로 `GuildMusicState`와 playback/idle reset/start/finish 상태 전이 이동 |
| 완료 | music voice helper 1차 분리 | `util/music/voice.py`로 음성 연결, 채널 이동, 활성 상태 판단, 같은 음성 채널 guard, 연결 transition debug 이동 |
| 완료 | music playback start state 보강 | `util/music/state.py`에 재생 시작 상태 전이 helper 추가 |
| 완료 | music state helper 패키지 이동 | `util/music_state.py`를 `util/music/state.py`로 이동하고, `cogs.music`/music util/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |
| 완료 | music voice helper 패키지 이동 | `util/music_voice.py`를 `util/music/voice.py`로 이동하고, `cogs.music`/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |
| 완료 | music panel store helper 패키지 이동 | `util/music_panel_store.py`를 `util/music/panel_store.py`로 이동하고, `cogs.music`/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |
| 완료 | music favorites helper 패키지 이동 | `util/music_favorites.py`를 `util/music/favorites.py`로 이동하고, `cogs.music`/music views/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |
| 완료 | music views helper 패키지 이동 | `util/music_views.py`를 `util/music/views.py`로 이동하고, `cogs.music`/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |
| 완료 | music source preparation helper 분리 | `util/music/playback.py`로 `YTDLSource.from_url` 호출, 준비 실패 사용자 메시지 매핑, prepared playback payload 생성 이동 |
| 완료 | music playback side effect helper 분리 | `MusicCog._start_prepared_playback()`로 prepared player 이후 state/control view/voice/updater/panel edit sequence 단일화 |
| 완료 | music seek/queue continuation 준비 경로 보강 | seek, loop fallback refresh, 다음 대기열 곡 준비가 `prepare_music_player()`를 통과하도록 정리 |
| 완료 | music loop/skip replay source reuse 분리 | `util/music/playback.py`로 기존 audio URL 재사용과 refresh fallback source 준비 이동 |
| 완료 | music stream extraction helper 분리 | `util/music/stream.py`로 `ytInitialPlayerResponse` 파싱, HTML fallback audio URL/메타데이터 추출 이동 |
| 완료 | music search/meta extraction helper 분리 | `util/music/extractor.py`로 keyword search 결과 URL 결정과 yt-dlp entries selection 이동 |
| 완료 | music source facade 분리 | `util/music/source.py`로 `YTDLSource`, yt-dlp fallback, FFmpeg 옵션 조립, HTML stream fallback 호출 이동 |
| 완료 | lint/type checker 배치 결정 | 이번 보강 배치에서는 새 의존성 없이 `compileall`/unittest/`git diff --check`/AST 정책 테스트를 gate로 유지, `ruff`/type checker는 별도 후속 작업으로 분리 |
| 완료 | MapleStory notice state 1차 분리 | `util/maplestory_notice_state.py`로 공지 fingerprint/state/update 계산 이동, 기존 `util.maplestory_events` 공개 import 호환 유지 |
| 완료 | MapleStory parser 1차 분리 | `util/maplestory_parser.py`로 이벤트/공지 HTML parser와 dataclass 이동, 기존 `util.maplestory_events` 공개 import 호환 유지 |
| 완료 | MapleStory fetcher 1차 분리 | `util/maplestory_fetcher.py`로 이벤트/공지 HTML fetch와 상세 hydrate 이동, 기존 `util.maplestory_events` 공개 import 호환 유지 |
| 완료 | MapleStory sender 1차 분리 | `util/maplestory_sender.py`로 embed/message build, 채널 resolve, Discord send helper 이동, 기존 `util.maplestory_events` 공개 import 호환 유지 |
| 완료 | YouTube notification state 1차 분리 | `util/youtube/notification_state.py`로 notified ID 정규화, YouTube datetime 파싱, pending live 재검사 판단 이동 |
| 완료 | YouTube notification state helper 패키지 이동 | `util/youtube_notification_state.py`를 `util/youtube/notification_state.py`로 이동하고, `cogs.loop`/YouTube runner/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |
| 완료 | YouTube video status helper 패키지 이동 | `util/youtube_video_status.py`를 `util/youtube/video_status.py`로 이동하고, `cogs.loop`/WebSub surface/test import를 새 카테고리 패키지 경로로 통일했으며 root helper 제거를 경로 계약 테스트로 고정 |

이번 패치로 YouTube channel resolver helper의 `util/youtube/` 패키지 이동이 완료되었다. root `util/music*.py` helper는 더 이상 남지 않았고, 다음 작은 후보는 root YouTube util의 카테고리 패키지 이동이다.

## 현재 구조 요약

- `bot.py`: Discord 클라이언트 초기화, Cog 동적 로드, 메시지 캐시(`USER_MESSAGES`), 파티 상태(`PARTY_LIST`), DB 초기화
- `cogs/`: Discord 명령과 백그라운드 태스크 구현
  - 대형 Cog: `music.py`, `loop.py`, `voice_chat.py`, `youtube_subscriptions.py`
  - 패키지 Cog: `cogs/gambling/`
- `api/`: OpenAI, Riot, ECOS 환율/외환보유액 API 래퍼
- `func/`: YouTube 요약, 1557 감지 등 기능성 helper
- `util/`: DB, 채널 설정, YouTube 구독, MapleStory, D-day, 로깅 등 공유 유틸
- `test/`: unittest 기반 테스트. `test/`는 패키지가 아니므로 discovery 방식이 표준
- 배포: `Dockerfile.deps`로 의존성 이미지 구성, `docker-compose.yml`로 실행, `Jenkinsfile`이 배포 스크립트 실행

## 긍정적인 점

- Cog 기반 구조라 기능별 진입점이 비교적 명확하다.
- 최근 예외 보강으로 사용자-facing 오류 메시지와 내부 logger 스택 로깅이 상당 부분 정리되었다.
- `util/channel_settings.py`, `util/db.py`, `util/youtube_subscriptions.py`처럼 반복되는 저장소 접근을 공통 유틸로 모은 지점이 있다.
- Riot, Scheduler, YouTube, MapleStory, message context, music helper 등 핵심 경로에 unittest가 존재하고 현재 전체 테스트가 통과한다.
- Docker/Jenkins 배포 흐름과 health check가 저장소에 포함되어 있어 운영 재현성이 어느 정도 있다.

## 주요 문제점

### P1. Jenkins 배포에 테스트/컴파일 게이트가 없다

#### 근거

- `Jenkinsfile`은 checkout, 환경 검증, deploy 단계는 갖고 있지만 `compileall`이나 `python -m unittest discover -s test`를 배포 전에 실행하지 않는다.
- 현재 로컬 기준으로는 `compileall`과 unittest 154개가 통과한다.

#### 영향

- push 후 배포 파이프라인이 코드 회귀를 배포 전에 막지 못한다.
- 문법 오류, import 오류, command surface 회귀가 health check 전까지 감지되지 않을 수 있다.

#### 개선 방향

- Deploy 전에 `python -m compileall -q bot.py api cogs common func util test` 실행
- 이어서 `python -m unittest discover -s test` 실행
- 시간이 오래 걸리는 테스트가 생기면 fast suite와 integration suite를 분리

#### 완료 기준

- Jenkins 로그에 compile 단계와 unittest 단계가 deploy보다 먼저 표시된다.
- 테스트 실패 시 docker compose build/up 단계가 실행되지 않는다.
- 로컬과 Jenkins의 검증 명령이 README/AGENTS에 동일하게 문서화된다.

### P1. 로컬 검증 Python과 Docker 런타임 Python이 다르다

#### 근거

- 로컬 검증은 Python 3.11.9에서 수행되었다.
- `Dockerfile.deps`는 `python:3.12-slim`을 사용한다.

#### 영향

- `discord.py`, `faster-whisper`, `aiomysql`, `matplotlib`, `yt-dlp` 같은 런타임 의존성이 Python minor 버전에 따라 다르게 동작할 수 있다.
- 로컬 테스트 통과가 운영 컨테이너에서의 동작을 완전히 보장하지 못한다.

#### 개선 방향

- 운영 기준 Python minor 버전을 하나로 결정한다.
- 로컬, CI, Docker 이미지를 같은 minor 버전으로 맞춘다.
- 최소한 Jenkins 테스트를 Docker 이미지 안에서 실행해 실제 배포 환경과 맞춘다.

#### 완료 기준

- `Dockerfile.deps`, 로컬 개발 문서, Jenkins 검증 환경의 Python minor 버전이 일치한다.
- Jenkins 로그에 컨테이너 내부 Python 버전과 테스트 결과가 남는다.

### P1. `on_ready` 초기화가 재진입에 취약하다

#### 근거

- `bot.py`의 `on_ready`에서 `load_variable()`, `update_db_info()`, 글로벌 slash command sync를 매번 수행한다.
- `load_party_list()`는 `PARTY_LIST`를 전체 초기화하지 않고 카테고리를 append한다.

#### 영향

- Discord reconnect로 `on_ready`가 다시 호출되면 파티 카테고리 중복, DB upsert 반복, guild chunk 반복, 최근 메시지 재로드가 발생할 수 있다.
- 글로벌 command sync가 반복되어 Discord API 호출량과 startup 시간이 늘 수 있다.

#### 개선 방향

- bot-level `_startup_completed` 플래그를 둬 one-time startup과 reconnect handling을 분리한다.
- `PARTY_LIST[guild.id]`는 로드 전에 재계산 방식으로 초기화한다.
- command sync는 startup 1회 또는 명시 관리 명령으로 제한한다.

#### 완료 기준

- 같은 프로세스에서 `on_ready`가 두 번 호출되어도 `PARTY_LIST` 항목 수가 중복 증가하지 않는다.
- startup-only 작업과 reconnect-safe 작업이 함수 단위로 분리된다.
- 관련 단위 테스트 또는 fake bot 기반 테스트가 추가된다.

### P1. YouTube 요약은 고정 임시 파일명 때문에 동시성 위험이 있다

#### 근거

- `func/youtube_summary.py`는 `youtube_audio.mp3`, `youtube_subtitles.*.vtt` 같은 현재 작업 디렉터리의 고정 파일명을 사용한다.
- 요약 명령은 Discord interaction에서 동시에 여러 번 실행될 수 있다.

#### 영향

- 둘 이상의 `/요약` 또는 context menu 요약이 동시에 실행되면 서로의 파일을 삭제하거나 덮어쓸 수 있다.
- STT 입력이 다른 요청의 오디오로 바뀌거나 cleanup이 실패할 수 있다.

#### 개선 방향

- 요청마다 `tempfile.TemporaryDirectory()`를 만들고 그 안에 다운로드/변환 결과를 저장한다.
- `yt-dlp` `outtmpl`도 요청별 디렉터리로 제한한다.
- cleanup은 `finally`에서 해당 임시 디렉터리만 정리한다.

#### 완료 기준

- `process_youtube_video_link()`가 요청별 workspace를 인자로 받거나 내부에서 생성한다.
- 현재 작업 디렉터리에 `youtube_audio.mp3` 또는 `youtube_subtitles.*.vtt`를 남기지 않는다.
- 동시 실행 fake 테스트에서 두 요청의 파일 경로가 분리됨을 검증한다.

### P1. AI/OpenAI 응답 객체와 사용자 메시지가 콘솔에 과도하게 출력된다

#### 근거

- `api/chatGPT.py`는 OpenAI response 객체 전체를 `print(response)`로 출력한다.
- `bot.py`는 일반 메시지 원문과 최근 메시지 sample을 콘솔에 출력한다.

#### 영향

- 운영 로그에 사용자 대화, 이미지 URL, 모델 응답, prompt 관련 메타데이터가 남을 수 있다.
- 로그 보관/전송 경로가 넓어질수록 개인정보성 데이터 노출 위험이 커진다.

#### 개선 방향

- response 객체 전체 print를 제거한다.
- 사용자 메시지 원문 로그는 기본 비활성화하고 필요 시 debug + 길이 제한으로 바꾼다.
- 로그에는 guild/channel/message id, action, latency 같은 운영 메타데이터 중심으로 기록한다.

#### 완료 기준

- `api/chatGPT.py`에서 response 객체 전체 출력이 제거된다.
- `bot.py`의 메시지 원문 출력은 debug 옵션 또는 요약 메타데이터 출력으로 대체된다.
- 테스트 또는 AST 정책 검사로 `print(response)` 재도입을 막는다.

### P1. 대형 파일이 변경 위험을 키운다

#### 근거

| 파일 | 기준 커밋 줄 수 | 혼재된 책임 |
| --- | ---: | --- |
| `cogs/music.py` | 2663 | 재생 상태, UI, 검색, 즐겨찾기, 패널, queue, 음성 제어 |
| `func/youtube_summary.py` | 1072 | URL 파싱, post 파싱, 자막, 다운로드, STT, GPT, Discord UI |
| `cogs/loop.py` | 954 | presence, 일일 초기화, 1557, YouTube, MapleStory, WebSub 갱신 |
| `util/maplestory_events.py` | 875 | HTML parser, fetch, state, Discord send orchestration |

#### 영향

- 작은 기능 변경도 넓은 파일을 건드려 회귀 위험과 리뷰 비용이 커진다.
- 테스트 단위와 책임 경계가 흐려져 부분 개선이 어려워진다.

#### 개선 방향

- `music.py`: player state, yt-dlp extractor, panel view, favorite service, slash command facade 분리
- `youtube_summary.py`: link parsing, post parser, video transcript, media temp workspace, GPT summarizer, Discord UI 분리
- `loop.py`: YouTube loop, MapleStory loop, daily reset loop를 독립 service로 분리
- 한 번에 대형 리팩터링하지 말고 테스트가 있는 단위부터 점진 분리

#### 완료 기준

- 첫 분리 PR은 동작 변경 없이 한 책임만 이동한다.
- 이동 전후 `python -m unittest discover -s test`가 통과한다.
- 분리된 모듈에 최소 단위 테스트가 존재한다.

## 중간 우선순위 개선 항목

### P2. Cog 로드가 하나의 실패에 취약하다

#### 근거

- `bot.py`의 `load_cogs()`는 발견된 extension을 순차 로드하지만 개별 Cog 로드 실패를 격리하지 않는다.

#### 영향

- 하나의 Cog import/setup 실패가 전체 봇 부팅 실패로 이어질 수 있다.
- 선택 기능의 장애가 핵심 기능까지 막을 수 있다.

#### 개선 방향

- Cog별 `try/except`로 실패 extension과 traceback을 로깅한다.
- 필수 Cog와 선택 Cog를 구분한다.
- 실패 Cog 목록을 startup summary로 출력한다.

#### 완료 기준

- 선택 Cog 로드 실패가 있어도 필수 Cog는 로드된다.
- 실패 Cog 이름과 예외 stack이 로그에 남는다.
- 필수 Cog 실패 시에는 프로세스가 명확히 실패한다.

### P2. DB 스키마 변경이 앱 시작 시 직접 수행된다

#### 근거

- `util/db.py`의 `create_tables()`는 테이블 생성뿐 아니라 `_ensure_bigint_unsigned`, `_ensure_column`으로 DDL을 실행한다.

#### 영향

- 운영 DB가 커지면 startup 지연, 권한 문제, 부분 적용, 롤백 어려움이 생길 수 있다.
- 앱 시작 실패 원인이 schema migration인지 runtime 오류인지 구분하기 어려워진다.

#### 개선 방향

- schema version 테이블을 추가한다.
- 위험한 ALTER는 배포 전 migration 단계로 이동한다.
- 앱 시작 시에는 schema version 검증만 수행한다.

#### 완료 기준

- 앱 시작 코드와 migration 실행 코드가 분리된다.
- migration 실패 시 deploy 단계에서 중단된다.
- 현재 schema version이 로그 또는 health/debug 경로에서 확인 가능하다.

### P2. 의존성 문서와 실제 설치 경로가 불일치한다

#### 근거

- README는 `pip install -r requirements.txt`를 안내한다.
- AGENTS는 `pip_install.txt`를 사용하라고 안내한다.
- `pip_install.txt`는 requirements 파일 형식이 아니라 `pip install ...` 명령 모음에 가깝다.
- `requirements.txt`는 버전 pin이 거의 없어 재현성이 약하다.

#### 영향

- 새 환경에서 설치 방식이 달라져 재현성이 떨어진다.
- GPU 관련 패키지와 일반 런타임 의존성이 섞여 설치 실패 가능성이 커진다.

#### 개선 방향

- 운영 기준을 `requirements.txt`로 통일한다.
- `pip_install.txt`는 삭제하거나 `scripts/install-dev.ps1` 같은 스크립트로 변경한다.
- 주요 패키지 버전 pin 또는 lock 파일을 도입한다.
- GPU 관련 NVIDIA 패키지는 optional/dev 문서로 분리한다.

#### 완료 기준

- README, AGENTS, Dockerfile이 같은 의존성 진입점을 가리킨다.
- 새 venv에서 문서 명령 그대로 설치와 테스트가 가능하다.
- GPU optional 설치는 별도 명령으로 분리되어 있다.

### P2. WebSub token이 선택값이라 운영 실수에 취약하다

#### 근거

- `cogs/status_api.py`의 WebSub 검증은 `YOUTUBE_WEBSUB_VERIFY_TOKEN`이 없으면 모든 요청을 허용한다.

#### 영향

- 운영에서 token 누락 시 callback endpoint가 불필요하게 열릴 수 있다.
- 외부 요청이 WebSub 처리 경로까지 도달할 가능성이 커진다.

#### 개선 방향

- 운영 모드에서는 verify token을 필수화한다.
- `/health`와 `/youtube/websub`의 접근 정책을 README와 deploy 문서에 명확히 분리한다.
- token 누락 시 startup warning을 logger로 남긴다.

#### 완료 기준

- 운영 설정에서 token 누락 시 startup 또는 health validation이 실패한다.
- 로컬 개발에서는 명시적 dev mode에서만 token 생략이 허용된다.
- WebSub 검증 실패/성공 경로 테스트가 존재한다.

### P2. 외부 API 호출 정책이 분산되어 있다

#### 근거

- Riot은 `aiohttp` 기반으로 정리되어 있다.
- Google API client와 OpenAI sync client는 여러 곳에서 `asyncio.to_thread`로 감싸 쓰고 있다.
- timeout, retry, rate limit, user-facing fallback 정책이 adapter별로 흩어져 있다.

#### 영향

- API별 실패 메시지와 로그 수준이 달라진다.
- quota exhaustion, timeout, JSON 파싱 실패 같은 공통 장애의 처리가 일관되지 않다.

#### 개선 방향

- API adapter별 timeout/retry/error mapping 표준을 정한다.
- Discord command layer에서는 domain exception만 처리한다.
- 외부 API rate limit과 quota exhaustion 메시지를 통일한다.

#### 완료 기준

- OpenAI, Google, Riot adapter가 각각 domain exception을 노출한다.
- 사용자-facing 오류 메시지는 공통 helper를 통과한다.
- timeout/rate limit 테스트가 adapter 단위로 존재한다.

### P2. 테스트는 늘었지만 CI/품질 게이트는 부족하다

#### 근거

- unittest는 154개로 의미 있는 기준선이 있다.
- formatter/linter/type checker는 아직 없다.
- AST 기반 정책 테스트는 일부 예외 정책만 보완한다.

#### 영향

- 스타일, import, 타입 회귀를 자동으로 잡기 어렵다.
- 대형 파일 분리 과정에서 테스트가 없는 경계의 회귀를 놓칠 수 있다.

#### 개선 방향

- 우선 Jenkins에 현재 검증 명령을 추가한다.
- 이후 `ruff`를 lint-only로 도입하고 자동 포맷은 별도 단계로 검토한다.
- 타입 힌트가 늘어난 파일부터 `mypy` 또는 `pyright` 부분 적용을 검토한다.

#### 완료 기준

- CI에서 compile, unittest, diff/whitespace 검사가 실행된다.
- lint/type 도입 시 baseline 예외 목록이 문서화되어 있다.
- 새 코드에는 lint/type 예외를 늘리지 않는 정책이 있다.

## 낮은 우선순위 개선 항목

### P3. 로그 체계가 아직 print와 logger가 혼재한다

#### 근거

- 예외 로그는 최근 많이 정리되었지만 상태성 출력은 여전히 `print`가 많다.

#### 영향

- 운영 로그 검색, 레벨 관리, 구조화가 어렵다.
- 사용자 콘텐츠 로그와 운영 메타 로그가 섞일 수 있다.

#### 개선 방향

- 상태 안내 `print`는 점진적으로 `logger.info/debug`로 이동한다.
- guild/channel/action extra field를 사용하는 helper를 추가한다.
- health/debug 로그와 사용자 콘텐츠 로그를 분리한다.

#### 완료 기준

- 신규 코드에서 상태성 `print`를 사용하지 않는다.
- 운영 로그에서 action, guild_id, channel_id 기준 검색이 가능하다.
- 사용자 메시지 원문 로그는 기본 비활성화되어 있다.

### P3. 문서가 현재 테스트 체계를 반영하지 않는다

#### 근거

- AGENTS에는 "No formal unit test suite"라고 되어 있지만 현재는 unittest discovery 기반 테스트가 존재하고 통과한다.

#### 영향

- 새 작업자가 오래된 안내를 따르면 검증을 놓칠 수 있다.
- `python -m unittest test.xxx`처럼 실패하는 실행 방식을 다시 사용할 수 있다.

#### 개선 방향

- AGENTS와 README에 `python -m unittest discover -s test`를 공식 검증 명령으로 명시한다.
- `test/`가 importable package가 아니라는 점도 명시한다.

#### 완료 기준

- README와 AGENTS의 테스트 안내가 현재 repo 동작과 일치한다.
- focused test 예시도 discovery mode를 사용한다.

### P3. 배포 문서에 운영 리소스 기준이 부족하다

#### 근거

- `docker-compose.yml`의 `mem_limit: 500m`는 고정되어 있다.
- STT, ffmpeg, matplotlib 그래프, yt-dlp가 같은 프로세스에서 동작할 수 있다.

#### 영향

- 음성/STT와 YouTube 요약이 겹치면 메모리 부족 또는 처리 지연이 발생할 수 있다.
- 운영 리소스 부족이 애플리케이션 버그처럼 보일 수 있다.

#### 개선 방향

- 기능별 예상 메모리 사용량을 측정한다.
- 음성/STT 기능을 운영에서 사용할지 결정한다.
- 필요하면 voice/STT 기능을 optional worker로 분리한다.

#### 완료 기준

- README 또는 deploy 문서에 권장 CPU/메모리 기준이 있다.
- health check 실패 시 리소스 부족 여부를 확인하는 운영 절차가 있다.

## 권장 실행 순서

| 순서 | 작업 | 첫 패치 범위 | 검증 명령 | 예상 리스크 |
| ---: | --- | --- | --- | --- |
| 1 | Jenkins 테스트 게이트 | `Jenkinsfile`에 compile/unittest stage 추가 | Jenkins dry run 또는 실제 빌드 로그, `git diff --check` | 테스트 시간이 배포 시간을 늘릴 수 있음 |
| 2 | `on_ready` guard | `bot.py`의 startup-only 작업 분리와 `PARTY_LIST` 재계산 | fake bot 단위 테스트, `python -m unittest discover -s test` | command sync 타이밍이 바뀔 수 있음 |
| 3 | YouTube temp workspace | `func/youtube_summary.py`의 고정 파일명을 요청별 temp dir로 이동 | YouTube summary 단위 테스트, 동시 실행 fake 테스트 | yt-dlp outtmpl 변경으로 파일 탐색 로직 조정 필요 |
| 4 | 민감 로그 제거 | `api/chatGPT.py`, `bot.py`의 원문/response 출력 제거 | AST 정책 테스트, `python -m unittest discover -s test` | 디버깅 정보가 줄어들 수 있음 |
| 5 | 문서 최신화 | README/AGENTS 테스트/의존성 안내 갱신 | `git diff --check`, 문서 리뷰 | 문서와 실제 설치 경로를 함께 맞춰야 함 |
| 6 | Python 버전 통일 | Dockerfile/문서/CI 기준 버전 결정 | 컨테이너 내부 `python --version`, 전체 테스트 | 일부 패키지 wheel 호환성 확인 필요 |
| 7 | 대형 파일 1차 분리 | 가장 테스트가 쉬운 parser/service부터 이동 | 이동 대상 단위 테스트, 전체 unittest | import cycle과 command 등록 회귀 가능 |

## 추천 추적 이슈 초안

| 우선순위 | 제목 | 완료 기준 |
| --- | --- | --- |
| P1 | Jenkins 배포 전 테스트 게이트 추가 | 배포 전 compile/unittest 실패 시 pipeline 중단 |
| P1 | YouTube 요약 임시 파일 동시성 수정 | 동시 요약 요청이 서로 다른 temp workspace 사용 |
| P1 | `on_ready` 초기화 one-time guard 추가 | reconnect 시 중복 상태/DB/API 호출 방지 |
| P1 | OpenAI/메시지 원문 로그 제거 또는 debug 제한 | 운영 로그에 response 객체/원문 메시지 미출력 |
| P2 | Python 버전 통일 | 로컬/CI/Docker Python minor version 일치 |
| P2 | DB migration 체계 도입 | startup DDL과 migration 실행 경로 분리 |
| P2 | 외부 API adapter 정책 표준화 | timeout/rate limit/domain exception 정책 통일 |
| P3 | README/AGENTS 최신화 | 테스트/설치 안내가 현재 repo 동작과 일치 |

## Evidence Appendix

| 항목 | 확인 근거 | 의미 |
| --- | --- | --- |
| 현재 커밋 | `git rev-parse --short HEAD` -> `34aab00` | 분석 기준 커밋 |
| 작업트리 | `git status --short --branch` -> `main...origin/main`, slice별 구현 커밋은 원격 main에 push됨 | 진행 작업은 커밋 단위로 분리됨 |
| Python 버전 | `python --version` -> `Python 3.11.9` | 로컬 검증 환경 |
| Docker Python | 기준 커밋 `Dockerfile.deps` -> `FROM python:3.12-slim`, 현재 작업트리 -> `FROM python:3.11-slim` | 로컬/운영 Python minor version 불일치가 해소됨 |
| 테스트 기준선 | `python -m unittest discover -s test` -> 154개 통과 | 현재 회귀 테스트 기준 |
| 컴파일 기준선 | `python -m compileall -q bot.py api cogs common func util test` 통과 | 문법/import 기본 검증 |
| 작업트리 최신 검증 | `python -m compileall -q bot.py api cogs common func util test scripts` 통과, `python -m unittest discover -s test` -> 470개 통과 | 구현 진행 후 회귀 확인 |
| 파일 수 | PowerShell 파일 집계 -> Python 파일 96개 | 분석 규모 |
| 대형 파일 기준선 | 기준 커밋 line count: `music.py` 2663, `youtube_summary.py` 1072, `loop.py` 954, `maplestory_events.py` 875 | 분리 우선 후보였던 초기 상태 |
| 대형 파일 현재 | Python read line count: `music.py` 1706, `youtube_summary.py` 191, `loop.py` 309, `maplestory_events.py` 251 | 분리 진행 후에도 `music.py`는 command/action facade 축소 여지가 큼 |
| 대형 파일 1차 분리 | `util/music/queue.py` 추출, `test/test_music_queue_helpers.py` 19개 통과 | `music.py` queue 책임 일부 축소 |
| music queue display/enqueue/action/metadata/metadata-extraction/metadata-runner helper 분리 | `util/music/queue.py` 213줄, `util/music/queue_actions.py` 83줄, `cogs/music.py` 현재 1706줄, queue helper/action 대상 테스트 28개 통과, command surface 대상 테스트 50개 통과, `test_music*.py` 222개 통과 | 대기열 표시 title/description 조립, `_play` active-voice URL enqueue, `_play_from_search_pick` 검색 선택 URL 보정과 active-voice queue enqueue, yt-dlp metadata dict의 QueuedTrack 반영, metadata 추출 예외 회수/dict 결과 필터링, executor scheduling과 QueuedTrack 반영 sequence, 삭제/비우기/이동/셔플 사용자 응답 문구를 command handler에서 분리하고 `_track_title` import 누락과 queue action/metadata 계약을 테스트로 고정했으며, root `util/music_queue.py`와 `util/music_queue_actions.py` 제거를 테스트로 고정 |
| music playback/skip/seek/URL action helper 분리 | `util/music/playback_actions.py` 125줄, `cogs/music.py` 현재 1706줄, playback action 대상 테스트 18개 통과, `test_music*.py` 220개 통과 | 일시정지/다시재생/정지/반복/스킵/구간 이동에 더해 URL 재생의 active voice 대기열 추가/즉시 준비 판단, play_url_now replacement 상태 전이, queue track 반환, 사용자 응답 문구를 command handler에서 분리하고, root `util/music_playback_actions.py` 제거를 테스트로 고정 |
| music URL play branch/immediate playback/preparation/start/queued response/voice guard/queue decision/branch dispatch/state context/defer/play_url_now voice guard/playback state/player preparation/playback start/replacement branch helper 분리 | `cogs/music.py` 현재 1706줄, command surface 대상 테스트 50개 통과 | `_play_music_url_branch()`가 `/재생` URL 분기의 defer, context 조회, voice guard, immediate dispatch만 담당하고, `_defer_music_url_branch()`가 `skip_defer` 조건과 Discord defer 호출을, `_get_music_url_branch_context()`가 guild id와 `GuildMusicState` 조회를, `_ensure_music_url_voice_client()`가 URL 분기 음성 guard를, `_should_start_music_url_immediate_playback()`이 active voice 판정과 queued 응답 위임을, `_dispatch_music_url_immediate_playback()`이 즉시 재생 여부 판정과 즉시 재생 시작 호출을, `_prepare_music_url_immediate_player()`가 `/재생` URL 즉시 재생 player 준비/실패 응답을, `_start_music_url_prepared_playback()`이 `/재생` URL 즉시 재생 playback start/확인 응답을, `_ensure_play_url_now_voice_client()`가 즉시 URL 재생 경로 음성 guard를, `_prepare_play_url_now_player()`가 즉시 URL 재생 player 준비/실패 응답을, `begin_play_url_now_playback_action()`/`complete_play_url_now_playback_action()`이 replacement 상태 전이를, `_begin_play_url_now_replacement()`가 active voice 판정과 기존 voice stop을, `_start_play_url_now_prepared_playback()`이 즉시 URL 재생 playback start/상태 복구/확인 응답을, `_start_music_url_immediate_playback()`이 준비된 player의 start helper 위임을, `_send_music_url_queued_response()`가 queued metadata task와 auto-delete 응답을 담당하도록 고정 |
| music play command branch dispatch helper 분리 | `cogs/music.py` 현재 1706줄, command surface 대상 테스트 50개 통과 | `_dispatch_music_play_command_branch()`가 `/재생` 명령의 검색어/URL 분기 선택, 검색 branch 위임, URL branch `skip_defer` 전달을 담당하고, `_play()`는 debug 로그와 branch dispatch helper 호출만 담당하도록 고정 |
| music play command debug logging helper 분리 | `util/music/logging.py` 35줄 추가, `cogs/music.py` 현재 1706줄, logging 대상 테스트 4개 추가, command surface 대상 테스트 50개 통과 | 새 music util은 `util/music/` 카테고리 패키지에 배치하고, `log_music_debug()`/`make_music_debug_logger()`가 music debug prefix와 sink 실패 회수를 담당하며, `build_music_play_command_debug_message()`가 `/재생` debug 메시지 조립을 담당하도록 고정 |
| music queue/error response 경로 통일 | `QUEUE_ADDED_MESSAGE`, `_send_auto_delete()`, `_send_ephemeral_response()`, `_send_channel_auto_delete()`, cleanup helper, command surface 대상 테스트 36개 통과 | `_play`와 `_play_from_search_pick`의 대기열 추가 응답, search pick 음성 연결 실패 응답, `_play` URL 음성 연결/준비 실패 응답, 제어 명령 guard/재생 없음/성공/단순 오류 응답, 즐겨찾기 저장/관리/대기열 표시/재생 시작 확인/검색 결과/패널 안내/입력 검증/채널 경고/cleanup/metadata/playback-control/lifecycle/logging/queue-action/playback-action/skip-seek-action/search-action/url-play-action/search-pick-action 경로가 helper 또는 구체 예외 정책을 통과하도록 고정 |
| music progress helper 분리 | `util/music/progress.py` 39줄, `cogs/music.py` 현재 1706줄, progress 대상 테스트 5개 통과, `test_music*.py` 214개 통과 | 시간/진행률 UI helper를 music Cog 본문에서 분리하고, root `util/music_progress.py` 제거를 테스트로 고정 |
| music search helper/action/yt-dlp executor/response/flow/play-branch helper 분리 | `util/music/search.py` 115줄, `cogs/music.py` 현재 1706줄, search 대상 테스트 13개 및 command surface 대상 테스트 50개 통과, `test_music*.py` 215개 통과 | HTTP URL 판별, 검색 결과 URL 정규화, watch entry filtering, 검색 결과 embed title/description 조립, `/재생` 검색과 즐겨찾기 검색의 빈 결과 메시지/표시 payload action, `ytsearch10:` query 조립과 yt-dlp executor scheduling, 검색 결과 없음/Embed/View/ephemeral response sequence, 검색 실행과 action mapping flow, `/재생` 키워드 검색 분기 위임 helper를 music Cog 검색 분기에서 분리하고, root `util/music_search.py` 제거를 테스트로 고정 |
| music embed helper 분리 | `util/music/embeds.py` 97줄, `cogs/music.py` 현재 1706줄, embed 대상 테스트 4개 통과, `test_music*.py` 214개 통과 | 기본 패널/재생 중 embed 생성 UI 책임을 music Cog 본문에서 분리하고, root `util/music_embeds.py` 제거를 테스트로 고정 |
| music extractor helper 분리 | `util/music/extractor.py` 47줄, `cogs/music.py` 현재 1706줄, extractor 대상 테스트 11개 통과, `test_music*.py` 216개 통과 | yt-dlp 포맷 후보 우선순위, keyword search URL 결정, entries selection 로직을 music Cog 본문에서 분리하고, root `util/music_extractor.py` 제거를 테스트로 고정 |
| music View/Modal 분리 | `util/music/views.py` 367줄, `cogs/music.py` 현재 1706줄, views 대상 테스트 4개 통과, `test_music*.py` 227개 통과 | 검색 결과/즐겨찾기/control/helper View와 search/seek modal을 music Cog 본문에서 분리하고, root `util/music_views.py` 제거를 테스트로 고정 |
| music panel store 분리 | `util/music/panel_store.py` 44줄 추출, `cogs/music.py` 현재 1706줄, panel store 대상 테스트 5개 통과, `test_music*.py` 225개 통과 | panel message id 로드/저장/삭제 DB 접근을 music Cog 본문에서 분리하고, root `util/music_panel_store.py` 제거를 테스트로 고정 |
| music favorite snapshot/payload/play/play-request/save-entry/save-side-effect/save-response/panel-refresh/cache-load/cache-hit/cache-store/cache-apply/load-failure/manager/modal/current-button/current-track/search-request/manager-open/current-player-wrapper helper 분리 | `util/music/favorites.py` 현재 517줄, `cogs/music.py` 현재 1706줄, favorite 대상 테스트 48개 및 command surface 대상 테스트 50개 통과, `test_music*.py` 226개 통과 | 현재 재생 player를 즐겨찾기 snapshot으로 바꾸고, 검색 결과 entry와 현재 재생 snapshot을 저장 payload/action으로 정규화하며, 저장 DB side effect와 완료 메시지 결과 생성을 util helper로 이동하고, 저장 결과 이후 favorites reload, 패널 refresh, 사용자 응답 정책과 패널 refresh skip/playing/helper 모드 선택, 캐시 hit/refresh bypass 판단, cache hit 반환 payload, cache 저장 payload 생성, cache 저장 side effect/반환값, 로드 실패 fallback payload 생성을 action/helper로 고정하고 현재곡 저장 wrapper를 제거했으며, 빈 슬롯/재생 URL action 판단, 즐겨찾기 재생 URL voice guard/playback state/player preparation, 즐겨찾기 재생 요청 슬롯 검증, 검색 결과 저장 action payload 생성, manager 슬롯 선택/관리자 open 상태 계산, favorite 검색 modal/submit 정규화, 현재곡 저장 버튼 disabled/slot 판정, 현재 재생곡 없음 메시지/저장 payload 생성, 검색 저장 요청 슬롯/검색어 검증을 music Cog/View 본문에서 분리하고, root `util/music_favorites.py` 제거를 테스트로 고정 |
| music state helper 분리 | `util/music/state.py` 55줄 추출, `cogs/music.py` 현재 1706줄, state 대상 테스트 6개 통과, `test_music*.py` 223개 통과 | `GuildMusicState`와 playback/idle reset/playback start/track finish 상태 전이를 music Cog 본문에서 분리하고, root `util/music_state.py` 제거를 테스트로 고정 |
| music voice helper 분리 | `util/music/voice.py` 78줄 추출, `cogs/music.py` 현재 1706줄, voice 대상 테스트 12개 통과, `test_music*.py` 224개 통과 | 음성 연결, 채널 이동, 재생/일시정지 활성 상태 판단, 같은 음성 채널 guard, 연결 transition debug를 music Cog 본문에서 분리하고, root `util/music_voice.py` 제거를 테스트로 고정 |
| music source preparation/playback payload helper 분리 | `util/music/playback.py` 113줄, `cogs/music.py` 현재 1706줄, playback 대상 테스트 9개 통과, `test_music*.py` 219개 통과 | 일반 재생, 즐겨찾기 재생, seek, loop fallback refresh, 다음 대기열 곡 준비의 `YTDLSource.from_url` 호출과 FFmpeg/스트림 준비 실패 매핑, loop/skip replay source 재사용, prepared player의 source/확인 메시지 payload와 prepared playback side effect sequence를 단일화하고, root `util/music_playback.py` 제거를 테스트로 고정 |
| music stream extraction helper 분리 | `util/music/stream.py` 51줄, `cogs/music.py` 현재 1706줄, stream 대상 테스트 5개 통과, `test_music*.py` 217개 통과 | HTML fallback의 `ytInitialPlayerResponse` 파싱, 최고 bitrate audio URL 선택, stream metadata 구성을 music Cog 본문에서 분리하고, root `util/music_stream.py` 제거를 테스트로 고정 |
| music search/meta extraction helper 분리 | `util/music/extractor.py` 47줄, `test/test_music_extractor.py` 11개 통과, `test_music*.py` 216개 통과 | keyword search 결과 URL 결정과 yt-dlp `entries` 중 포맷 포함 엔트리 선택을 테스트 가능한 helper로 고정하고, root `util/music_extractor.py` 제거를 테스트로 고정 |
| music source facade 분리 | `util/music/source.py` 306줄, `cogs/music.py` 현재 1706줄, source 대상 테스트 4개 통과, `test_music*.py` 218개 통과 | `YTDLSource`, yt-dlp fallback 전략, FFmpeg 옵션 조립, HTML stream fallback 호출을 music Cog 본문에서 분리하고, root `util/music_source.py` 제거를 테스트로 고정 |
| lint/type checker 배치 결정 | `ruff`, `mypy`, `pyright` 설정 파일/의존성 추가 없음; 현재 gate는 `compileall`, unittest, `git diff --check`, AST 정책 테스트 | 새 외부 패키지를 추가하지 않는 이번 배치의 범위를 지키고, lint/type 정식 도입은 별도 baseline 작업으로 분리 |
| YouTube post parser 분리 | `func/youtube_post.py` 174줄 추출, YouTube post 대상 테스트 7개 통과 | 커뮤니티 게시물 파싱/입력 포맷팅을 영상 요약 실행 경로에서 분리 |
| YouTube transcript helper 분리 | `func/youtube_transcript.py` 38줄 추출, transcript 대상 테스트 2개 통과 | 자막 파일 정리/정규화를 영상 요약 orchestration에서 분리 |
| YouTube media helper 분리 | `func/youtube_media.py` 298줄 추출, media 대상 테스트 1개 통과 | 자막 다운로드/MP3 변환/STT를 요약 orchestration에서 분리 |
| YouTube GPT summarizer 분리 | `func/youtube_summarizer.py` 54줄 추출, summarizer 대상 테스트 3개 통과 | OpenAI prompt/model 호출을 Discord UI/process orchestration에서 분리 |
| YouTube summary UI 분리 | `func/youtube_summary_ui.py` 115줄 추출, UI 대상 테스트 2개 통과 | Discord prompt/View/check_youtube_link를 process orchestration에서 분리 |
| YouTube process orchestration 분리 | `func/youtube_processor.py` 144줄 추출, `func/youtube_summary.py` 현재 191줄, processor 대상 테스트 4개 통과 | post/video 요약 실행, 요청별 workspace cleanup, domain error mapping을 facade에서 분리 |
| MapleStory 상태 분리 | `util/maplestory_notice_state.py` 103줄 추출, state 대상 테스트 1개 통과 | 공지 상태 계산을 parser/fetch/send orchestration에서 분리 |
| MapleStory parser 분리 | `util/maplestory_parser.py` 394줄 추출, parser 대상 테스트 2개 및 기존 MapleStory events 테스트 14개 통과 | 이벤트/공지 HTML parser와 dataclass를 fetch/send orchestration에서 분리 |
| MapleStory fetcher 분리 | `util/maplestory_fetcher.py` 91줄 추출, fetcher 대상 테스트 4개 통과 | 이벤트/공지 HTML fetch와 상세 hydrate를 send orchestration에서 분리 |
| MapleStory sender 분리 | `util/maplestory_sender.py` 154줄 추출, `util/maplestory_events.py` 현재 251줄, sender 대상 테스트 4개 통과 | embed/message build, 채널 resolve, Discord send helper를 refresh/state orchestration에서 분리 |
| YouTube notification 상태 분리 | `util/youtube/notification_state.py` 168줄, YouTube notification state 대상 테스트 10개 통과 | pending live 재검사, notified ID 계산, live/upload/pending 상태 저장, pending check timestamp 갱신을 loop orchestration에서 분리하고, root `util/youtube_notification_state.py` 제거를 테스트로 고정 |
| Loop task lifecycle 분리 | `util/loop_task_lifecycle.py` 31줄 추출, lifecycle 대상 테스트 3개 통과 | 반복 task start/cancel 정책을 Cog 본문에서 분리하고 unload cleanup 추가 |
| WebSub subscription helper 분리 | `util/youtube_websub_subscription.py` 151줄 추출, `cogs/loop.py` 현재 309줄, WebSub subscription 대상 테스트 6개 통과 | callback URL 구성, subscribe/unsubscribe 요청, live/upload 구독 대상 필터링, WebSub 상태 저장을 loop Cog 본문에서 분리 |
| WebSub notification handler 분리 | `util/youtube_websub_notification.py` 49줄 추출, `cogs/loop.py` 현재 309줄, WebSub notification 대상 테스트 1개 통과 | Atom notification 파싱, 구독 조회, 후보 처리 결과 집계를 loop Cog 본문에서 분리 |
| YouTube community polling helper 분리 | `util/youtube_community_polling.py` 66줄 추출, `cogs/loop.py` 현재 309줄, community polling 대상 테스트 3개 통과 | 커뮤니티 post fetch, fetch 실패 warning, notification processing 위임을 loop Cog 본문에서 분리 |
| YouTube video status helper 분리 | `util/youtube/video_status.py` 28줄, `cogs/loop.py` 현재 309줄, video status 대상 테스트 3개 통과 | Google `videos.list` 요청과 응답 classification을 loop Cog 본문에서 분리하고, root `util/youtube_video_status.py` 제거를 테스트로 고정 |
| YouTube channel resolver helper 패키지 이동 | `util/youtube/channel_resolver.py` 102줄, channel resolver 대상 테스트 7개 통과 | YouTube 채널 ID/handle/search 입력 resolve helper를 YouTube 카테고리 패키지로 이동하고, root `util/youtube_channel_resolver.py` 제거를 테스트로 고정 |
| YouTube community notification 분리 | `util/youtube_community_notification.py` 160줄 추출, `cogs/loop.py` 현재 309줄, community notification 대상 테스트 5개 통과 | 커뮤니티 embed/message build, 최초 post ID seed, 새 게시물 알림 전송과 상태 저장을 loop Cog 본문에서 분리 |
| YouTube Atom feed fallback 분리 | `util/youtube_feed_fallback.py` 160줄 추출, `cogs/loop.py` 현재 309줄, feed fallback 대상 테스트 4개 통과 | Atom feed polling throttle, feed fetch, seen update tracking, 후보 dispatch/refetch를 loop Cog 본문에서 분리 |
| YouTube loop runner 분리 | `util/youtube_loop_runner.py` 94줄, `cogs/loop.py` 현재 309줄, runner 대상 테스트 2개 통과 | YouTube 후보 확인, pending check timestamp helper 호출, 커뮤니티 task orchestration을 loop Cog 본문에서 분리 |
| YouTube video candidate runner 분리 | `util/youtube_video_candidate_runner.py` 132줄 추출, `cogs/loop.py` 현재 309줄, video candidate 대상 테스트 3개 통과 | live/upcoming/upload/shorts candidate 상태 처리와 outcome 반환을 loop Cog 본문에서 분리 |
| YouTube notification sender 분리 | `util/youtube_notification_sender.py` 110줄 추출, `cogs/loop.py` 현재 309줄, sender 대상 테스트 4개 통과 | live/upload 알림 대상 채널 resolve와 메시지 전송을 loop Cog 본문에서 분리 |
| Daily refresh runner 분리 | `util/daily_refresh_runner.py` 106줄 추출, `cogs/loop.py` 현재 309줄, daily refresh 대상 테스트 2개 통과 | 기념일/DDAY/썬데이메이플/user message reset orchestration을 loop Cog 본문에서 분리 |
| WebSub renewal runner 분리 | `util/youtube_websub_renewal.py` 24줄 추출, `cogs/loop.py` 현재 309줄, WebSub renewal 대상 테스트 2개 통과 | 주기적 WebSub 갱신 호출과 성공 로그를 loop Cog 본문에서 분리 |
| Weekly 1557 report runner 분리 | `util/weekly_1557_reporter.py` 66줄 추출, `cogs/loop.py` 현재 309줄, weekly 1557 대상 테스트 3개 통과 | 주간 1557 리포트 생성, 전송, 카운트 초기화 orchestration을 loop Cog 본문에서 분리 |
| Presence status helper 분리 | `util/presence_status.py` 20줄 추출, `cogs/loop.py` 현재 309줄, presence 대상 테스트 3개 통과 | USER_MESSAGES 캐시 집계와 Discord presence 문구 생성을 loop Cog 본문에서 분리 |
| MapleStory notice loop runner 분리 | `util/maplestory_notice_loop_runner.py` 47줄 추출, `cogs/loop.py` 현재 309줄, MapleStory notice loop 대상 테스트 2개 통과 | 공지 refresh 결과 집계, 실패 로그, 전송 건수 로그를 loop Cog 본문에서 분리하고 3분 polling 위치는 유지 |
| env 추적 상태 | `git check-ignore -v .env .env.deploy`; `git ls-files .env .env.deploy` empty | 비밀 파일은 ignore 상태 |
| Jenkins 테스트 단계 | 기준 커밋 `Jenkinsfile`에는 checkout/validate/deploy만 있었고, 현재 작업트리에는 `Verify` stage 추가 | 배포 전 compile/unittest gate 부재가 해소됨 |
| 설치 안내 불일치 | README는 `requirements.txt`, AGENTS는 `pip_install.txt` 안내 | 문서 정합성 개선 필요 |

## 결론

현재 코드는 테스트 기준선이 있고 최근 예외 보강으로 런타임 실패 대응이 크게 좋아졌다. 다만 운영 안정성 관점에서는 배포 전 테스트 부재, `on_ready` 재진입, YouTube 요약 임시 파일 동시성, 민감한 로그 출력이 가장 먼저 처리할 문제다. 이후에는 대형 파일 분리와 의존성/DB migration 체계를 잡는 순서가 비용 대비 효과가 높다.

가장 먼저 할 일은 다음 다섯 가지로 고정한다.

1. Jenkins 테스트 게이트 추가
2. `on_ready` guard 추가
3. YouTube temp workspace 도입
4. 민감 로그 제거
5. README/AGENTS 문서 최신화
