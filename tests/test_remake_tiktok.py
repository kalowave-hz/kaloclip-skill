import time

from kaloclip.cli import main

IMG = "739230=https://resource.kaloclip.com/a.png"
TT = "https://www.tiktok.com/@seller/video/7312345678901234567"
PRODUCT = ["--image", IMG, "--title", "Wireless Earbuds", "--product-id", "1234567890"]
PUBLISH = ["tiktok", "publish", "--account", "31", "--asset", "207630", "--product-id", "1729384756",
           "--product-title", "Wireless Earbuds", "--title", "Wireless Earbuds", "--caption", "Tiny buds"]


def ok(data):
    return {"success": True, "code": None, "message": None, "data": data}


def fail(code, message, data=None):
    return {"success": False, "code": code, "message": message, "data": data}


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


def calls(server, method, path):
    return [r for r in server.requests if r[0] == method and r[1] == path]


# --- remake ------------------------------------------------------------------------

def test_remake_options(capsys, env):
    env.responses["/remakes/options"] = ok({
        "modelOptions": [{"label": "Seedance 2", "value": "sd2", "description": "fast"},
                         {"label": "Seedance 2.5", "value": "sd25", "description": "best"}],
        "resolutionOptions": [{"label": "720P", "value": "720P"}],
        "aspectRatioOptions": [{"label": "9:16", "value": "RATIO_9_16"}],
        "defaultModel": "sd2", "defaultResolution": "720P", "defaultAspectRatio": "RATIO_9_16",
    })
    code, out = run(capsys, "remake", "options", "--duration", "12")
    assert code == 0, out
    assert "sd2,Seedance 2,true,fast" in out and "sd25,Seedance 2.5,false,best" in out
    assert calls(env, "GET", "/remakes/options")[0][2] == {"duration": "12"}


def test_remake_create_dry_run_previews_and_maps_fields(capsys, env):
    env.responses["/remakes/preview"] = ok(36.5)
    code, out = run(capsys, "remake", "create", "--video", TT, *PRODUCT, "--model", "sd2",
                    "--description", "same hook", "--country", "US", "--language", "en", "--bgm", "keep")
    assert code == 0, out
    assert "credits: 36.5" in out and "--yes --idempotency-key" in out
    assert calls(env, "POST", "/remakes") == []
    (_, _, _, _, preview), = calls(env, "POST", "/remakes/preview")
    assert preview == {"videoSource": "TikTok", "videoUrl": TT, "resolution": "720P", "internalModelId": "sd2"}


def test_remake_create_submits_with_key(capsys, env):
    env.responses["/remakes"] = ok(5150)
    code, out = run(capsys, "remake", "create", "--video", TT, *PRODUCT, "--model", "sd2",
                    "--description", "same hook", "--country", "US", "--yes", "--idempotency-key", "k-1")
    assert code == 0, out
    assert "job_id: 5150" in out
    (_, _, _, headers, body), = calls(env, "POST", "/remakes")
    assert headers["idempotency-key"] == "k-1"
    assert body == {
        "creditSourceType": "OPENAPI", "videoSource": "TikTok", "videoUrl": TT,
        "imageInfos": [{"assetId": 739230, "imageUrl": "https://resource.kaloclip.com/a.png"}],
        "productTitle": "Wireless Earbuds", "productId": "1234567890", "userInputPrompt": "same hook",
        "productCountry": "US", "videoLanguage": "en", "internalModelId": "sd2",
        "aspectRatio": "RATIO_9_16", "quantity": 1, "resolution": "720P", "bgmOption": "REGENERATE_BGM",
    }
    assert calls(env, "POST", "/remakes/preview") == []


def test_remake_from_own_asset(capsys, env):
    env.responses["/remakes"] = ok(1)
    code, out = run(capsys, "remake", "create", "--video-asset", "207630", *PRODUCT, "--model", "sd2", "--yes")
    assert code == 0, out
    body = calls(env, "POST", "/remakes")[0][4]
    assert body["videoSource"] == "Kaloclip" and body["videoAssetId"] == 207630 and "videoUrl" not in body


def test_remake_reference_must_be_exactly_one(capsys, env):
    code, out = run(capsys, "remake", "create", *PRODUCT, "--model", "sd2")
    assert code == 2 and "exactly one of --video" in out
    code, out = run(capsys, "remake", "create", "--video", TT, "--video-asset", "1", *PRODUCT, "--model", "sd2")
    assert code == 2
    code, out = run(capsys, "remake", "preview", "--video", "https://www.instagram.com/reel/x", "--model", "sd2")
    assert code == 2 and "Instagram" in out
    code, out = run(capsys, "remake", "preview", "--video", "https://example.com/v.mp4", "--model", "sd2")
    assert code == 2 and "--source" in out
    assert env.requests == []


def test_remake_too_long_reference_stops_the_dry_run(capsys, env):
    env.responses["/remakes/preview"] = fail("VIDEO_REMAKE_DURATION_EXCEEDED", "too long")
    code, out = run(capsys, "remake", "create", "--video", TT, *PRODUCT, "--model", "sd2")
    assert code == 1
    assert "longer than 30 seconds" in out and "dry_run" not in out


def test_remake_job_completion_hands_over_the_video(capsys, env):
    env.responses["/jobs"] = ok({"id": 5150, "jobType": "VIDEO_REMAKE", "state": "completed",
                                 "output": {"videoUrl": "https://r/v.mp4", "userAssetId": 9}})
    code, out = run(capsys, "job", "5150")
    assert code == 0 and "videoUrl is the finished video" in out


# --- tiktok ------------------------------------------------------------------------

def test_tiktok_bare_lists_accounts(capsys, env):
    env.responses["/tiktok-publish/accounts"] = ok([
        {"linkId": 31, "accountName": "shop", "accountUserType": "CREATOR", "region": "US",
         "expired": False, "canPublishVideo": True},
    ])
    code, out = run(capsys, "tiktok")
    assert code == 0, out
    assert "31,shop,CREATOR,US,false,true" in out


def test_tiktok_accounts_empty_points_to_auth(capsys, env):
    env.responses["/tiktok-publish/accounts"] = ok([])
    code, out = run(capsys, "tiktok", "accounts")
    assert code == 0 and "clip tiktok auth" in out


def test_tiktok_auth(capsys, env):
    env.responses["/tiktok-publish/auth-url"] = ok({"authUrl": "https://tt/auth?state=x"})
    code, out = run(capsys, "tiktok", "auth", "--region", "US")
    assert code == 0 and "https://tt/auth?state=x" in out
    (method, _, query, _, _), = calls(env, "POST", "/tiktok-publish/auth-url")
    assert query == {"region": "US"}


def test_tiktok_music_paging_needs_search_id(capsys, env):
    code, out = run(capsys, "tiktok", "music", "pop", "--account", "31", "--page-token", "p2")
    assert code == 2 and env.requests == []
    env.responses["/tiktok-publish/music/search"] = ok({
        "music": [{"id": "m1", "title": "Pop", "author": "A", "duration": "30", "playUrls": ["https://r/m.mp3"]}],
        "hasMore": True, "nextPageToken": "p2", "searchId": "s1"})
    code, out = run(capsys, "tiktok", "music", "pop", "--account", "31")
    assert code == 0 and "--page-token p2 --search-id s1" in out and "REPLACES" in out


def test_tiktok_publish_dry_run_sends_nothing(capsys, env):
    code, out = run(capsys, *PUBLISH)
    assert code == 0, out
    assert "Nothing was sent" in out and "publicly" in out
    assert env.requests == []


def test_tiktok_publish_title_rules(capsys, env):
    args = list(PUBLISH)
    i = args.index("--title") + 1
    for bad in ("Buy now!", "x" * 31, "限时，特价"):
        args[i] = bad
        code, out = run(capsys, *args)
        assert code == 2, bad
    assert env.requests == []


def test_tiktok_publish_submits_and_waits_for_confirm(capsys, env):
    env.responses["/tiktok-publish/videos"] = ok({"id": 9012, "status": "INIT"})
    env.responses["/tiktok-publish/videos/result"] = [
        ok({"id": 9012, "status": "PRE_CHECKING"}),
        ok({"id": 9012, "status": "PRE_CHECK_SUCCESS", "needConfirm": True,
            "issues": [{"risk": "LOW_QUALITY", "suggestions": "use a sharper video"}]}),
    ]
    when = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 86400))
    code, out = run(capsys, *PUBLISH, "--precheck", "--schedule", when, "--yes", "--wait")
    assert code == 0, out
    assert "PRE_CHECK_SUCCESS" in out and "LOW_QUALITY" in out and "clip tiktok confirm 9012" in out
    (_, _, _, headers, body), = calls(env, "POST", "/tiktok-publish/videos")
    assert "idempotency-key" not in headers
    assert body["publishMode"] == "SCHEDULE" and body["publishTime"] > time.time() * 1000
    assert body["linkId"] == 31 and body["assetId"] == 207630 and body["description"] == "Tiny buds"
    assert body["isAiGenerated"] is True and body["needPrecheck"] is True
    assert "autoConfirmPrecheckIssues" not in body
    assert len(calls(env, "GET", "/tiktok-publish/videos/result")) == 2


def test_tiktok_publish_duplicate_points_to_records(capsys, env):
    env.responses["/tiktok-publish/videos"] = (409, fail("PUBLISH_DUPLICATE", "dup"))
    code, out = run(capsys, *PUBLISH, "--yes")
    assert code == 1
    assert "clip tiktok records --asset" in out
    assert len(calls(env, "POST", "/tiktok-publish/videos")) == 1


def test_tiktok_publish_schedule_bounds(capsys, env):
    code, out = run(capsys, *PUBLISH, "--schedule", "2001-01-01T00:00:00Z")
    assert code == 2 and "future" in out
    code, out = run(capsys, *PUBLISH, "--schedule", str(int((time.time() + 40 * 86400) * 1000)))
    assert code == 2 and "30 days" in out


def test_tiktok_confirm_dry_run_then_yes(capsys, env):
    env.responses["/tiktok-publish/videos/result"] = ok({"id": 9012, "status": "PRE_CHECK_SUCCESS",
                                                         "needConfirm": True, "issues": []})
    code, out = run(capsys, "tiktok", "confirm", "9012")
    assert code == 0 and "Nothing was sent" in out
    assert calls(env, "POST", "/tiktok-publish/videos/confirm") == []
    env.responses["/tiktok-publish/videos/result"] = ok({"id": 9012, "status": "PUBLISHING"})
    code, out = run(capsys, "tiktok", "confirm", "9012", "--yes")
    assert code == 0, out
    assert calls(env, "POST", "/tiktok-publish/videos/confirm")[0][4] == {"id": 9012}


def test_tiktok_records_filters(capsys, env):
    env.responses["/tiktok-publish/videos/page"] = ok({
        "data": [{"id": 1, "status": "SUCCESS", "publishUrl": "https://tt/v/1", "assetId": 207630,
                  "performance": {"orderCount": 3, "gmvAmount": "29.97", "gmvCurrency": "USD"}}],
        "pageNo": 1, "pageSize": 20, "total": 1})
    code, out = run(capsys, "tiktok", "records", "--asset", "207630", "--status", "SUCCESS", "--status", "FAIL")
    assert code == 0, out
    assert "29.97 USD" in out
    query = calls(env, "GET", "/tiktok-publish/videos/page")[0][2]
    assert query == {"assetId": "207630", "statuses": "SUCCESS,FAIL", "pageNo": "1", "pageSize": "20"}


def test_tiktok_cancel(capsys, env):
    env.responses["/tiktok-publish/videos/result"] = ok({"id": 9012, "status": "CANCEL"})
    code, out = run(capsys, "tiktok", "cancel", "9012")
    assert code == 0 and "Cancelled" in out
    assert calls(env, "POST", "/tiktok-publish/videos/cancel")[0][4] == {"id": 9012}
