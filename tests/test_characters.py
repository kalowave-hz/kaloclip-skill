from kaloclip.cli import main

IMG = "739230=https://resource.kaloclip.com/a.png"
CHARACTER = {
    "id": 4521, "category": "MODEL", "name": "Mia", "personalIntro": "warm",
    "mainImage": {"imageUrl": "https://r/main.png"}, "otherImages": [{"imageUrl": "https://r/side.png"}],
    "bindState": "BOUND", "platformSummary": None, "voiceAssetId": None, "voiceName": None,
}
VOICE = {"id": 88, "name": "Mia voice", "voiceId": "v-1", "provider": "TENCENT", "source": "CLONED",
         "cloneState": "SUCCEEDED", "gender": "female", "languages": ["en"],
         "sampleAudioUrl": "https://r/a.mp3", "previewAudioUrl": "https://r/a.mp3"}


def ok(data):
    return {"success": True, "code": None, "message": None, "data": data}


def fail(code, message, data=None):
    return {"success": False, "code": code, "message": message, "data": data}


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


def calls(server, method, path):
    return [r for r in server.requests if r[0] == method and r[1] == path]


# --- characters ----------------------------------------------------------------

def test_character_list_is_the_default_and_shows_use_hint(capsys, env):
    env.responses["/character-assets"] = ok({"data": [CHARACTER], "pageNo": 1, "pageSize": 20, "total": 1})
    code, out = run(capsys, "character")
    assert code == 0, out
    assert '4521,Mia,MODEL,BOUND,null,null,"https://r/main.png"' in out
    assert "--character <id>" in out and "clip character voice" in out
    (_, _, query, _, _), = calls(env, "GET", "/character-assets")
    assert query == {"pageNo": "1", "pageSize": "20"}


def test_character_list_empty_suggests_create(capsys, env):
    env.responses["/character-assets"] = ok({"data": [], "pageNo": 1, "pageSize": 20, "total": 0})
    code, out = run(capsys, "characters", "list", "--category", "ANIMAL")
    assert code == 0
    assert "characters: 0 results" in out and "clip character create" in out
    assert calls(env, "GET", "/character-assets")[0][2]["category"] == "ANIMAL"


def test_character_get(capsys, env):
    env.responses["/character-assets/detail"] = ok(CHARACTER)
    code, out = run(capsys, "character", "get", "4521")
    assert code == 0, out
    assert "intro: warm" in out and "https://r/side.png" in out
    assert calls(env, "GET", "/character-assets/detail")[0][2] == {"assetId": "4521"}


def test_character_create_is_multipart_and_never_resent(capsys, env, tmp_path):
    main_img = tmp_path / "front.png"
    main_img.write_bytes(b"\x89PNG main")
    side = tmp_path / "side.jpg"
    side.write_bytes(b"JPEG side")
    env.responses["/character-assets"] = ok(CHARACTER)
    code, out = run(capsys, "character", "create", "--name", "Mia", "--main-image", str(main_img),
                    "--other-image", str(side), "--intro", "warm")
    assert code == 0, out
    assert "character_id: 4521" in out
    (_, _, _, headers, body), = calls(env, "POST", "/character-assets")
    assert headers["content-type"].startswith("multipart/form-data")
    assert b'name="category"\r\n\r\nMODEL' in body and b'name="name"\r\n\r\nMia' in body
    assert b'name="personalIntro"\r\n\r\nwarm' in body
    assert b'name="mainImage"; filename="front.png"' in body and b"\x89PNG main" in body
    assert b'name="otherImages"; filename="side.jpg"' in body


def test_character_create_5xx_is_not_retried(capsys, env, tmp_path):
    main_img = tmp_path / "front.png"
    main_img.write_bytes(b"x")
    env.responses["/character-assets"] = (502, None)
    code, out = run(capsys, "character", "create", "--name", "Mia", "--main-image", str(main_img))
    assert code != 0
    assert len(calls(env, "POST", "/character-assets")) == 1
    assert "clip character list --name 'Mia'" in out


def test_character_limit_is_not_a_retry(capsys, env, tmp_path):
    main_img = tmp_path / "front.png"
    main_img.write_bytes(b"x")
    env.responses["/character-assets"] = (400, fail("CHARACTER_ASSET_LIMIT_EXCEEDED", "limit"))
    code, out = run(capsys, "character", "create", "--name", "Mia", "--main-image", str(main_img))
    assert code != 0
    assert "Free 3 / Pro 10 / Max 50" in out and "don't retry" in out


def test_character_create_checks_locally(capsys, env, tmp_path):
    doc = tmp_path / "a.txt"
    doc.write_text("x")
    code, out = run(capsys, "character", "create", "--name", "Mia", "--main-image", str(doc))
    assert code == 2 and "JPEG/PNG/GIF/WebP" in out
    code, out = run(capsys, "character", "create", "--name", "x" * 51, "--main-image", str(doc))
    assert code == 2 and "1-50" in out
    assert env.requests == []


def test_character_voice_bind_and_clear(capsys, env):
    env.responses["/character-assets/voice"] = ok({**CHARACTER, "voiceAssetId": 88, "voiceName": "Mia voice"})
    code, out = run(capsys, "character", "voice", "4521", "--voice", "88")
    assert code == 0, out
    (_, _, query, _, body), = calls(env, "PUT", "/character-assets/voice")
    assert query == {"assetId": "4521"} and body == {"voiceAssetId": 88}
    run(capsys, "character", "voice", "4521", "--clear")
    assert calls(env, "PUT", "/character-assets/voice")[-1][4] == {"voiceAssetId": None}


def test_character_voice_needs_exactly_one_choice(capsys, env):
    code, out = run(capsys, "character", "voice", "4521")
    assert code == 2 and "--clear" in out
    code, out = run(capsys, "character", "voice", "4521", "--voice", "88", "--clear")
    assert code == 2
    assert env.requests == []


# --- voices --------------------------------------------------------------------

def test_voice_list(capsys, env):
    env.responses["/voice-assets"] = ok({"data": [VOICE], "pageNo": 1, "pageSize": 20, "total": 1})
    code, out = run(capsys, "voice")
    assert code == 0, out
    assert '88,Mia voice,CLONED,female,en,"https://r/a.mp3"' in out


def test_voice_clone_dry_run_then_submit(capsys, env, tmp_path):
    audio = tmp_path / "sample.m4a"
    audio.write_bytes(b"AUDIO")
    argv = ["voice", "clone", "--name", "Mia voice", "--language", "en", "--gender", "female", "--audio", str(audio)]
    code, out = run(capsys, *argv)
    assert code == 0
    assert "dry_run" in out and "credits: 20" in out
    assert env.requests == []

    env.responses["/voice-assets/clone"] = ok(VOICE)
    code, out = run(capsys, *argv, "--yes")
    assert code == 0, out
    assert "voice_id: 88" in out and "clip character voice <character_id> --voice 88" in out
    (_, _, _, headers, body), = calls(env, "POST", "/voice-assets/clone")
    assert "idempotency-key" not in headers  # deduplicated by form + audio upstream
    assert b'name="creditSourceType"\r\n\r\nOPENAPI' in body and b'name="gender"\r\n\r\nfemale' in body
    assert b'name="audio"; filename="sample.m4a"' in body and b"AUDIO" in body


def test_voice_clone_unclear_failure_is_not_resent(capsys, env, tmp_path):
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"AUDIO")
    env.responses["/voice-assets/clone"] = (500, None)
    code, out = run(capsys, "voice", "clone", "--name", "v", "--language", "en", "--gender", "male",
                    "--audio", str(audio), "--yes")
    assert code != 0
    assert len(calls(env, "POST", "/voice-assets/clone")) == 1
    assert "clip voice list" in out and "never a different one" in out


def test_voice_clone_in_progress(capsys, env, tmp_path):
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"AUDIO")
    env.responses["/voice-assets/clone"] = (409, fail("VOICE_CLONE_IN_PROGRESS", "busy"))
    code, out = run(capsys, "voice", "clone", "--name", "v", "--language", "en", "--gender", "male",
                    "--audio", str(audio), "--yes")
    assert code != 0
    assert "don't switch to another recording" in out


def test_voice_clone_checks_audio_locally(capsys, env, tmp_path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"x")
    code, out = run(capsys, "voice", "clone", "--name", "v", "--language", "en", "--gender", "male",
                    "--audio", str(audio))
    assert code == 2 and "mp3" in out
    assert env.requests == []


# --- character in script / video --------------------------------------------------

def test_script_and_video_carry_the_character(capsys, env):
    env.responses["/scripts"] = [ok(7), ok({"id": 7, "state": "completed", "jobType": "REFERENCE_SCRIPT_GENERATE",
                                           "output": {"script": "S", "metadata": {"onCamera": "person",
                                                                                  "demo": None}}})]
    code, out = run(capsys, "script", "create", "--image", IMG, "--title", "t", "--category", "c",
                    "--model", "giv15", "--duration", "15", "--character", "4521", "--yes")
    assert code == 0, out
    (_, _, _, _, body), = calls(env, "POST", "/scripts")
    assert body["characterAssetId"] == 4521

    env.responses["/videos"] = ok(9)
    code, out = run(capsys, "video", "create", "--script-job", "7", "--voice", "88", "--yes")
    assert code == 0, out
    (_, _, _, _, body), = calls(env, "POST", "/videos")
    assert body["characterAssetId"] == 4521  # reused from the draft
    assert body["voiceAssetId"] == 88
    assert body["scriptMetadata"] == {"onCamera": "person", "demo": None}


def test_edited_script_still_sends_the_drafts_metadata(capsys, env, tmp_path):
    edited = tmp_path / "e.txt"
    edited.write_text("Edited")
    env.responses["/scripts"] = ok({"id": 7, "state": "completed", "jobType": "REFERENCE_SCRIPT_GENERATE",
                                    "output": {"script": "S", "metadata": {"onCamera": "product-only",
                                                                           "demo": "strict"}}})
    env.responses["/videos"] = ok(9)
    code, out = run(capsys, "video", "create", "--script-job", "7", "--script-file", str(edited), "--title", "T",
                    "--image", IMG, "--model", "giv15", "--duration", "15", "--yes")
    assert code == 0, out
    (_, _, _, _, body), = calls(env, "POST", "/videos")
    assert body["script"] == "Edited"
    assert body["scriptMetadata"] == {"onCamera": "product-only", "demo": "strict"}


def test_non_giv15_draft_sends_no_metadata(capsys, env):
    env.responses["/videos"] = ok(9)
    code, out = run(capsys, "video", "create", "--script", "S", "--title", "T", "--image", IMG,
                    "--model", "sd2", "--duration", "15", "--yes")
    assert code == 0, out
    (_, _, _, _, body), = calls(env, "POST", "/videos")
    assert "scriptMetadata" not in body and "voiceAssetId" not in body and "characterAssetId" not in body


def test_character_needs_a_supported_model(capsys, env):
    code, out = run(capsys, "script", "create", "--image", IMG, "--title", "t", "--category", "c",
                    "--model", "sr2l", "--duration", "15", "--character", "4521")
    assert code == 2
    assert "sd2, sd25, giv15, w3" in out
    code, out = run(capsys, "video", "create", "--script", "S", "--title", "T", "--image", IMG,
                    "--model", "sr2l", "--duration", "15", "--voice", "88")
    assert code == 2 and "--voice works with models" in out
    assert env.requests == []


def test_character_allows_five_product_images(capsys, env):
    images = [f"{i}=https://r/{i}.png" for i in range(1, 7)]
    argv = ["script", "create", "--title", "t", "--category", "c", "--model", "sd2", "--duration", "15",
            "--character", "4521"]
    for img in images:
        argv += ["--image", img]
    code, out = run(capsys, *argv)
    assert code == 2 and "at most 5 product images" in out


def test_product_link_images_are_capped_at_five_with_a_character(capsys, env):
    env.responses["/products/resolve"] = ok({
        "productTitle": "P", "categoryNames": ["c"],
        "imageInfos": [{"assetId": i, "imageUrl": f"https://r/{i}.png"} for i in range(1, 7)],
    })
    code, out = run(capsys, "script", "create", "--product-link", "https://shop.tiktok.com/view/product/1",
                    "--model", "sd2", "--duration", "15", "--character", "4521", "--json")
    assert code == 0, out
    assert out.count('"assetId"') == 5


def test_voice_replace_failure_hint(capsys, env):
    env.responses["/jobs"] = ok({"id": 9, "jobType": "VIDEO_CREATION", "state": "failed",
                                 "errorCode": "VOICE_REPLACE", "errorMessage": "voice failed"})
    code, out = run(capsys, "job", "9")
    assert code == 0
    assert "clip voice list" in out
