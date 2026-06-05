from feishu_browser_use.server import _parse_login_command


def test_parse_spaced_login_command():
	assert _parse_login_command("登录 美团 朝阳店") == ("meituan", "朝阳店")


def test_parse_compact_login_command():
	assert _parse_login_command("登录美团江湖饭煸") == ("meituan", "江湖饭煸")


def test_parse_login_command_with_backend_words():
	assert _parse_login_command("登录美团商家后台江湖饭煸") == ("meituan", "江湖饭煸")
