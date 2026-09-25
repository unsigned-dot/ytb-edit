import json

from ytb_edit.core.models import AudioFormat, OutputMode, SourceFiles
from ytb_edit.services.cache import SourceCache
from ytb_edit.settings import AppSettings, load_settings, save_settings


def _make_source(cache: SourceCache, video_id: str) -> SourceFiles:
    directory = cache.dir_for(video_id)
    directory.mkdir(parents=True)
    (directory / "v.webm").write_bytes(b"video")
    (directory / "a.m4a").write_bytes(b"audio")
    return SourceFiles(directory / "v.webm", directory / "a.m4a")


def test_cache_roundtrip(tmp_path):
    cache = SourceCache(tmp_path)
    assert cache.load("abc") is None
    source = _make_source(cache, "abc")
    cache.save("abc", source)
    assert cache.load("abc") == source
    assert cache.size_of("abc") == 10 + len(json.dumps({"video": "v.webm", "audio": "a.m4a"}))


def test_cache_ignores_missing_or_empty_files(tmp_path):
    cache = SourceCache(tmp_path)
    source = _make_source(cache, "abc")
    cache.save("abc", source)
    source.video_path.unlink()
    assert cache.load("abc") == SourceFiles(None, source.audio_path)
    source.audio_path.write_bytes(b"")
    assert cache.load("abc") is None


def test_purge_incomplete(tmp_path):
    cache = SourceCache(tmp_path)
    cache.save("done", _make_source(cache, "done"))
    (cache.dir_for("done") / "x.webm.part").write_bytes(b"...")
    _make_source(cache, "interrupted")  # pas de source.json
    cache.purge_incomplete()
    assert cache.load("done") is not None
    assert not (cache.dir_for("done") / "x.webm.part").exists()
    assert not cache.dir_for("interrupted").exists()


def test_delete_missing_is_ok(tmp_path):
    assert SourceCache(tmp_path).delete("nothing")


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    settings = AppSettings(output_dir="C:/Clips", audio_format="mp3", cache_limit_gb=5)
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded == settings
    assert loaded.audio is AudioFormat.MP3


def test_settings_missing_or_corrupted_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "absent.json") == AppSettings()
    bad = tmp_path / "bad.json"
    bad.write_text("{pas du json", encoding="utf-8")
    assert load_settings(bad) == AppSettings()
    bad.write_text("[1, 2]", encoding="utf-8")
    assert load_settings(bad) == AppSettings()


def test_settings_wrong_types_and_unknown_values_are_ignored(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(
        json.dumps(
            {
                "cache_limit_gb": "beaucoup",
                "default_mode": "???",
                "output_dir": "D:/x",
                "inconnu": 1,
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.cache_limit_gb == AppSettings().cache_limit_gb
    assert settings.output_dir == "D:/x"
    assert settings.mode is OutputMode.AUDIO_VIDEO
