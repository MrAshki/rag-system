from evaluation.tuning_freeze import create_manifest, verify_manifest


def test_tuning_freeze_detects_post_freeze_change(tmp_path):
    production = tmp_path / "router.py"
    production.write_text("route = 'focused_rag'\n", encoding="utf-8")
    manifest = create_manifest(tmp_path, [production])
    assert verify_manifest(tmp_path, manifest) == []

    production.write_text("route = 'specific_section'\n", encoding="utf-8")
    assert verify_manifest(tmp_path, manifest) == ["router.py"]
