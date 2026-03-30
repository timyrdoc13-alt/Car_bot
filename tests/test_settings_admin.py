from car_channel_bot.config.settings import Settings, _parse_admin_ids


def test_parse_admin_ids_spacing() -> None:
    assert _parse_admin_ids("228378111, 1197488973") == "228378111,1197488973"
    assert _parse_admin_ids("228378111;1197488973") == "228378111,1197488973"


def test_settings_admin_id_list() -> None:
    s = Settings(
        bot_token="x",
        channel_id=-1,
        admin_ids="228378111,1197488973",
    )
    assert s.admin_id_list == [228378111, 1197488973]
